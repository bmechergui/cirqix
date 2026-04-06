// Ce fichier est importé uniquement côté client (via dynamic import + ssr:false)
// PixiJS v8 — API async Application, Graphics chainable
import { Application, Container, Graphics, Text, TextStyle } from 'pixi.js';
import { mmToPx, LAYER_COLORS } from './layers';
import type { PCBState, DRCViolation, SchemaComponent, SchemaNet } from '@layrix/types';

interface PlacementItem {
  ref: string;
  x_mm: number;
  y_mm: number;
  rotation: number;
  side: 'front' | 'back';
}

interface PlacementData {
  placements?: PlacementItem[];
  board_width_mm?: number;
  board_height_mm?: number;
}

export interface ZoomControls {
  zoomIn: () => void;
  zoomOut: () => void;
  resetZoom: () => void;
}

const BOARD_BG   = 0x0d1a00;
const COMP_LINE  = 0x888888;
const DRC_ERROR  = 0xff2222;
const DRC_WARN   = 0xffaa00;
const ZOOM_STEP  = 1.3;
const MIN_SCALE  = 0.1;
const MAX_SCALE  = 20;

// Map tscircuit logical layer names → KiCad layer names used in LAYER_COLORS
function toKicadLayer(layer: string | undefined, forSilk = false): string {
  if (!layer) return forSilk ? 'F.SilkS' : 'F.Cu';
  if (layer === 'top')    return forSilk ? 'F.SilkS' : 'F.Cu';
  if (layer === 'bottom') return forSilk ? 'B.SilkS' : 'B.Cu';
  return layer;
}

export class PCBRenderer {
  private app: Application;

  // Viewport container — holds all layers, scaled/translated for zoom + auto-fit
  private viewport      = new Container();
  private boardLayer    = new Container();
  private componentLayer = new Container();
  private drcLayer      = new Container();
  private labelLayer    = new Container();

  // Board dimensions in px (set after render so zoomIn/zoomOut can re-center)
  private boardWpx = 0;
  private boardHpx = 0;
  private baseScale = 1;

  // Placeholder text — tracked so clearAll() can remove it cleanly
  private placeholderLabel: Text | null = null;

  // Pan state
  private isPanning   = false;
  private panStartX   = 0;
  private panStartY   = 0;
  private panOriginX  = 0;
  private panOriginY  = 0;

  constructor(app: Application) {
    this.app = app;
    this.viewport.addChild(this.boardLayer);
    this.viewport.addChild(this.componentLayer);
    this.viewport.addChild(this.drcLayer);
    this.viewport.addChild(this.labelLayer);
    app.stage.addChild(this.viewport);
    this.initPan();
  }

  private initPan(): void {
    const stage   = this.app.stage;
    const canvas  = this.app.canvas as HTMLCanvasElement;

    stage.eventMode = 'static';
    stage.hitArea   = this.app.screen;

    stage.on('pointerdown', (e) => {
      this.isPanning  = true;
      this.panStartX  = e.globalX;
      this.panStartY  = e.globalY;
      this.panOriginX = this.viewport.x;
      this.panOriginY = this.viewport.y;
      canvas.style.cursor = 'grabbing';
    });

    stage.on('pointermove', (e) => {
      if (!this.isPanning) return;
      this.viewport.x = this.panOriginX + (e.globalX - this.panStartX);
      this.viewport.y = this.panOriginY + (e.globalY - this.panStartY);
    });

    const stopPan = () => {
      this.isPanning = false;
      canvas.style.cursor = 'grab';
    };
    stage.on('pointerup',        stopPan);
    stage.on('pointerupoutside', stopPan);

    canvas.style.cursor = 'grab';

    // Wheel zoom — centered on cursor position
    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
      const newScale = Math.min(Math.max(this.viewport.scale.x * factor, MIN_SCALE), MAX_SCALE);

      // Zoom toward cursor: adjust viewport position so the point under
      // the cursor stays fixed after scaling
      const rect    = canvas.getBoundingClientRect();
      const mouseX  = e.clientX - rect.left;
      const mouseY  = e.clientY - rect.top;
      const ratio   = newScale / this.viewport.scale.x;
      this.viewport.x = mouseX - ratio * (mouseX - this.viewport.x);
      this.viewport.y = mouseY - ratio * (mouseY - this.viewport.y);
      this.viewport.scale.set(newScale);
    }, { passive: false });
  }

  render(state: PCBState | null, layerVisibility: Record<string, boolean> = {}): void {
    this.clearAll();

    if (Array.isArray(state?.components) && state.components.length > 0) {
      this.renderFromComponents(state.components, state.connections ?? [], layerVisibility);
      this.autoFit();
      if (state.drcViolations?.length) {
        for (const v of state.drcViolations) this.renderDRCMarker(v);
      }
      return;
    }

    if (!state?.placement) {
      this.renderPlaceholder();
      return;
    }

    const placement = state.placement as PlacementData;
    this.boardWpx = mmToPx(placement.board_width_mm ?? 50);
    this.boardHpx = mmToPx(placement.board_height_mm ?? 50);
    this.renderBoard(this.boardWpx, this.boardHpx);
    if (placement.placements) {
      for (const comp of placement.placements) this.renderComponent(comp);
    }
    this.autoFit();
    if (state.drcViolations?.length) {
      for (const v of state.drcViolations) this.renderDRCMarker(v);
    }
  }

  // ---------------------------------------------------------------------------
  // Zoom controls — exposed via ZoomControls interface
  // ---------------------------------------------------------------------------

  zoomIn(): void {
    const s = Math.min(this.viewport.scale.x * ZOOM_STEP, MAX_SCALE);
    this.applyScale(s);
  }

  zoomOut(): void {
    const s = Math.max(this.viewport.scale.x / ZOOM_STEP, MIN_SCALE);
    this.applyScale(s);
  }

  resetZoom(): void {
    this.applyScale(this.baseScale);
  }

  private applyScale(s: number): void {
    if (!this.app?.screen) return;
    this.viewport.scale.set(s);
    // Re-center around the board
    this.viewport.x = (this.app.screen.width  - this.boardWpx * s) / 2;
    this.viewport.y = (this.app.screen.height - this.boardHpx * s) / 2;
  }

  // ---------------------------------------------------------------------------
  // Auto-fit: scale the viewport so the content fills ~85% of the canvas.
  // Fits to component+trace bounding box when components are clustered;
  // falls back to board dimensions when content fills ≥40% of the board.
  // ---------------------------------------------------------------------------

  private autoFit(): void {
    const PAD = 0.85; // visible area fraction

    // Try to fit the actual rendered content (components + traces)
    const contentBounds = this.componentLayer.getBounds();
    const hasContent = contentBounds.width > 0 && contentBounds.height > 0;

    if (hasContent) {
      // Use content bounds — pad by 20% around the tight box
      const cw = contentBounds.width  * 1.2;
      const ch = contentBounds.height * 1.2;
      const scaleX = (this.app.screen.width  * PAD) / cw;
      const scaleY = (this.app.screen.height * PAD) / ch;
      this.baseScale = Math.min(scaleX, scaleY, MAX_SCALE);

      // Center on content midpoint
      const cx = contentBounds.x + contentBounds.width  / 2;
      const cy = contentBounds.y + contentBounds.height / 2;
      this.viewport.scale.set(this.baseScale);
      this.viewport.x = this.app.screen.width  / 2 - cx * this.baseScale;
      this.viewport.y = this.app.screen.height / 2 - cy * this.baseScale;
      return;
    }

    // Fallback: fit to board dimensions
    if (this.boardWpx <= 0 || this.boardHpx <= 0) return;
    const scaleX = (this.app.screen.width  * PAD) / this.boardWpx;
    const scaleY = (this.app.screen.height * PAD) / this.boardHpx;
    this.baseScale = Math.min(scaleX, scaleY, MAX_SCALE);
    this.applyScale(this.baseScale);
  }

  // ---------------------------------------------------------------------------
  // Circuit-json rendering (all coords relative to board origin 0,0)
  // ---------------------------------------------------------------------------

  private renderFromCircuitJson(
    elements: unknown[],
    layerVisibility: Record<string, boolean>
  ): void {
    type AnyEl = { type: string; layer?: string; [k: string]: unknown };

    const boardEl = elements.find(
      (e) => (e as AnyEl).type === 'pcb_board'
    ) as { width: number; height: number } | undefined;

    this.boardWpx = mmToPx(boardEl?.width  ?? 50);
    this.boardHpx = mmToPx(boardEl?.height ?? 50);

    for (const raw of elements) {
      const el = raw as AnyEl;

      switch (el.type) {

        case 'pcb_board': {
          if (layerVisibility['Edge.Cuts'] === false) break;
          const g = new Graphics();
          g.rect(0, 0, this.boardWpx, this.boardHpx)
            .fill({ color: BOARD_BG });
          g.rect(0, 0, this.boardWpx, this.boardHpx)
            .stroke({ color: LAYER_COLORS['Edge.Cuts'] ?? 0xffff00, width: 1.5 });
          this.boardLayer.addChild(g);
          break;
        }

        case 'pcb_smtpad': {
          const kicad = toKicadLayer(el.layer);
          if (layerVisibility[kicad] === false) break;
          const pad = el as unknown as { x: number; y: number; width: number; height: number };
          const pw = mmToPx(pad.width);
          const ph = mmToPx(pad.height);
          const g = new Graphics();
          g.rect(mmToPx(pad.x) - pw / 2, mmToPx(pad.y) - ph / 2, pw, ph)
            .fill({ color: LAYER_COLORS[kicad] ?? 0xff5555, alpha: 0.85 });
          this.componentLayer.addChild(g);
          break;
        }

        case 'pcb_component': {
          const kicad = toKicadLayer(el.layer);
          if (layerVisibility[kicad] === false) break;
          const comp = el as unknown as { center: { x: number; y: number } };
          const cx = mmToPx(comp.center.x);
          const cy = mmToPx(comp.center.y);
          const r  = mmToPx(0.5);
          const g = new Graphics();
          g.moveTo(cx - r, cy).lineTo(cx + r, cy);
          g.moveTo(cx, cy - r).lineTo(cx, cy + r);
          g.stroke({ color: LAYER_COLORS[kicad] ?? 0xff5555, width: 1.5 });
          this.componentLayer.addChild(g);
          break;
        }

        case 'pcb_silkscreen_path': {
          const kicad = toKicadLayer(el.layer, true);
          if (layerVisibility[kicad] === false) break;
          const path = el as unknown as { route: Array<{ x: number; y: number }> };
          if (!path.route?.length) break;
          const [first, ...rest] = path.route;
          if (!first) break;
          const g = new Graphics();
          g.moveTo(mmToPx(first.x), mmToPx(first.y));
          for (const pt of rest) g.lineTo(mmToPx(pt.x), mmToPx(pt.y));
          g.stroke({ color: LAYER_COLORS[kicad] ?? 0xffffff, width: 0.75 });
          this.componentLayer.addChild(g);
          break;
        }

        case 'pcb_silkscreen_text': {
          const kicad = toKicadLayer(el.layer, true);
          if (layerVisibility[kicad] === false) break;
          const txt = el as unknown as {
            text: string;
            anchor_position: { x: number; y: number };
            font_size?: number;
          };
          if (!txt.text || !txt.anchor_position) break;
          const style = new TextStyle({
            fontSize: Math.max(mmToPx(txt.font_size ?? 0.6), 5),
            fill: LAYER_COLORS[kicad] ?? 0xffffff,
            fontFamily: 'monospace',
          });
          const label = new Text({ text: txt.text, style });
          label.x = mmToPx(txt.anchor_position.x) - label.width / 2;
          label.y = mmToPx(txt.anchor_position.y) - label.height / 2;
          this.componentLayer.addChild(label);
          break;
        }

        case 'pcb_copper_fill': {
          const fill = el as unknown as { x: number; y: number; width: number; height: number; layer?: string };
          const kicad = toKicadLayer(fill.layer ?? 'bottom');
          if (layerVisibility[kicad] === false) break;
          const color = LAYER_COLORS[kicad] ?? 0x4488ff;
          const g = new Graphics();
          g.rect(mmToPx(fill.x), mmToPx(fill.y), mmToPx(fill.width), mmToPx(fill.height))
            .fill({ color, alpha: 0.18 })
            .stroke({ color, width: 1, alpha: 0.35 });
          this.boardLayer.addChild(g);
          break;
        }

        case 'pcb_trace': {
          const kicad = toKicadLayer(el.layer);
          if (layerVisibility[kicad] === false) break;
          const trace = el as unknown as {
            route: Array<{ x: number; y: number }>;
            stroke_width?: number;
          };
          if (!trace.route?.length) break;
          const traceW = Math.max(mmToPx(trace.stroke_width ?? 0.2), 1);
          const [first, ...rest] = trace.route;
          if (!first) break;
          const g = new Graphics();
          g.moveTo(mmToPx(first.x), mmToPx(first.y));
          for (const pt of rest) g.lineTo(mmToPx(pt.x), mmToPx(pt.y));
          g.stroke({ color: LAYER_COLORS[kicad] ?? 0xff5555, width: traceW });
          this.componentLayer.addChild(g);
          break;
        }

        default:
          break;
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Component-schema rendering (Circuit-Synth grid layout, PixiJS fallback)
  // ---------------------------------------------------------------------------

  private renderFromComponents(
    components: SchemaComponent[],
    connections: SchemaNet[],
    _layerVisibility: Record<string, boolean>
  ): void {
    const BOARD_W = 50;
    const BOARD_H = 50;
    this.boardWpx = mmToPx(BOARD_W);
    this.boardHpx = mmToPx(BOARD_H);
    this.renderBoard(this.boardWpx, this.boardHpx);

    const cols   = Math.max(1, Math.ceil(Math.sqrt(components.length)));
    const margin = 5;
    const usableW = BOARD_W - 2 * margin;
    const usableH = BOARD_H - 2 * margin;

    const positions = components.map((_, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      return {
        x_mm: margin + (col + 0.5) * (usableW / cols),
        y_mm: margin + (row + 0.5) * (usableH / Math.ceil(components.length / cols)),
      };
    });

    // Draw ratsnest lines
    const NET_COLORS = [0xD4820A, 0x4488FF, 0x22C55E, 0xF59E0B, 0xA855F7];
    const refIdx = new Map(components.map((c, i) => [c.ref, i]));
    connections.forEach((conn, ni) => {
      const color = NET_COLORS[ni % NET_COLORS.length]!;
      const pts = conn.pins.map((p) => positions[refIdx.get(p.ref) ?? 0]!);
      if (pts.length < 2) return;
      const g = new Graphics();
      g.moveTo(mmToPx(pts[0]!.x_mm), mmToPx(pts[0]!.y_mm));
      for (let k = 1; k < pts.length; k++) {
        g.lineTo(mmToPx(pts[k]!.x_mm), mmToPx(pts[k]!.y_mm));
      }
      g.stroke({ color, width: 1, alpha: 0.5 });
      this.componentLayer.addChild(g);
    });

    // Draw component boxes
    components.forEach((comp, i) => {
      const pos  = positions[i]!;
      const isIC = /U\d|IC/i.test(comp.ref);
      const size = mmToPx(isIC ? 8 : 3);
      const cx   = mmToPx(pos.x_mm);
      const cy   = mmToPx(pos.y_mm);

      const g = new Graphics();
      g.roundRect(cx - size / 2, cy - size / 2, size, size, isIC ? 2 : 1)
        .fill({ color: 0x1a1a1a })
        .stroke({ color: LAYER_COLORS['F.Cu'] ?? 0xD4820A, width: 1 });
      this.componentLayer.addChild(g);

      const style = new TextStyle({
        fontSize: isIC ? 8 : 6,
        fill: LAYER_COLORS['F.SilkS'] ?? 0xffffff,
        fontFamily: 'monospace',
      });
      const label = new Text({ text: comp.ref, style });
      label.x = cx - label.width / 2;
      label.y = cy - size / 2 - 10;
      this.labelLayer.addChild(label);
    });
  }

  // ---------------------------------------------------------------------------
  // Placement-based rendering (fallback, coords relative to board origin 0,0)
  // ---------------------------------------------------------------------------

  private renderBoard(w: number, h: number): void {
    const g = new Graphics();
    g.rect(0, 0, w, h)
      .fill({ color: BOARD_BG })
      .stroke({ color: LAYER_COLORS['Edge.Cuts'] ?? 0xffff00, width: 1.5 });
    this.boardLayer.addChild(g);
  }

  private renderComponent(comp: PlacementItem): void {
    const cx   = mmToPx(comp.x_mm);
    const cy   = mmToPx(comp.y_mm);
    const isIC = comp.ref.startsWith('U') || comp.ref.startsWith('IC');
    const size = mmToPx(isIC ? 8 : 3);

    const g = new Graphics();
    g.roundRect(cx - size / 2, cy - size / 2, size, size, isIC ? 2 : 1)
      .fill({ color: 0x2a2a2a })
      .stroke({ color: COMP_LINE, width: 1 });

    if (isIC) {
      g.circle(cx - size / 2 + 3, cy - size / 2 + 3, 2)
        .fill({ color: LAYER_COLORS['F.SilkS'] ?? 0xffffff, alpha: 0.5 });
    }

    this.componentLayer.addChild(g);

    const style = new TextStyle({
      fontSize: isIC ? 8 : 6,
      fill: LAYER_COLORS['F.SilkS'] ?? 0xffffff,
      fontFamily: 'monospace',
    });
    const label = new Text({ text: comp.ref, style });
    label.x = cx - label.width / 2;
    label.y = cy - size / 2 - 10;
    this.labelLayer.addChild(label);
  }

  private renderDRCMarker(v: DRCViolation): void {
    const cx    = mmToPx(v.x_mm);
    const cy    = mmToPx(v.y_mm);
    const color = v.severity === 'error' ? DRC_ERROR : DRC_WARN;
    const r     = mmToPx(1);

    const g = new Graphics();
    g.circle(cx, cy, r).stroke({ color, width: 2 });
    g.moveTo(cx - r * 0.7, cy).lineTo(cx + r * 0.7, cy);
    g.moveTo(cx, cy - r * 0.7).lineTo(cx, cy + r * 0.7);
    g.stroke({ color, width: 1.5 });

    this.drcLayer.addChild(g);
  }

  private renderPlaceholder(): void {
    const cx    = this.app.screen.width  / 2;
    const cy    = this.app.screen.height / 2;
    const style = new TextStyle({ fontSize: 12, fill: 0x444444, fontFamily: 'monospace' });
    const label = new Text({ text: 'Waiting for PCB data…', style });
    label.x = cx - label.width  / 2;
    label.y = cy - label.height / 2;
    this.placeholderLabel = label;
    this.app.stage.addChild(label);
  }

  private clearAll(): void {
    this.boardLayer.removeChildren();
    this.componentLayer.removeChildren();
    this.drcLayer.removeChildren();
    this.labelLayer.removeChildren();
    if (this.placeholderLabel) {
      this.app.stage.removeChild(this.placeholderLabel);
      this.placeholderLabel = null;
    }
  }

  destroy(): void {
    this.clearAll();
    this.app.destroy(true);
  }
}

// Factory: initialise l'Application PixiJS et retourne le renderer
export async function createPCBRenderer(canvas: HTMLCanvasElement): Promise<PCBRenderer> {
  const app = new Application();
  await app.init({
    canvas,
    background: 0x0d0d0d,
    resizeTo: canvas.parentElement ?? canvas,
    antialias: true,
    resolution: window.devicePixelRatio ?? 1,
    autoDensity: true,
  });
  return new PCBRenderer(app);
}

// Ce fichier est importé uniquement côté client (via dynamic import + ssr:false)
// PixiJS v8 — API async Application, Graphics chainable
import { Application, Container, Graphics, Text, TextStyle } from 'pixi.js';
import { mmToPx, LAYER_COLORS } from './layers';
import type { PCBState, DRCViolation } from '@layrix/types';

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

const BOARD_BG   = 0x0d1a00;
const COMP_LINE  = 0x888888;
const DRC_ERROR  = 0xff2222;
const DRC_WARN   = 0xffaa00;

// Map tscircuit logical layer names → KiCad layer names used in LAYER_COLORS
function toKicadLayer(layer: string | undefined, forSilk = false): string {
  if (!layer) return forSilk ? 'F.SilkS' : 'F.Cu';
  if (layer === 'top')    return forSilk ? 'F.SilkS' : 'F.Cu';
  if (layer === 'bottom') return forSilk ? 'B.SilkS' : 'B.Cu';
  return layer; // already a KiCad name (e.g. 'F.Cu', 'Edge.Cuts')
}

export class PCBRenderer {
  private app: Application;
  private boardLayer    = new Container();
  private componentLayer = new Container();
  private drcLayer      = new Container();
  private labelLayer    = new Container();

  constructor(app: Application) {
    this.app = app;
    app.stage.addChild(this.boardLayer);
    app.stage.addChild(this.componentLayer);
    app.stage.addChild(this.drcLayer);
    app.stage.addChild(this.labelLayer);
  }

  render(state: PCBState | null, layerVisibility: Record<string, boolean> = {}): void {
    this.clearAll();

    // Prefer circuit-json rendering when available
    if (Array.isArray(state?.circuit_json) && state.circuit_json.length > 0) {
      this.renderFromCircuitJson(state.circuit_json, layerVisibility);
      if (state.drcViolations?.length) {
        const boardW = mmToPx(state.board_width_mm ?? 50);
        const boardH = mmToPx(state.board_height_mm ?? 50);
        const ox = (this.app.screen.width  - boardW) / 2;
        const oy = (this.app.screen.height - boardH) / 2;
        for (const v of state.drcViolations) {
          this.renderDRCMarker(v, ox, oy);
        }
      }
      return;
    }

    // Fallback: placement-based rendering
    if (!state?.placement) {
      this.renderPlaceholder();
      return;
    }

    const placement = state.placement as PlacementData;
    const boardW = mmToPx(placement.board_width_mm ?? 50);
    const boardH = mmToPx(placement.board_height_mm ?? 50);
    const offsetX = (this.app.screen.width  - boardW) / 2;
    const offsetY = (this.app.screen.height - boardH) / 2;

    this.renderBoard(boardW, boardH, offsetX, offsetY);

    if (placement.placements) {
      for (const comp of placement.placements) {
        this.renderComponent(comp, offsetX, offsetY);
      }
    }

    if (state.drcViolations?.length) {
      for (const v of state.drcViolations) {
        this.renderDRCMarker(v, offsetX, offsetY);
      }
    }
  }

  // --- Circuit-json rendering --------------------------------------------

  private renderFromCircuitJson(
    elements: unknown[],
    layerVisibility: Record<string, boolean>
  ): void {
    type AnyEl = { type: string; layer?: string; [k: string]: unknown };

    // Locate board dimensions
    const boardEl = elements.find(
      (e) => (e as AnyEl).type === 'pcb_board'
    ) as { width: number; height: number } | undefined;

    const boardW   = boardEl?.width  ?? 50;
    const boardH   = boardEl?.height ?? 50;
    const boardWpx = mmToPx(boardW);
    const boardHpx = mmToPx(boardH);
    const ox = (this.app.screen.width  - boardWpx) / 2;
    const oy = (this.app.screen.height - boardHpx) / 2;

    // Board background fill
    const bg = new Graphics();
    bg.rect(ox, oy, boardWpx, boardHpx).fill({ color: BOARD_BG });
    this.boardLayer.addChild(bg);

    for (const raw of elements) {
      const el = raw as AnyEl;

      switch (el.type) {

        case 'pcb_board': {
          if (layerVisibility['Edge.Cuts'] === false) break;
          const g = new Graphics();
          g.rect(ox, oy, boardWpx, boardHpx)
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
          g.rect(ox + mmToPx(pad.x) - pw / 2, oy + mmToPx(pad.y) - ph / 2, pw, ph)
            .fill({ color: LAYER_COLORS[kicad] ?? 0xff5555, alpha: 0.85 });
          this.componentLayer.addChild(g);
          break;
        }

        case 'pcb_component': {
          const kicad = toKicadLayer(el.layer);
          if (layerVisibility[kicad] === false) break;
          const comp = el as unknown as { center: { x: number; y: number } };
          const cx = ox + mmToPx(comp.center.x);
          const cy = oy + mmToPx(comp.center.y);
          const r  = mmToPx(0.35);
          const g = new Graphics();
          g.moveTo(cx - r, cy).lineTo(cx + r, cy);
          g.moveTo(cx, cy - r).lineTo(cx, cy + r);
          g.stroke({ color: LAYER_COLORS[kicad] ?? 0xff5555, width: 1 });
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
          g.moveTo(ox + mmToPx(first.x), oy + mmToPx(first.y));
          for (const pt of rest) {
            g.lineTo(ox + mmToPx(pt.x), oy + mmToPx(pt.y));
          }
          g.stroke({ color: LAYER_COLORS[kicad] ?? 0xffffff, width: 0.75 });
          this.componentLayer.addChild(g);
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
          g.moveTo(ox + mmToPx(first.x), oy + mmToPx(first.y));
          for (const pt of rest) {
            g.lineTo(ox + mmToPx(pt.x), oy + mmToPx(pt.y));
          }
          g.stroke({ color: LAYER_COLORS[kicad] ?? 0xff5555, width: traceW });
          this.componentLayer.addChild(g);
          break;
        }

        default:
          break;
      }
    }
  }

  // --- Placement-based rendering (fallback) ------------------------------

  private renderBoard(w: number, h: number, ox: number, oy: number): void {
    const g = new Graphics();
    g.rect(ox, oy, w, h)
      .fill({ color: BOARD_BG })
      .stroke({ color: LAYER_COLORS['Edge.Cuts'] ?? 0xffff00, width: 1.5 });
    this.boardLayer.addChild(g);
  }

  private renderComponent(comp: PlacementItem, ox: number, oy: number): void {
    const cx = ox + mmToPx(comp.x_mm);
    const cy = oy + mmToPx(comp.y_mm);
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

  private renderDRCMarker(v: DRCViolation, ox: number, oy: number): void {
    const cx = ox + mmToPx(v.x_mm);
    const cy = oy + mmToPx(v.y_mm);
    const color = v.severity === 'error' ? DRC_ERROR : DRC_WARN;
    const r = mmToPx(1);

    const g = new Graphics();
    g.circle(cx, cy, r).stroke({ color, width: 2 });
    g.moveTo(cx - r * 0.7, cy).lineTo(cx + r * 0.7, cy);
    g.moveTo(cx, cy - r * 0.7).lineTo(cx, cy + r * 0.7);
    g.stroke({ color, width: 1.5 });

    this.drcLayer.addChild(g);
  }

  private renderPlaceholder(): void {
    const cx = this.app.screen.width  / 2;
    const cy = this.app.screen.height / 2;
    const style = new TextStyle({ fontSize: 12, fill: 0x444444, fontFamily: 'monospace' });
    const label = new Text({ text: 'Waiting for PCB data…', style });
    label.x = cx - label.width  / 2;
    label.y = cy - label.height / 2;
    this.boardLayer.addChild(label);
  }

  private clearAll(): void {
    this.boardLayer.removeChildren();
    this.componentLayer.removeChildren();
    this.drcLayer.removeChildren();
    this.labelLayer.removeChildren();
  }

  destroy(): void {
    this.clearAll();
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

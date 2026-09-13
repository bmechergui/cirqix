/**
 * Vues de rendu d'un board — partagées entre la route `GET /api/projects/[id]/render`
 * (qui les traduit en options `kicad-cli pcb render`) et le viewer (qui les propose).
 *
 * Deux familles :
 *  - `png` : projection orthogonale, une face — ce que l'on met dans un rapport ;
 *  - `3d`  : perspective + rotation — la vue 3D de KiCad, rendue par son lanceur
 *    de rayons. `iso` reprend l'isométrique documentée par KiCad (`-45,0,45`).
 */

export type RenderView = 'top' | 'bottom' | 'iso' | 'iso-back' | 'front' | 'back' | 'left' | 'right';
export type RenderQuality = 'basic' | 'high';
export type RenderFamily = 'png' | '3d';

export interface RenderPreset {
  readonly label: string;
  readonly family: RenderFamily;
  readonly side: 'top' | 'bottom' | 'left' | 'right' | 'front' | 'back';
  readonly rotate: string | null;
  readonly perspective: boolean;
}

export const RENDER_PRESETS: Readonly<Record<RenderView, RenderPreset>> = {
  top:        { label: 'Top',       family: 'png', side: 'top',    rotate: null,        perspective: false },
  bottom:     { label: 'Bottom',    family: 'png', side: 'bottom', rotate: null,        perspective: false },
  iso:        { label: 'Iso',       family: '3d',  side: 'top',    rotate: '-45,0,45',  perspective: true },
  'iso-back': { label: 'Iso back',  family: '3d',  side: 'top',    rotate: '-45,0,225', perspective: true },
  front:      { label: 'Front',     family: '3d',  side: 'front',  rotate: null,        perspective: true },
  back:       { label: 'Back',      family: '3d',  side: 'back',   rotate: null,        perspective: true },
  left:       { label: 'Left',      family: '3d',  side: 'left',   rotate: null,        perspective: true },
  right:      { label: 'Right',     family: '3d',  side: 'right',  rotate: null,        perspective: true },
};

export const RENDER_VIEWS = Object.keys(RENDER_PRESETS) as readonly RenderView[];

export function viewsOfFamily(family: RenderFamily): readonly RenderView[] {
  return RENDER_VIEWS.filter((v) => RENDER_PRESETS[v].family === family);
}

export interface RenderParams {
  readonly view: RenderView;
  readonly quality: RenderQuality;
  /** Rotation supplémentaire autour de l'axe vertical, en degrés (vue 3D seulement). */
  readonly yaw: number;
  readonly zoom: number;
  readonly width: number;
  readonly height: number;
}

export const RENDER_DEFAULTS: RenderParams = {
  view: 'top', quality: 'basic', yaw: 0, zoom: 1, width: 1600, height: 900,
};

const LIMITS = {
  yaw: { min: -180, max: 180 },
  zoom: { min: 0.25, max: 4 },
  width: { min: 64, max: 4096 },
  height: { min: 64, max: 4096 },
} as const;

function isView(v: string): v is RenderView {
  return Object.prototype.hasOwnProperty.call(RENDER_PRESETS, v);
}

function nombreBorne(raw: string | null, def: number, lim: { min: number; max: number }): number | null {
  if (raw === null || raw === '') return def;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < lim.min || n > lim.max) return null;
  return n;
}

export type ParsedRender = { ok: true; params: RenderParams } | { ok: false; error: string };

/** Lit et borne les paramètres de requête ; refuse franchement ce qui ne se lit pas. */
export function parseRenderQuery(q: URLSearchParams): ParsedRender {
  const view = q.get('view') ?? RENDER_DEFAULTS.view;
  if (!isView(view)) return { ok: false, error: `unknown view "${view}" — expected one of ${RENDER_VIEWS.join(', ')}` };
  const quality = q.get('quality') ?? RENDER_DEFAULTS.quality;
  if (quality !== 'basic' && quality !== 'high') return { ok: false, error: 'quality must be basic or high' };
  const yaw = nombreBorne(q.get('yaw'), RENDER_DEFAULTS.yaw, LIMITS.yaw);
  const zoom = nombreBorne(q.get('zoom'), RENDER_DEFAULTS.zoom, LIMITS.zoom);
  const width = nombreBorne(q.get('w'), RENDER_DEFAULTS.width, LIMITS.width);
  const height = nombreBorne(q.get('h'), RENDER_DEFAULTS.height, LIMITS.height);
  if (yaw === null) return { ok: false, error: 'yaw must be a number between -180 and 180' };
  if (zoom === null) return { ok: false, error: 'zoom must be a number between 0.25 and 4' };
  if (width === null || height === null) return { ok: false, error: 'w and h must be integers between 64 and 4096' };
  return { ok: true, params: { view, quality, yaw, zoom, width: Math.round(width), height: Math.round(height) } };
}

/** Le corps exact envoyé à `POST /render/auto` du service KiCad (sans le board). */
export function serviceRenderOptions(p: RenderParams): {
  side: RenderPreset['side']; rotate: string | null; perspective: boolean;
  zoom: number; quality: RenderQuality; width: number; height: number;
} {
  const preset = RENDER_PRESETS[p.view];
  const rotate = preset.family === '3d' && p.yaw !== 0
    ? appliquerYaw(preset.rotate ?? '0,0,0', p.yaw)
    : preset.rotate;
  return {
    side: preset.side, rotate, perspective: preset.perspective,
    zoom: p.zoom, quality: p.quality, width: p.width, height: p.height,
  };
}

/** Ajoute `yaw` degrés à la composante Z d'une rotation 'X,Y,Z' de kicad-cli. */
export function appliquerYaw(rotate: string, yaw: number): string {
  const [x = '0', y = '0', z = '0'] = rotate.split(',');
  const zNum = ((Number(z) + yaw) % 360 + 360) % 360;
  return `${x},${y},${zNum}`;
}

/** La chaîne de requête que le viewer met dans `src` — l'inverse de `parseRenderQuery`. */
export function renderQueryString(p: Partial<RenderParams>): string {
  const q = new URLSearchParams();
  const full = { ...RENDER_DEFAULTS, ...p };
  q.set('view', full.view);
  q.set('quality', full.quality);
  if (full.yaw !== 0) q.set('yaw', String(full.yaw));
  if (full.zoom !== 1) q.set('zoom', String(full.zoom));
  if (full.width !== RENDER_DEFAULTS.width) q.set('w', String(full.width));
  if (full.height !== RENDER_DEFAULTS.height) q.set('h', String(full.height));
  return q.toString();
}

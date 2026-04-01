// Couches PCB — couleurs et ordre d'affichage

export const LAYER_COLORS: Record<string, number> = {
  'Edge.Cuts': 0xffff00,
  'F.Cu':      0xff5555,
  'B.Cu':      0x5555ff,
  'F.SilkS':   0xffffff,
  'B.SilkS':   0x888888,
  'F.Mask':    0xcc00cc,
  'B.Mask':    0x008800,
  'F.Fab':     0xaaaaaa,
  'B.Fab':     0x555555,
};

// Ordre d'affichage (bas → haut)
export const LAYER_ORDER: string[] = [
  'B.Cu', 'B.Mask', 'B.SilkS', 'B.Fab',
  'F.Cu', 'F.Mask', 'F.SilkS', 'F.Fab',
  'Edge.Cuts',
];

// Visibilité par défaut
export const DEFAULT_LAYER_VISIBILITY: Record<string, boolean> = {
  'Edge.Cuts': true,
  'F.Cu':      true,
  'B.Cu':      true,
  'F.SilkS':   true,
  'B.SilkS':   false,
  'F.Mask':    false,
  'B.Mask':    false,
  'F.Fab':     true,
  'B.Fab':     false,
};

// 1mm = 3.7795px à 96 DPI (standard CSS)
export const PX_PER_MM = 3.7795;

export function mmToPx(mm: number): number {
  return mm * PX_PER_MM;
}

// Couleurs en hex string CSS pour la légende
export function colorToHex(color: number): string {
  return `#${color.toString(16).padStart(6, '0')}`;
}

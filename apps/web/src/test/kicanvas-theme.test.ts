import { describe, it, expect } from 'vitest';
import { ensureKiCanvasTheme, KICANVAS_THEME_PREF_KEY } from '@/widgets/viewer/lib/kicanvas-loader';

/**
 * En `controls="full"`, KiCanvas ignore l'attribut `theme` et lit sa
 * préférence `kc:prefs:theme` (`{"val": …}`, défaut witchhazel = carte rose).
 * Ce que ces tests discriminent : la préférence est posée au format exact de
 * KiCanvas quand elle manque, jamais écrasée quand l'utilisateur a choisi.
 */
function memoire(initial: Record<string, string> = {}) {
  const m = new Map(Object.entries(initial));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); }, m };
}

describe('ensureKiCanvasTheme', () => {
  it('pose le thème KiCad au format de KiCanvas quand rien n’est enregistré', () => {
    const s = memoire();
    ensureKiCanvasTheme(s);
    expect(JSON.parse(s.m.get(KICANVAS_THEME_PREF_KEY)!)).toEqual({ val: 'kicad' });
  });
  it('respecte un choix déjà fait dans les réglages de KiCanvas', () => {
    const s = memoire({ [KICANVAS_THEME_PREF_KEY]: JSON.stringify({ val: 'witchhazel' }) });
    ensureKiCanvasTheme(s);
    expect(JSON.parse(s.m.get(KICANVAS_THEME_PREF_KEY)!)).toEqual({ val: 'witchhazel' });
  });
  it('ne lève pas sans stockage', () => {
    expect(() => ensureKiCanvasTheme(null)).not.toThrow();
    expect(() => ensureKiCanvasTheme({ getItem: () => { throw new Error('bloqué'); }, setItem: () => undefined })).not.toThrow();
  });
});

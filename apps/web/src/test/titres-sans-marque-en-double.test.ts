import { describe, it, expect, vi } from 'vitest';

// `layout.tsx` charge ses polices par `next/font/google`, qui ne tourne pas sous
// jsdom : on les remplace, le sujet est le titre, pas la typographie.
vi.mock('next/font/google', () => {
  const police = () => ({ variable: '', className: '' });
  return { Geist: police, Geist_Mono: police, Syne: police };
});

/**
 * Le gabarit racine (`app/layout.tsx`) ajoute déjà « | Cirqix » à chaque titre.
 * Une page qui écrit « … — Cirqix » affichait donc « Sign in — Cirqix | Cirqix »
 * dans l'onglet — relevé au parcours local du 2026-09-19.
 */
import { metadata as racine } from '@/app/layout';
import { metadata as connexion } from '@/app/(auth)/login/page';
import { metadata as inscription } from '@/app/(auth)/signup/page';

describe('titres des pages', () => {
  it('le gabarit racine porte la marque', () => {
    expect(racine.title).toMatchObject({ template: '%s | Cirqix' });
  });

  for (const [nom, meta] of [['connexion', connexion], ['inscription', inscription]] as const) {
    it(`${nom} ne répète pas la marque que le gabarit ajoute`, () => {
      expect(String(meta.title)).not.toMatch(/Cirqix/);
    });
  }
});

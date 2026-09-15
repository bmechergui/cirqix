import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Le titre du Hero doit tenir dans un écran de 375 px.
 *
 * Mesuré le 2026-09-15 dans Playwright à 375 px, marges `px-6` (24 px de chaque
 * côté, donc 327 px utiles) :
 *
 *   text-[2rem]    32 px    « manufacturable » coupé, « autonomously » fin à 383 px
 *   text-[1.8rem]  28,8 px  « manufacturable » fin à 392 px — coupé encore
 *
 * La police d'affichage est large : « manufacturable » mesure ~12,8 fois la
 * taille de police, soit 25,6 px au plus pour 327 px. La règle Responsive de
 * CLAUDE.md (1,8 rem) ne suffit donc pas avec cette police ; 1,5 rem (24 px,
 * ~307 px) tient avec de la marge. Le `overflow-hidden` du Hero coupait le texte
 * sans barre de défilement, donc sans rien qui le signale.
 *
 * jsdom ne met rien en page : cette garde verrouille la taille MOBILE du h1,
 * la mesure réelle reste à Playwright.
 */
const TAILLE_MOBILE_MAX_REM = 1.5;

const SOURCE = readFileSync(
  path.resolve(__dirname, '../features/marketing/ui/Hero.tsx'),
  'utf8',
);

function tailleMobileDuTitre(): number {
  const classes = SOURCE.match(/<h1\s+className="([^"]+)"/)?.[1];
  if (classes === undefined) throw new Error('h1 du Hero introuvable');
  const base = classes.split(/\s+/).filter((c) => /^text-\[[\d.]+rem\]$/.test(c));
  if (base.length !== 1) throw new Error(`taille mobile du h1 ambiguë : ${base.join(' ')}`);
  return parseFloat(base[0]!.slice('text-['.length));
}

describe('Hero — titre sur mobile', () => {
  it('ne dépasse pas la taille qui tient dans 375 px', () => {
    expect(tailleMobileDuTitre()).toBeLessThanOrEqual(TAILLE_MOBILE_MAX_REM);
  });

  it('garde les tailles des écrans plus larges', () => {
    expect(SOURCE).toMatch(/<h1\s+className="[^"]*sm:text-\[2\.6rem\][^"]*md:text-\[3rem\]/);
  });
});

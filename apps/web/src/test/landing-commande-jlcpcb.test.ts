import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * La page publique ne promet pas une commande JLCPCB que le produit n'envoie pas.
 *
 * Vérifié le 2026-09-05 et inscrit dans CLAUDE.md : `POST /api/jlcpcb/order`
 * PRÉPARE un dossier et répond « No order was sent to JLCPCB » — la dernière
 * étape est manuelle. La landing disait pourtant « orders from JLCPCB — fully
 * autonomously » (Hero et description des métadonnées) et « order directly from
 * JLCPCB with one click » (étapes). Relevé le 2026-09-15.
 */
const lire = (relatif: string): string => readFileSync(path.resolve(__dirname, relatif), 'utf8');

const PAGES = {
  hero: lire('../features/marketing/ui/Hero.tsx'),
  metadonnees: lire('../app/layout.tsx'),
  contenu: lire('../shared/lib/marketing-content.ts'),
};

const PROMESSES = [/orders? (directly )?from JLCPCB/i, /one[- ]click/i];

describe('landing — commande JLCPCB', () => {
  for (const [nom, texte] of Object.entries(PAGES)) {
    it(`${nom} ne promet ni commande automatique ni commande en un clic`, () => {
      for (const promesse of PROMESSES) expect(texte).not.toMatch(promesse);
    });
  }

  it("le Hero et la description disent que l'envoi reste a l'utilisateur", () => {
    expect(PAGES.hero).toMatch(/submit/i);
    expect(PAGES.metadonnees).toMatch(/submit/i);
  });
});

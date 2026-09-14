import { describe, it, expect, beforeEach } from 'vitest';

/**
 * L'aide Cirqix remplace celle de KiCanvas — demandé le 2026-09-14 : le
 * panneau « Help » annonçait « You're using KiCanvas… very much in alpha…
 * file an issue on GitHub », avec des liens vers son dépôt et ses dons.
 *
 * Ce que ces tests discriminent : le panneau est bien RÉÉCRIT (et le compte le
 * dit), plus une mention de KiCanvas ni de lien sortant n'y subsiste, le titre
 * devient le nôtre, l'opération est idempotente, et un panneau pas encore
 * rendu par Lit n'est pas marqué comme traité — sinon on ne repasserait jamais.
 */

import {
  remplacerAideParCirqix,
  construireAideCirqix,
  AIDE_CIRQIX,
  TITRE_AIDE,
} from '@/widgets/viewer/lib/kicanvas-aide';

function avecOmbre(tag: string): HTMLElement {
  const el = document.createElement(tag);
  el.attachShadow({ mode: 'open' });
  return el;
}

/** L'arbre réel : embed → app → kc-help-panel{ kc-ui-panel-title, kc-ui-panel-body }. */
function arbreAvecAide(rendu = true): { embed: HTMLElement; panneau: HTMLElement } {
  const embed = avecOmbre('kicanvas-embed-test');
  const app = avecOmbre('kc-board-app-test');
  const panneau = avecOmbre('kc-help-panel');
  if (rendu) {
    const titre = document.createElement('kc-ui-panel-title');
    titre.setAttribute('title', 'Help');
    const corps = document.createElement('kc-ui-panel-body');
    const p = document.createElement('p');
    p.textContent = "You're using KiCanvas, an interactive, browser-based viewer.";
    const lien = document.createElement('a');
    lien.setAttribute('href', 'https://github.com/theacodes/kicanvas');
    lien.textContent = 'file an issue on GitHub';
    corps.append(p, lien);
    panneau.shadowRoot!.append(titre, corps);
  }
  app.shadowRoot!.appendChild(panneau);
  embed.shadowRoot!.appendChild(app);
  return { embed, panneau };
}

describe('construireAideCirqix', () => {
  it('rend une section par thème, et une ligne par commande', () => {
    const f = construireAideCirqix(document);
    const hote = document.createElement('div');
    hote.appendChild(f);
    expect(hote.querySelectorAll('ul').length).toBe(AIDE_CIRQIX.length);
    const lignes = AIDE_CIRQIX.reduce((n, s) => n + s.lignes.length, 0);
    expect(hote.querySelectorAll('li').length).toBe(lignes);
  });

  it('ne parle jamais de KiCanvas et ne sort nulle part', () => {
    const hote = document.createElement('div');
    hote.appendChild(construireAideCirqix(document));
    expect(hote.textContent?.toLowerCase()).not.toContain('kicanvas');
    expect(hote.textContent?.toLowerCase()).not.toContain('alpha');
    expect(hote.querySelectorAll('a').length).toBe(0);
  });

  it('couvre le routage ET le schéma — les quatre vues sont nommées', () => {
    const texte = AIDE_CIRQIX.flatMap((s) => s.lignes).map((l) => l.terme).join(' ');
    for (const vue of ['Native', 'Cirqix', 'PNG', '3D']) expect(texte).toContain(vue);
  });

  it('est en ANGLAIS, comme le produit — aucun accent, aucun mot français', () => {
    const tout = [TITRE_AIDE, ...AIDE_CIRQIX.flatMap((s) => [s.titre, ...s.lignes.flatMap((l) => [l.terme, l.texte])])].join(' ');
    expect(tout).not.toMatch(/[àâäéèêëîïôöùûüç]/i);
    expect(tout.toLowerCase()).not.toMatch(/\b(les|des|une|avec|sans|dans|pour|carte|couches|glisser)\b/);
  });
});

describe('remplacerAideParCirqix', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('réécrit le panneau : plus un mot de KiCanvas, plus un lien', () => {
    const { embed, panneau } = arbreAvecAide();
    expect(remplacerAideParCirqix(embed)).toBe(1);
    const corps = panneau.shadowRoot!.querySelector('kc-ui-panel-body')!;
    expect(corps.textContent?.toLowerCase()).not.toContain('kicanvas');
    expect(corps.querySelectorAll('a').length).toBe(0);
    expect(corps.querySelectorAll('li').length).toBeGreaterThan(5);
  });

  it('pose NOTRE titre, quel que soit celui que KiCanvas avait mis', () => {
    // ⚠️ Notre titre vaut « Help », comme celui de KiCanvas : vérifier
    // `title === TITRE_AIDE` sur son titre d'origine passerait sans notre code.
    // On part donc d'un titre différent — seul notre passage peut le changer.
    const { embed, panneau } = arbreAvecAide();
    panneau.shadowRoot!.querySelector('kc-ui-panel-title')!.setAttribute('title', 'KiCanvas info');
    remplacerAideParCirqix(embed);
    expect(panneau.shadowRoot!.querySelector('kc-ui-panel-title')!.getAttribute('title')).toBe(TITRE_AIDE);
  });

  it('est idempotente', () => {
    const { embed } = arbreAvecAide();
    remplacerAideParCirqix(embed);
    expect(remplacerAideParCirqix(embed)).toBe(0);
  });

  it('un panneau pas encore rendu n’est pas marqué traité — on doit pouvoir repasser', () => {
    const { embed, panneau } = arbreAvecAide(false);
    expect(remplacerAideParCirqix(embed)).toBe(0);
    // Lit rend le panneau après coup : le passage suivant doit le réécrire.
    const titre = document.createElement('kc-ui-panel-title');
    titre.setAttribute('title', 'Help');
    const corps = document.createElement('kc-ui-panel-body');
    corps.textContent = "You're using KiCanvas";
    panneau.shadowRoot!.append(titre, corps);
    expect(remplacerAideParCirqix(embed)).toBe(1);
  });

  it('ne lève pas sans hôte ni sans panneau d’aide', () => {
    expect(remplacerAideParCirqix(null)).toBe(0);
    expect(remplacerAideParCirqix(avecOmbre('kicanvas-embed-test'))).toBe(0);
  });
});

import { describe, it, expect, beforeEach } from 'vitest';

/**
 * L'habillage Cirqix de KiCanvas — demandé le 2026-09-14 : « je veux qu'on ne
 * puisse pas dire que c'est KiCanvas », sans rien lui retirer.
 *
 * Ce que ces tests discriminent : la feuille est posée dans TOUS les shadow
 * roots imbriqués (KiCanvas en a au moins deux : `kicanvas-embed` →
 * `kc-board-app` → panneaux) ; elle est idempotente ; elle redéclare bien les
 * variables que KiCanvas lit ; et les dégradés violets sont neutralisés — sans
 * quoi le panneau resterait celui de KiCanvas.
 */

import { appliquerSkinCirqix, SKIN_CIRQIX_CSS, MARQUE_SKIN } from '@/widgets/viewer/lib/kicanvas-skin';

function elementAvecOmbre(tag: string): HTMLElement {
  const el = document.createElement(tag);
  el.attachShadow({ mode: 'open' });
  return el;
}

/** L'imbrication réelle : embed → board-app → panneau. */
function arbreKiCanvas(): HTMLElement {
  const embed = elementAvecOmbre('kicanvas-embed-test');
  const app = elementAvecOmbre('kc-board-app-test');
  const panneau = elementAvecOmbre('kc-board-objects-panel-test');
  app.shadowRoot!.appendChild(panneau);
  embed.shadowRoot!.appendChild(app);
  return embed;
}

function feuilles(el: HTMLElement): number {
  let n = 0;
  const visiter = (e: Element) => {
    const s = (e as HTMLElement).shadowRoot;
    if (!s) return;
    n += s.querySelectorAll(`style[data-${MARQUE_SKIN}]`).length;
    for (const c of Array.from(s.querySelectorAll('*'))) visiter(c);
  };
  visiter(el);
  return n;
}

describe('SKIN_CIRQIX_CSS', () => {
  it('redéclare les variables que KiCanvas lit pour ses panneaux et sa barre d’icônes', () => {
    for (const v of ['--panel-bg', '--panel-title-bg', '--activity-bar-bg', '--activity-bar-active-fg',
                     '--list-item-hover-bg', '--input-bg', '--scrollbar-fg', '--tooltip-bg']) {
      expect(SKIN_CIRQIX_CSS).toContain(`${v}:`);
    }
  });

  it('neutralise les dégradés violets — sinon le panneau reste celui de KiCanvas', () => {
    for (const g of ['--gradient-purple-blue-dark', '--gradient-purple-green-light', '--gradient-cyan-blue-light']) {
      expect(SKIN_CIRQIX_CSS).toContain(`${g}:`);
    }
    expect(SKIN_CIRQIX_CSS).not.toMatch(/#ae81ff|linear-gradient/);
  });

  it('chaque déclaration est en !important — KiCanvas les pose sur son propre :host', () => {
    const declarations = SKIN_CIRQIX_CSS.match(/--[a-z0-9-]+:[^;]+;/g) ?? [];
    expect(declarations.length).toBeGreaterThan(30);
    expect(declarations.every((d) => d.includes('!important'))).toBe(true);
  });
});

describe('appliquerSkinCirqix', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('pose la feuille dans chaque shadow root imbriqué', () => {
    const embed = arbreKiCanvas();
    expect(appliquerSkinCirqix(embed)).toBe(3);
    expect(feuilles(embed)).toBe(3);
  });

  it('est idempotente : un second appel n’empile rien', () => {
    const embed = arbreKiCanvas();
    appliquerSkinCirqix(embed);
    expect(appliquerSkinCirqix(embed)).toBe(0);
    expect(feuilles(embed)).toBe(3);
  });

  it('habille les panneaux apparus après coup', () => {
    const embed = arbreKiCanvas();
    appliquerSkinCirqix(embed);
    const tardif = elementAvecOmbre('kc-board-nets-panel-test');
    (embed.shadowRoot!.firstElementChild as HTMLElement).shadowRoot!.appendChild(tardif);
    expect(appliquerSkinCirqix(embed)).toBe(1);
    expect(feuilles(embed)).toBe(4);
  });

  it('ne lève pas sans hôte ni sans shadow root', () => {
    expect(appliquerSkinCirqix(null)).toBe(0);
    expect(appliquerSkinCirqix(document.createElement('div'))).toBe(0);
  });
});

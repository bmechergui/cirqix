/**
 * L'aide Cirqix, à la place de celle de KiCanvas.
 *
 * Demandé le 2026-09-14, captures à l'appui : le panneau « Help » annonçait
 * « You're using KiCanvas… very much in alpha… file an issue on GitHub »,
 * avec des liens vers son dépôt et ses dons. Ce n'est ni notre produit, ni
 * une aide utile à quelqu'un qui regarde son schéma ou son routage.
 *
 * On remplace le CONTENU du panneau — titre compris — par une aide courte :
 * les commandes, ce que font les panneaux, ce que valent les quatre vues.
 * KiCanvas garde tout le reste ; seul ce texte change.
 *
 * ⚠️ Le contenu est construit en DOM (`createElement` / `textContent`), jamais
 * par `innerHTML` : rien ici ne vient de l'utilisateur, et on n'ouvre pas une
 * porte qui n'a pas besoin de l'être.
 */

/** Le viewer parle anglais, comme le produit (demandé le 2026-09-14). */
export const TITRE_AIDE = 'Help';

export interface LigneAide {
  readonly terme: string;
  readonly texte: string;
}

export interface SectionAide {
  readonly titre: string;
  readonly lignes: readonly LigneAide[];
}

export const AIDE_CIRQIX: readonly SectionAide[] = [
  {
    titre: 'Navigate',
    lignes: [
      { terme: 'Drag', texte: 'pans the view (hand mode in the bottom toolbar).' },
      { terme: 'Ctrl + wheel', texte: 'zooms; the wheel alone scrolls the page.' },
      { terme: 'Fit', texte: 'the ⛶ button recenters the board or the schematic.' },
    ],
  },
  {
    titre: 'Inspect',
    lignes: [
      { terme: 'Click', texte: 'selects a footprint, a track or a via; its name shows in the top right.' },
      { terme: 'Layers', texte: 'show or hide F.Cu, B.Cu, silkscreen, solder mask, board outline.' },
      { terme: 'Nets', texte: 'lists the connections of the board and highlights them.' },
      { terme: 'Footprints', texte: 'lists the components, by side, with their value.' },
    ],
  },
  {
    titre: 'The four views',
    lignes: [
      { terme: 'Native', texte: 'the schematic and the routing exactly as KiCad writes them — this view.' },
      { terme: 'Cirqix', texte: 'our simplified rendering, easier to read on a small board.' },
      { terme: 'PNG', texte: 'an image rendered by KiCad, top and bottom.' },
      { terme: '3D', texte: 'the board in volume, drag to rotate, with or without component bodies.' },
    ],
  },
];

const MARQUE_AIDE = 'cirqix-aide';

/** Le contenu du panneau, en DOM. `doc` est injectable pour les tests. */
export function construireAideCirqix(doc: Document = document): DocumentFragment {
  const fragment = doc.createDocumentFragment();
  for (const section of AIDE_CIRQIX) {
    const titre = doc.createElement('p');
    const fort = doc.createElement('strong');
    fort.textContent = section.titre;
    titre.appendChild(fort);
    fragment.appendChild(titre);

    const liste = doc.createElement('ul');
    for (const ligne of section.lignes) {
      const item = doc.createElement('li');
      const terme = doc.createElement('strong');
      terme.textContent = ligne.terme;
      item.appendChild(terme);
      item.appendChild(doc.createTextNode(` — ${ligne.texte}`));
      liste.appendChild(item);
    }
    fragment.appendChild(liste);
  }
  return fragment;
}

/**
 * Remplace l'aide de KiCanvas par la nôtre, dans tous les `kc-help-panel`
 * sous `hote` (ils vivent dans des shadow roots imbriqués).
 *
 * Idempotente. Rend le nombre de panneaux RÉÉCRITS par cet appel — zéro quand
 * tout est déjà fait, ou quand le panneau n'est pas encore rendu. Sans ce
 * compte, un remplacement jamais appliqué serait indistinguable d'un
 * remplacement déjà en place.
 */
export function remplacerAideParCirqix(hote: Element | null | undefined): number {
  if (!hote) return 0;
  const doc = hote.ownerDocument ?? document;
  let reecrits = 0;
  const vus = new Set<ShadowRoot>();

  const traiter = (panneau: Element): void => {
    const shadow = (panneau as HTMLElement).shadowRoot;
    if (!shadow || shadow.querySelector(`[data-${MARQUE_AIDE}]`)) return;
    const corps = shadow.querySelector('kc-ui-panel-body');
    if (!corps) return; // pas encore rendu : on repassera
    corps.replaceChildren(construireAideCirqix(doc));
    corps.setAttribute(`data-${MARQUE_AIDE}`, '');
    shadow.querySelector('kc-ui-panel-title')?.setAttribute('title', TITRE_AIDE);
    reecrits += 1;
  };

  const visiter = (el: Element): void => {
    if (el.tagName.toLowerCase() === 'kc-help-panel') traiter(el);
    const shadow = (el as HTMLElement).shadowRoot;
    if (!shadow || vus.has(shadow)) return;
    vus.add(shadow);
    for (const enfant of Array.from(shadow.querySelectorAll('*'))) visiter(enfant);
  };

  visiter(hote);
  return reecrits;
}

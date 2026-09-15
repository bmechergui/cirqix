/**
 * L'habillage Cirqix de KiCanvas.
 *
 * KiCanvas garde toutes ses fonctions — couches, nets, empreintes, propriétés,
 * sélection — mais son apparence est la nôtre : demandé le 2026-09-14,
 * « je veux qu'on ne puisse pas dire que c'est KiCanvas ».
 *
 * Il expose l'intégralité de ses couleurs en variables CSS (`--panel-bg`,
 * `--activity-bar-bg`, `--list-item-hover-bg`…) déclarées sur le `:host` de ses
 * composants. On les redéclare avec la palette Cirqix, sans toucher à son code
 * ni au rendu du board : les violets et les dégradés bleu-vert disparaissent au
 * profit des noirs du dashboard et du bleu Cirqix.
 *
 * ⚠️ `!important` est nécessaire : KiCanvas déclare ces variables sur `:host`,
 * et une déclaration hôte l'emporte sur une valeur héritée du document.
 */

/** Palette du dashboard — les mêmes valeurs que le reste du viewer. */
const NOIR_FOND = '#060606';
const NOIR_PANNEAU = '#0a0a0a';
const NOIR_ELEVE = '#111111';
const BORDURE = '#1e1e1e';
const TEXTE = '#e8e8e8';
const TEXTE_DOUX = '#8a8a8a';
const TEXTE_FAIBLE = '#3d3d3d';
// Noir et blanc (2026-09-15), comme le reste du produit : l'accent est le blanc.
const PRIMAIRE = '#ffffff';
const PRIMAIRE_FOND = 'rgb(255 255 255 / 0.10)';
const PRIMAIRE_BORD = 'rgb(255 255 255 / 0.30)';

export const MARQUE_SKIN = 'cirqix-skin-kicanvas';

export const SKIN_CIRQIX_CSS = `
:host, :root {
  --bg: ${NOIR_FOND} !important;
  --fg: ${TEXTE} !important;

  /* Les dégradés violets de KiCanvas : neutralisés à la source. */
  --gradient-purple-blue-dark: ${NOIR_PANNEAU} !important;
  --gradient-purple-blue-medium: ${NOIR_ELEVE} !important;
  --gradient-purple-green-light: ${NOIR_ELEVE} !important;
  --gradient-purple-green-highlight: ${PRIMAIRE_FOND} !important;
  --gradient-purple-red: ${NOIR_ELEVE} !important;
  --gradient-purple-red-highlight: ${PRIMAIRE_FOND} !important;
  --gradient-cyan-blue-light: ${NOIR_ELEVE} !important;

  /* Barre d'icônes */
  --activity-bar-bg: ${NOIR_FOND} !important;
  --activity-bar-fg: ${TEXTE_FAIBLE} !important;
  --activity-bar-active-bg: ${PRIMAIRE_FOND} !important;
  --activity-bar-active-fg: ${PRIMAIRE} !important;

  /* Panneaux */
  --panel-bg: ${NOIR_PANNEAU} !important;
  --panel-fg: ${TEXTE} !important;
  --panel-border: 1px solid ${BORDURE} !important;
  --panel-title-bg: ${NOIR_ELEVE} !important;
  --panel-title-fg: ${TEXTE} !important;
  --panel-title-border: 1px solid ${BORDURE} !important;
  --panel-subtitle-bg: ${NOIR_FOND} !important;
  --panel-subtitle-fg: ${TEXTE_DOUX} !important;
  --panel-title-button-bg: transparent !important;
  --panel-title-button-fg: ${TEXTE_DOUX} !important;
  --panel-title-button-hover-bg: ${PRIMAIRE_FOND} !important;
  --panel-title-button-hover-fg: ${PRIMAIRE} !important;

  /* Listes (couches, nets, empreintes) */
  --list-item-bg: transparent !important;
  --list-item-fg: ${TEXTE} !important;
  --list-item-hover-bg: ${NOIR_ELEVE} !important;
  --list-item-hover-fg: ${TEXTE} !important;
  --list-item-active-bg: ${PRIMAIRE_FOND} !important;
  --list-item-active-fg: ${PRIMAIRE} !important;
  --list-item-disabled-bg: transparent !important;
  --list-item-disabled-fg: ${TEXTE_FAIBLE} !important;

  /* Champ de recherche */
  --input-bg: ${NOIR_ELEVE} !important;
  --input-fg: ${TEXTE} !important;
  --input-border: 1px solid ${BORDURE} !important;
  --input-placeholder: ${TEXTE_FAIBLE} !important;
  --input-accent: ${PRIMAIRE} !important;
  --input-focus-outline: 1px solid ${PRIMAIRE_BORD} !important;
  --input-range-bg: ${BORDURE} !important;
  --input-range-fg: ${PRIMAIRE} !important;
  --input-range-hover-bg: ${BORDURE} !important;

  /* Boutons */
  --button-bg: ${NOIR_ELEVE} !important;
  --button-fg: ${TEXTE} !important;
  --button-hover-bg: ${PRIMAIRE_FOND} !important;
  --button-hover-fg: ${PRIMAIRE} !important;
  --button-selected-bg: ${PRIMAIRE_FOND} !important;
  --button-selected-fg: ${PRIMAIRE} !important;
  --button-disabled-bg: transparent !important;
  --button-disabled-fg: ${TEXTE_FAIBLE} !important;
  --button-toolbar-bg: ${NOIR_ELEVE} !important;
  --button-toolbar-fg: ${TEXTE_DOUX} !important;
  --button-toolbar-hover-bg: ${PRIMAIRE_FOND} !important;
  --button-toolbar-hover-fg: ${PRIMAIRE} !important;
  --button-toolbar-alt-bg: ${NOIR_ELEVE} !important;
  --button-toolbar-alt-hover-bg: ${PRIMAIRE_FOND} !important;
  --button-toolbar-alt-hover-fg: ${PRIMAIRE} !important;
  --button-menu-bg: transparent !important;
  --button-menu-fg: ${TEXTE_DOUX} !important;
  --button-menu-hover-bg: transparent !important;
  --button-menu-hover-fg: ${PRIMAIRE} !important;
  --button-focus-outline: 1px solid ${PRIMAIRE_BORD} !important;

  /* Menus, info-bulles, poignée de redimensionnement, ascenseurs */
  --dropdown-bg: ${NOIR_ELEVE} !important;
  --dropdown-fg: ${TEXTE} !important;
  --dropdown-hover-bg: ${PRIMAIRE_FOND} !important;
  --dropdown-hover-fg: ${PRIMAIRE} !important;
  --dropdown-active-bg: ${PRIMAIRE_FOND} !important;
  --dropdown-active-fg: ${PRIMAIRE} !important;
  --tooltip-bg: ${NOIR_ELEVE} !important;
  --tooltip-fg: ${TEXTE} !important;
  --tooltip-border: 1px solid ${BORDURE} !important;
  --resizer-bg: ${BORDURE} !important;
  --resizer-active-bg: ${PRIMAIRE} !important;
  --scrollbar-bg: ${NOIR_PANNEAU} !important;
  --scrollbar-fg: ${BORDURE} !important;
  --scrollbar-hover-fg: ${TEXTE_FAIBLE} !important;
  --scrollbar-active-fg: ${PRIMAIRE} !important;
  --focus-overlay-bg: ${NOIR_FOND} !important;
  --focus-overlay-fg: ${TEXTE} !important;
}
`;

/**
 * Pose la feuille dans TOUS les shadow roots sous `hote` (KiCanvas en imbrique
 * plusieurs : `kicanvas-embed` → `kc-board-app` → panneaux). Idempotente : on
 * peut la rappeler à chaque mutation sans empiler les feuilles.
 *
 * Rend le nombre de feuilles POSÉES par cet appel — zéro quand tout est déjà
 * habillé. Sans ce compte, un habillage jamais appliqué serait indistinguable
 * d'un habillage déjà en place.
 */
export function appliquerSkinCirqix(hote: Element | null | undefined): number {
  if (!hote) return 0;
  let posees = 0;
  const vus = new Set<ShadowRoot>();
  const visiter = (el: Element): void => {
    const shadow = (el as HTMLElement).shadowRoot;
    if (!shadow || vus.has(shadow)) return;
    vus.add(shadow);
    if (!shadow.querySelector(`style[data-${MARQUE_SKIN}]`)) {
      const style = document.createElement('style');
      style.setAttribute(`data-${MARQUE_SKIN}`, '');
      style.textContent = SKIN_CIRQIX_CSS;
      shadow.appendChild(style);
      posees += 1;
    }
    for (const enfant of Array.from(shadow.querySelectorAll('*'))) visiter(enfant);
  };
  visiter(hote);
  return posees;
}

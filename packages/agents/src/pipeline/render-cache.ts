import { createHash } from 'node:crypto';

/**
 * Cache des rendus KiCad (`kicad-cli pcb render`), partagé entre :
 *  - la route web `GET /api/projects/[id]/render`, qui sert un rendu déjà
 *    déposé avant d'en demander un au service ;
 *  - le pipeline, qui PRÉ-REND les vues les plus demandées à la livraison
 *    (`prerendus.ts`), pour que l'ouverture du projet soit instantanée.
 *
 * La clé dérive du CONTENU du board et des paramètres : un board régénéré
 * change de clé, donc de fichier — jamais une image périmée servie pour un
 * board neuf. Une seule sérialisation, ici, pour que les deux côtés calculent
 * la même clé ; un ordre de champs différent rendrait le cache aveugle.
 */

export interface RenderCacheParams {
  readonly view: string;
  readonly quality: 'basic' | 'high';
  readonly yaw: number;
  readonly zoom: number;
  readonly width: number;
  readonly height: number;
}

/** Les vues pré-rendues à la livraison : ce que le viewer ouvre en premier. */
export const PRERENDUS: readonly RenderCacheParams[] = [
  { view: 'top', quality: 'basic', yaw: 0, zoom: 1, width: 1600, height: 900 },
  { view: 'iso', quality: 'basic', yaw: 0, zoom: 1, width: 1600, height: 900 },
];

/** Options `kicad-cli` des vues pré-rendues — la même table que `render-presets.ts` côté web. */
export const OPTIONS_PRERENDUS: Readonly<Record<string, { side: string; rotate: string | null; perspective: boolean }>> = {
  top: { side: 'top', rotate: null, perspective: false },
  iso: { side: 'top', rotate: '-45,0,45', perspective: true },
};

export function cleDeRendu(board: Uint8Array, params: RenderCacheParams): string {
  const h = createHash('sha1');
  h.update(board);
  h.update(JSON.stringify({
    view: params.view, quality: params.quality, yaw: params.yaw,
    zoom: params.zoom, width: params.width, height: params.height,
  }));
  return h.digest('hex');
}

/** Chemin, sous `${userId}/${projectId}/`, du rendu de clé `cle`. */
export function cheminDuRendu(cle: string): string {
  return `renders/${cle}.png`;
}

/** Options du MODÈLE 3D : avec ou sans les corps des composants (demandé le 2026-09-14). */
export interface ModelCacheOptions {
  readonly components: boolean;
}

export const MODELE_PAR_DEFAUT: ModelCacheOptions = { components: true };

/**
 * Clé du MODÈLE 3D (GLB) : le contenu du board et l'option `components`.
 * Sans option, la clé est celle du modèle AVEC composants — celle que le
 * pipeline pré-exporte à la livraison.
 */
/**
 * Génération du modèle. À incrémenter quand le CONTENU d'un GLB change pour un
 * même board : la v2 (2026-09-14) embarque les corps des composants — les
 * modèles déposés avant, exportés sans aucun modèle 3D installé, ne doivent
 * plus être servis.
 */
const GENERATION_MODELE = 'glb2';

export function cleDuModele(board: Uint8Array, options: ModelCacheOptions = MODELE_PAR_DEFAUT): string {
  const h = createHash('sha1');
  h.update(board);
  h.update(GENERATION_MODELE);
  if (!options.components) h.update(JSON.stringify({ components: false }));
  return h.digest('hex');
}

/** Chemin, sous `${userId}/${projectId}/`, du modèle GLB de clé `cle`. */
export function cheminDuModele(cle: string): string {
  return `renders/${cle}.glb`;
}

import type { Material, Mesh, MeshStandardMaterial, Object3D } from 'three';

/**
 * Le style du visualiseur 3D de KiCad appliqué au GLB de
 * `kicad-cli pcb export glb` — demandé le 2026-09-15, capture de référence à
 * l'appui. Chaque règle vient d'une MESURE du GLB de `carte-05` :
 *
 *  1. Les couches se reconnaissent au NOM DU MAILLAGE (`<board>_copper`,
 *     `_pad`, `_via`, `_silkscreen`, `_soldermask`, `_PCB`), jamais à la
 *     couleur. L'ancienne règle « gris métallique = cœur FR4 » visait en
 *     réalité les PASTILLES (`_pad` : gris 0,5, métal 1) et les peignait en
 *     beige mat ; le vrai corps FR4 est `_PCB`.
 *  2. KiCad écrit les couleurs de couches en valeurs d'AFFICHAGE (vernis
 *     0,08/0,2/0,14 à 83 %) et les MÉLANGE en espace d'affichage : le vert
 *     sombre du vernis domine, et une piste dessous (cuivre 0,7/0,61/0) ressort
 *     en vert plus clair. Mélangées en linéaire par Three.js, les mêmes valeurs
 *     donnaient soit un vert-gris délavé (sans conversion), soit un vert kaki où
 *     le FR4 olive l'emportait et les pistes disparaissaient (converties) —
 *     mesuré à la capture sur la vraie vue. Le viewer rend donc en espace
 *     d'affichage (`<Canvas linear>`) et prend les couleurs de couches TELLES
 *     QU'ÉCRITES.
 *  3. Les corps STEP, eux, sortent de l'export déjà LINÉARISÉS : dans cet
 *     espace d'affichage ils seraient trop sombres, on les reconvertit en sRGB.
 *     Leurs matériaux ne déclarent aucun facteur métal/rugosité : le défaut glTF
 *     (métal 1, rugosité 1) faisait d'un connecteur blanc un métal terne.
 *  4. FR4 et sérigraphie opaques : trois couches translucides superposées se
 *     trient mal. Le vernis reste translucide — les pistes doivent se voir au
 *     travers — mais mat : à rugosité 0,6 il renvoyait un reflet blanc sur tout
 *     un coin de la carte.
 *
 * Fonctions PURES sur le JSON glTF, testées sans WebGL.
 */

export type CoucheKiCad = 'copper' | 'pad' | 'via' | 'silkscreen' | 'soldermask' | 'PCB';

export interface GltfMaterialDef {
  readonly pbrMetallicRoughness?: {
    readonly baseColorFactor?: readonly number[];
    readonly metallicFactor?: number;
    readonly roughnessFactor?: number;
  };
  readonly alphaMode?: string;
}

export interface GltfJson {
  readonly meshes?: ReadonlyArray<{ readonly name?: string; readonly primitives: ReadonlyArray<{ readonly material?: number }> }>;
  readonly materials?: ReadonlyArray<GltfMaterialDef>;
}

export interface StyleMatiere {
  /** Reconvertir en sRGB une couleur que l'export a linéarisée (corps STEP). */
  readonly lineaireVersSrgb?: boolean;
  readonly metalness?: number;
  readonly roughness?: number;
  /** Rendre le matériau opaque (FR4, sérigraphie). */
  readonly opaque?: boolean;
}

const SUFFIXE_COUCHE = /.+_(copper|pad|via|silkscreen|soldermask|PCB)$/;

export function coucheDuMaillage(nom: string | undefined): CoucheKiCad | null {
  const m = SUFFIXE_COUCHE.exec(nom ?? '');
  return m ? (m[1] as CoucheKiCad) : null;
}

export function couchesParMateriau(json: GltfJson): ReadonlyMap<number, CoucheKiCad> {
  const couches = new Map<number, CoucheKiCad>();
  for (const maillage of json.meshes ?? []) {
    const couche = coucheDuMaillage(maillage.name);
    if (!couche) continue;
    for (const p of maillage.primitives) {
      // Pistes et vias partagent UN matériau dans l'export (mesuré) : la première couche l'emporte.
      if (p.material !== undefined && !couches.has(p.material)) couches.set(p.material, couche);
    }
  }
  return couches;
}

export function styleKiCad(couche: CoucheKiCad | null, def: GltfMaterialDef): StyleMatiere | null {
  switch (couche) {
    case 'copper':
    case 'via':
      // Métal à moitié : un cuivre 100 % métal n'a que l'environnement à
      // refléter et sort SOMBRE sous le vernis. Éclairé en diffus, il ressort
      // plus clair au travers, comme dans KiCad.
      return { metalness: 0.3, roughness: 0.5 };
    case 'pad':
      // Étamé/doré : du métal poli, jamais du FR4.
      return { metalness: 1, roughness: 0.3 };
    case 'silkscreen':
    case 'PCB':
      return { opaque: true };
    case 'soldermask':
      return { roughness: 0.9 };
    case null: {
      const pbr = def.pbrMetallicRoughness;
      const sansFacteurs = pbr?.metallicFactor === undefined && pbr?.roughnessFactor === undefined;
      // La reconversion tient à l'ESPACE de couleur, pas aux facteurs : un corps
      // qui déclare les siens garde sa matière, mais sortirait trop sombre en
      // espace d'affichage s'il restait linéaire.
      return sansFacteurs ? { lineaireVersSrgb: true, metalness: 0, roughness: 0.5 } : { lineaireVersSrgb: true };
    }
  }
}

const DEJA_STYLE = 'kicadStyle';

/**
 * Applique le style à la scène chargée. `indexDuMateriau` rend l'index glTF
 * d'un matériau Three.js (`parser.associations`). Idempotent : `useGLTF` met
 * la scène en cache, et un remontage ne doit pas reconvertir deux fois.
 */
export function appliquerStyleKiCad(
  scene: Object3D,
  json: GltfJson,
  indexDuMateriau: (m: Material) => number | undefined,
): void {
  const couches = couchesParMateriau(json);
  scene.traverse((o) => {
    const mesh = o as Mesh;
    if (!mesh.isMesh) return;
    const materiaux = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const m of materiaux) {
      const std = m as MeshStandardMaterial;
      if (!std.color || std.userData[DEJA_STYLE]) continue;
      std.userData[DEJA_STYLE] = true;
      const index = indexDuMateriau(m);
      if (index === undefined) continue;
      const style = styleKiCad(couches.get(index) ?? null, json.materials?.[index] ?? {});
      if (!style) continue;
      if (style.lineaireVersSrgb) std.color.convertLinearToSRGB();
      if (style.metalness !== undefined) std.metalness = style.metalness;
      if (style.roughness !== undefined) std.roughness = style.roughness;
      if (style.opaque) {
        std.transparent = false;
        std.opacity = 1;
        std.depthWrite = true;
      }
      std.needsUpdate = true;
    }
  });
}

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
 *     0,08/0,2/0,14 = son préréglage « Green »), là où glTF attend du
 *     linéaire : Three.js les éclaircissait, le vernis sortait gris-vert délavé.
 *     Les corps STEP, eux, sont déjà linéarisés par l'export — on n'y touche pas.
 *  3. Les matériaux STEP ne déclarent aucun facteur métal/rugosité : le défaut
 *     glTF (métal 1, rugosité 1) faisait d'un connecteur blanc un métal terne.
 *  4. FR4 et sérigraphie opaques : trois couches translucides superposées se
 *     trient mal. Le vernis reste translucide — les pistes doivent se voir au travers.
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
  /** Reconvertir la couleur d'affichage écrite par KiCad en linéaire. */
  readonly srgbVersLineaire: boolean;
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
      return { srgbVersLineaire: true, metalness: 1, roughness: 0.35 };
    case 'pad':
      // Étamé/doré : du métal poli, jamais du FR4.
      return { srgbVersLineaire: true, metalness: 1, roughness: 0.3 };
    case 'silkscreen':
      return { srgbVersLineaire: true, opaque: true };
    case 'PCB':
      return { srgbVersLineaire: true, opaque: true };
    case 'soldermask':
      // ⚠️ Le vernis N'EST PAS reconverti : essayé et mesuré à la capture, le
      // vert linéarisé (0,007/0,033/0,017) est si sombre qu'à 83 % d'opacité le
      // FR4 transparaît en kaki et les pistes disparaissent. Tel qu'écrit, il
      // rend le vert KiCad, pistes plus claires au travers.
      return { srgbVersLineaire: false, roughness: 0.6 };
    case null: {
      const pbr = def.pbrMetallicRoughness;
      const sansFacteurs = pbr?.metallicFactor === undefined && pbr?.roughnessFactor === undefined;
      return sansFacteurs ? { srgbVersLineaire: false, metalness: 0, roughness: 0.5 } : null;
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
      if (style.srgbVersLineaire) std.color.convertSRGBToLinear();
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

import { describe, it, expect } from 'vitest';
import { Color, Group, Mesh, MeshStandardMaterial, BoxGeometry } from 'three';
import {
  coucheDuMaillage,
  couchesParMateriau,
  styleKiCad,
  appliquerStyleKiCad,
  type GltfJson,
} from '@/widgets/viewer/ui/kicad-3d-style';

/**
 * Le style « visualiseur 3D de KiCad » du GLB — ce que ces tests discriminent,
 * chaque point MESURÉ sur le GLB de `carte-05` exporté par `kicad-cli pcb export glb` :
 *
 *  - les couches de la carte se reconnaissent au NOM DU MAILLAGE
 *    (`<board>_copper|pad|via|silkscreen|soldermask|PCB`) — jamais à la couleur :
 *    l'ancienne règle « gris métallique = FR4 » repeignait en beige les
 *    PASTILLES (`_pad`, gris 0,5 métallique), le vrai corps FR4 étant `_PCB` ;
 *  - KiCad écrit ses couleurs de couches en valeurs d'AFFICHAGE (sRGB) là où
 *    glTF attend du linéaire : sans conversion, le vernis vert sort délavé ;
 *  - les matériaux des corps STEP n'ont AUCUN facteur métal/rugosité, donc le
 *    défaut glTF (métal 1, rugosité 1) : un connecteur blanc sortait en métal
 *    terne. On leur rend une matière plastique ;
 *  - FR4 et sérigraphie deviennent opaques (le vernis reste translucide : on
 *    doit voir les pistes au travers).
 */

const JSON_CARTE: GltfJson = {
  meshes: [
    { name: 'C_0603_1608Metric', primitives: [{ material: 0 }, { material: 1 }] },
    { name: 'board_copper', primitives: [{ material: 2 }] },
    { name: 'board_pad', primitives: [{ material: 3 }] },
    { name: 'board_via', primitives: [{ material: 2 }] },
    { name: 'board_silkscreen', primitives: [{ material: 4 }] },
    { name: 'board_soldermask', primitives: [{ material: 5 }] },
    { name: 'board_PCB', primitives: [{ material: 6 }] },
  ],
  materials: [
    { pbrMetallicRoughness: { baseColorFactor: [0.645, 0.638, 0.572, 1] } },
    { pbrMetallicRoughness: { baseColorFactor: [0.119, 0.059, 0.038, 1] } },
    { pbrMetallicRoughness: { baseColorFactor: [0.7, 0.61, 0, 1], metallicFactor: 1, roughnessFactor: 0.4 } },
    { pbrMetallicRoughness: { baseColorFactor: [0.5, 0.5, 0.5, 1], metallicFactor: 1, roughnessFactor: 0.4 } },
    { pbrMetallicRoughness: { baseColorFactor: [1, 1, 1, 0.9], metallicFactor: 0, roughnessFactor: 0.9 }, alphaMode: 'BLEND' },
    { pbrMetallicRoughness: { baseColorFactor: [0.08, 0.2, 0.14, 0.83], metallicFactor: 0, roughnessFactor: 0.6 }, alphaMode: 'BLEND' },
    { pbrMetallicRoughness: { baseColorFactor: [0.42, 0.45, 0.29, 0.98], metallicFactor: 0, roughnessFactor: 0.8 }, alphaMode: 'BLEND' },
  ],
};

describe('coucheDuMaillage', () => {
  it('reconnait les six couches de la carte par le suffixe du maillage, quel que soit le nom du board', () => {
    expect(coucheDuMaillage('board_copper')).toBe('copper');
    expect(coucheDuMaillage('c05_pad')).toBe('pad');
    expect(coucheDuMaillage('ma_carte_via')).toBe('via');
    expect(coucheDuMaillage('board_silkscreen')).toBe('silkscreen');
    expect(coucheDuMaillage('board_soldermask')).toBe('soldermask');
    expect(coucheDuMaillage('board_PCB')).toBe('PCB');
  });
  it('un corps de composant n est pas une couche', () => {
    expect(coucheDuMaillage('C_0603_1608Metric')).toBeNull();
    expect(coucheDuMaillage('LQFP-48_7x7mm_P0.5mm')).toBeNull();
    expect(coucheDuMaillage(undefined)).toBeNull();
    expect(coucheDuMaillage('copper')).toBeNull();
  });
});

describe('couchesParMateriau', () => {
  it('rattache chaque materiau a la couche du maillage qui l utilise', () => {
    const c = couchesParMateriau(JSON_CARTE);
    expect(c.get(2)).toBe('copper');
    expect(c.get(3)).toBe('pad');
    expect(c.get(4)).toBe('silkscreen');
    expect(c.get(5)).toBe('soldermask');
    expect(c.get(6)).toBe('PCB');
    expect(c.has(0)).toBe(false);
    expect(c.has(1)).toBe(false);
  });
  it('un GLB sans maillage ne leve pas', () => {
    expect(couchesParMateriau({}).size).toBe(0);
  });
});

describe('styleKiCad', () => {
  const mats = JSON_CARTE.materials ?? [];
  it('les PASTILLES restent metalliques — elles ne deviennent plus du FR4', () => {
    const s = styleKiCad('pad', mats[3]!);
    expect(s?.metalness).toBeGreaterThan(0.5);
    expect(s?.srgbVersLineaire).toBe(true);
  });
  it('les couches de la carte sont converties de sRGB en lineaire — SAUF le vernis', () => {
    for (const couche of ['copper', 'via', 'silkscreen', 'PCB'] as const) {
      expect(styleKiCad(couche, mats[2]!)?.srgbVersLineaire).toBe(true);
    }
    // Linearise, le vert tombe si sombre que le FR4 transparait en kaki (capture du 2026-09-15).
    expect(styleKiCad('soldermask', mats[5]!)?.srgbVersLineaire).toBe(false);
  });
  it('FR4 et serigraphie opaques, vernis translucide', () => {
    expect(styleKiCad('PCB', mats[6]!)?.opaque).toBe(true);
    expect(styleKiCad('silkscreen', mats[4]!)?.opaque).toBe(true);
    expect(styleKiCad('soldermask', mats[5]!)?.opaque).toBeFalsy();
  });
  it('un corps STEP sans facteur PBR recoit une matiere plastique, sans reconversion de couleur', () => {
    const s = styleKiCad(null, mats[1]!);
    expect(s).not.toBeNull();
    expect(s?.metalness).toBe(0);
    expect(s?.roughness).toBeLessThan(1);
    expect(s?.srgbVersLineaire).toBe(false);
  });
  it('un materiau de composant qui declare ses facteurs est laisse tel quel', () => {
    expect(styleKiCad(null, { pbrMetallicRoughness: { metallicFactor: 0.2, roughnessFactor: 0.3 } })).toBeNull();
  });
});

describe('appliquerStyleKiCad', () => {
  function scene(): { racine: Group; masque: MeshStandardMaterial; pcb: MeshStandardMaterial; corps: MeshStandardMaterial; pastille: MeshStandardMaterial } {
    const g = new BoxGeometry();
    const masque = new MeshStandardMaterial({ color: new Color(0.08, 0.2, 0.14), transparent: true, opacity: 0.83 });
    const pcb = new MeshStandardMaterial({ color: new Color(0.42, 0.45, 0.29), transparent: true, opacity: 0.98 });
    const corps = new MeshStandardMaterial({ color: new Color(0.119, 0.059, 0.038), metalness: 1, roughness: 1 });
    const pastille = new MeshStandardMaterial({ color: new Color(0.5, 0.5, 0.5), metalness: 1, roughness: 0.4 });
    const racine = new Group();
    racine.add(new Mesh(g, masque), new Mesh(g, pcb), new Mesh(g, corps), new Mesh(g, pastille));
    return { racine, masque, pcb, corps, pastille };
  }
  const indices = (m: MeshStandardMaterial, s: ReturnType<typeof scene>): number | undefined =>
    new Map([[s.corps, 1], [s.pastille, 3], [s.masque, 5], [s.pcb, 6]]).get(m);

  it('applique le style par materiau, UNE seule fois (la scene est en cache chez useGLTF)', () => {
    const s = scene();
    const indexDe = (m: object) => indices(m as MeshStandardMaterial, s);
    appliquerStyleKiCad(s.racine, JSON_CARTE, indexDe);
    const vert = s.masque.color.g;
    expect(vert).toBeCloseTo(0.2, 5);
    expect(s.masque.transparent).toBe(true);
    const fr4 = s.pcb.color.r;
    expect(fr4).toBeCloseTo(new Color(0.42, 0.45, 0.29).convertSRGBToLinear().r, 5);
    expect(s.pcb.transparent).toBe(false);
    expect(s.pcb.opacity).toBe(1);
    expect(s.corps.metalness).toBe(0);
    expect(s.pastille.metalness).toBeGreaterThan(0.5);
    expect(s.pastille.color.r).not.toBeCloseTo(0.5, 2);

    appliquerStyleKiCad(s.racine, JSON_CARTE, indexDe);
    expect(s.masque.color.g).toBe(vert);
    expect(s.pcb.color.r).toBe(fr4); // jamais reconverti deux fois
  });
});

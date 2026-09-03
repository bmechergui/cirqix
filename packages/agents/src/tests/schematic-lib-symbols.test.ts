/**
 * Les sous-symboles d'unité ne portent PAS le préfixe de bibliothèque.
 *
 * Trouvé le 2026-08-24 en bissectant le schéma d'un run réel. `kicad-cli sch erc`
 * répondait `Failed to load schematic` — le défaut qui bloquait l'ERC depuis
 * plusieurs jours, et qui expliquait aussi un PCB généré à 1 composant sur 27,
 * la netlist se construisant depuis ce même fichier.
 *
 * La bissection a montré que les DIX symboles de `lib_symbols` échouaient
 * individuellement. Leur point commun :
 *
 *     (symbol "Device:R"                 ← le parent porte le préfixe, c'est juste
 *       (symbol "Device:R_0_1" …)        ← l'unité NE DOIT PAS le porter
 *       (symbol "Device:R_1_1" …))
 *
 * KiCad attend `"R_0_1"`. Vérifié : en retirant le préfixe des 20 sous-symboles,
 * le même fichier passe de `Failed to load schematic` à un rapport ERC produit.
 *
 * ⚠️ `services/kicad/tools/schematic.py` les écrit correctement depuis toujours.
 * Seul ce générateur TypeScript — le repli de niveau 3 — se trompait, ce qui
 * rendait la panne INTERMITTENTE : elle n'apparaissait que sur les runs où les
 * deux chemins Python avaient échoué avant lui.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const SOURCE = readFileSync(
  join(__dirname, '..', 'engines', 'schematic-engine.ts'),
  'utf-8',
);

/** `(symbol "Lib:Nom_<unité>_<style>"` — la forme que KiCad refuse. */
const SOUS_SYMBOLE_PREFIXE = /\(symbol "[A-Za-z_][\w]*:[^"]*_\d+_\d+"/g;

/** `(symbol "Nom_<unité>_<style>"` — la forme attendue. */
const SOUS_SYMBOLE_NU = /\(symbol "[^":]+_\d+_\d+"/g;

describe('lib_symbols du générateur TypeScript', () => {
  it('ne préfixe aucun sous-symbole d\'unité', () => {
    const fautifs = SOURCE.match(SOUS_SYMBOLE_PREFIXE) ?? [];
    expect(fautifs, `sous-symboles préfixés : ${fautifs.join(', ')}`).toEqual([]);
  });

  it('déclare bien des sous-symboles d\'unité', () => {
    // Sans cette garde, supprimer purement et simplement les sous-symboles
    // ferait passer le test précédent tout en produisant des symboles vides.
    expect((SOURCE.match(SOUS_SYMBOLE_NU) ?? []).length).toBeGreaterThanOrEqual(20);
  });

  it('garde le préfixe sur les symboles PARENTS', () => {
    // Le parent, lui, DOIT porter `Lib:Nom` — c'est la reference que les
    // instances du schema citent. Retirer le prefixe partout casserait tout.
    for (const attendu of ['(symbol "Device:R"', '(symbol "Device:C"',
                           '(symbol "power:GND"']) {
      expect(SOURCE).toContain(attendu);
    }
  });
});

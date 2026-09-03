/**
 * Le client envoie le PLAFOND DU PLAN, pas son estimation.
 *
 * Mesuré le 2026-08-26 sur le banc des cinq cartes. L'ESP32 (20 composants,
 * 5 nets) restait à 2 couches et n'y arrivait pas — 25 % routé, 8 connexions
 * manquantes — alors que le service sait escalader 2 → 4 → 6 → 8.
 *
 * La cause : `decidedLayers = min(neededLayers, plafondDuPlan)` où
 * `neededLayers` vaut 2 dès que la carte a ≤ 30 composants et ≤ 30 nets. Le
 * service recevait donc 2, et `_layer_ladder(2)` ne rend qu'UN palier :
 * l'escalade était structurellement impossible.
 *
 * ⚠️ L'heuristique est une ESTIMATION faite avant le routage. Le service, lui,
 * escalade sur une MESURE — il a essayé, il a compté, il monte d'un cran. Faire
 * primer la première sur la seconde revient à préférer une supposition à un
 * fait constaté.
 *
 * ⚠️ Le plan reste un PLAFOND et le gate est intact : un compte gratuit ne
 * dépasse pas 2 couches, quoi que le routage réclame. On retire une borne
 * supplémentaire, jamais la borne commerciale.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const SOURCE = readFileSync(
  join(__dirname, '..', 'tools', 'handlers', 'routing.ts'),
  'utf-8',
);

describe('plafond de couches envoyé au service', () => {
  it("n'écrase plus le plafond par une estimation de composants", () => {
    // `Math.min(neededLayers, ...)` était exactement la borne fautive.
    expect(SOURCE).not.toContain('Math.min(\n    neededLayers,');
  });

  it('envoie bien le plafond du plan', () => {
    expect(SOURCE).toMatch(/decidedLayers\s*=\s*maxLayersForPlan\(/);
  });

  it('conserve le gate commercial', () => {
    // Sans lui, un compte gratuit obtiendrait des cartes 4 couches —
    // sensiblement plus chères à fabriquer et contraires à la grille annoncée.
    expect(SOURCE).toContain('maxLayersForPlan(getProjectPlan(projectId))');
  });

  it('garde une trace écrite de la raison', () => {
    // Le prochain lecteur doit comprendre pourquoi l'estimation a disparu,
    // sinon elle reviendra.
    expect(SOURCE).toMatch(/escalad/i);
  });
});

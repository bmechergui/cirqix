import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  LONG_CALL_HEADERS_TIMEOUT_MS,
  LONG_CALL_BODY_TIMEOUT_MS,
  longCallDispatcher,
} from '../engines/long-call-transport';

/**
 * Le `fetch` global de Node (undici) impose ses propres échéances —
 * `headersTimeout` et `bodyTimeout`, 300 000 ms chacune par défaut — que
 * l'`AbortSignal` de l'appelant ne désarme PAS. Un appel dont la réponse met
 * plus de 5 minutes à commencer meurt donc sur `UND_ERR_HEADERS_TIMEOUT`,
 * quel que soit le budget accordé au serveur.
 *
 * Un test comportemental de ce plafond exigerait un serveur muet pendant plus
 * de 5 minutes : il durerait plus longtemps que toute la suite. On verrouille
 * donc la CONFIGURATION et le CÂBLAGE, et la preuve comportementale vit dans la
 * mesure du 2026-08-20 (routage STM32 réel, documentée dans CLAUDE.md).
 */

const ENGINES = join(__dirname, '..', 'engines');
const read = (file: string): string => readFileSync(join(ENGINES, file), 'utf8');

describe('transport des appels longs', () => {
  it('désarme les deux échéances de transport', () => {
    expect(LONG_CALL_HEADERS_TIMEOUT_MS).toBe(0);
    expect(LONG_CALL_BODY_TIMEOUT_MS).toBe(0);
  });

  it('partage un seul dispatcher — sinon les sockets fuient', () => {
    expect(longCallDispatcher()).toBe(longCallDispatcher());
  });
});

describe('câblage des clients aux appels longs', () => {
  // Ces deux étapes sont les seules à pouvoir dépasser 5 minutes : le routage
  // dispose de 1800 s sur 4 couches, le placement de 900 s. Les autres appels
  // (ERC, DRC, export) restent loin sous le défaut d'undici.
  for (const file of ['routing-service.ts', 'placement-service.ts']) {
    it(`${file} passe par longCallFetch et non par le fetch global`, () => {
      const source = read(file);
      expect(source).toContain('longCallFetch');
      // Un `await fetch(` résiduel réintroduirait le plafond de 300 s en silence.
      expect(source).not.toMatch(/await fetch\(/);
    });
  }
});

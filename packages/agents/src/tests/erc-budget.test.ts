import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { ERC_TIMEOUT_MS } from '../engines/erc-service';
import { PLACEMENT_TIMEOUT_MS } from '../engines/placement-budget';

/**
 * Budget accordé à l'ERC, côté client.
 *
 * Mesuré le 2026-09-15, run NE555 `1b2c2ab4` par la file : le client
 * raccrochait à 10 s. Le service avait bien reçu la requête — la validation
 * kicad-tools est journalisée à 08:06:25 — mais n'avait pas encore répondu
 * quand l'`AbortSignal` a tiré (`TimeoutError`). Aucun `POST /erc` n'apparaît
 * dans le journal du service. Le handler est retombé sur l'ERC TypeScript et
 * a promu `ERC_CLEAN` avec la note « kicad-cli indisponible » : kicad-cli
 * était DISPONIBLE, c'est le client qui ne l'attendait pas.
 *
 * Isolé, le même schéma passe en 3,6 à 4,1 s. Mais le service s'accorde
 * jusqu'à `_MAX_ITERATIONS` passes de kicad-cli de `_KICAD_CLI_TIMEOUT_S`
 * chacune : un budget client de 10 s ne couvrait pas son propre pire cas.
 * Même classe de défaut que le budget de placement du 2026-08-20.
 *
 * La garde lit les limites dans `routers/erc.py` : relever le budget du
 * service sans relever celui du client la fait échouer.
 */

const ERC_PY = resolve(__dirname, '../../../../services/kicad/routers/erc.py');

function constantePython(nom: string): number {
  const source = readFileSync(ERC_PY, 'utf-8');
  const m = source.match(new RegExp(`^${nom}\\s*(?::\\s*int)?\\s*=\\s*(\\d+)`, 'm'));
  if (!m) throw new Error(`${nom} introuvable dans routers/erc.py — la garde ne mesure plus rien`);
  return Number(m[1]);
}

describe('budget ERC', () => {
  it('couvre le pire cas que le service s’accorde lui-même', () => {
    const iterations = constantePython('_MAX_ITERATIONS');
    const cliTimeoutS = constantePython('_KICAD_CLI_TIMEOUT_S');
    // + la validation kicad-tools qui précède kicad-cli (≈ 3 s mesurées) et le
    // transport : on exige au moins 15 s de marge au-delà des passes kicad-cli.
    const pireCasMs = (iterations * cliTimeoutS + 15) * 1000;
    expect(ERC_TIMEOUT_MS).toBeGreaterThanOrEqual(pireCasMs);
  });

  it('reste borné — un service figé doit rester récupérable', () => {
    expect(ERC_TIMEOUT_MS).toBeLessThanOrEqual(PLACEMENT_TIMEOUT_MS);
  });
});

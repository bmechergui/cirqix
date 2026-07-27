import { describe, it, expect, beforeAll } from 'vitest';

/**
 * Test d'INTÉGRATION — chaîne de handlers TS contre le service KiCad RÉEL.
 *
 * Tous les autres tests de ce dossier mockent les clients de service : ils
 * valident la logique des handlers, jamais le CÂBLAGE (noms de champs, formes
 * de requête/réponse, base64). Ce trou a coûté cher pendant la validation du
 * 2026-07-27 : le driver Python envoyait `kicad_sch_content` au lieu de
 * `kicad_sch_b64`, ce qu'aucun test mocké ne pouvait détecter.
 *
 * OPT-IN — ignoré sauf si `CIRQIX_LIVE_KICAD=1`, car il exige le conteneur
 * `cirqix-kicad` démarré (token ≥32 caractères) :
 *
 *     KICAD_SERVICE_URL=http://127.0.0.1:8766 \
 *     KICAD_SERVICE_TOKEN=<token> \
 *     CIRQIX_LIVE_KICAD=1 npx vitest run src/tests/pipeline-live.test.ts
 *
 * Le rôle du LLM (agent Schéma) est tenu par la fixture ci-dessous, comme dans
 * `services/kicad/examples/led-blinker-full-pipeline/`.
 */

const LIVE = process.env['CIRQIX_LIVE_KICAD'] === '1';
const describeLive = LIVE ? describe : describe.skip;

import { pcbStateCache } from '../tools/shared';
import { handleGenPcb } from '../tools/handlers/gen-pcb';
import { handlePlacement } from '../tools/handlers/placement';
import { handleRouting } from '../tools/handlers/routing';
import { handleDrc } from '../tools/handlers/drc';
import { handleExport } from '../tools/handlers/export';

const PROJECT = 'live-led-blinker';

/** Sortie de l'agent Schéma — NE555 astable pilotant une LED (cf. la fixture). */
const SCHEMA = {
  components: [
    { ref: 'U1', value: 'NE555', footprint: 'Package_DIP:DIP-8_W7.62mm' },
    { ref: 'R1', value: '10k', footprint: 'Resistor_SMD:R_0805_2012Metric' },
    { ref: 'R2', value: '68k', footprint: 'Resistor_SMD:R_0805_2012Metric' },
    { ref: 'R3', value: '330', footprint: 'Resistor_SMD:R_0805_2012Metric' },
    { ref: 'C1', value: '10uF', footprint: 'Capacitor_SMD:C_0805_2012Metric' },
    { ref: 'C2', value: '100nF', footprint: 'Capacitor_SMD:C_0805_2012Metric' },
    { ref: 'D1', value: 'LED', footprint: 'LED_SMD:LED_0805_2012Metric' },
    {
      ref: 'J1',
      value: 'Conn_01x02',
      footprint: 'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical',
    },
  ],
  nets: ['VCC', 'GND', 'TRIG_THR', 'DISCH', 'OUT', 'LED_A'],
  connections: [
    { name: 'VCC', pins: [{ ref: 'J1', pin: 1 }, { ref: 'U1', pin: 8 }, { ref: 'U1', pin: 4 }, { ref: 'R1', pin: 1 }, { ref: 'C2', pin: 1 }] },
    { name: 'GND', pins: [{ ref: 'J1', pin: 2 }, { ref: 'U1', pin: 1 }, { ref: 'C1', pin: 2 }, { ref: 'C2', pin: 2 }, { ref: 'D1', pin: 2 }] },
    { name: 'DISCH', pins: [{ ref: 'U1', pin: 7 }, { ref: 'R1', pin: 2 }, { ref: 'R2', pin: 1 }] },
    { name: 'TRIG_THR', pins: [{ ref: 'U1', pin: 2 }, { ref: 'U1', pin: 6 }, { ref: 'R2', pin: 2 }, { ref: 'C1', pin: 1 }] },
    { name: 'OUT', pins: [{ ref: 'U1', pin: 3 }, { ref: 'R3', pin: 1 }] },
    { name: 'LED_A', pins: [{ ref: 'R3', pin: 2 }, { ref: 'D1', pin: 1 }] },
  ],
};

describeLive('pipeline live — handlers TS contre le service KiCad réel', () => {
  beforeAll(async () => {
    const url = process.env['KICAD_SERVICE_URL'];
    const token = process.env['KICAD_SERVICE_TOKEN'];
    expect(url, 'KICAD_SERVICE_URL requis').toBeTruthy();
    expect(token, 'KICAD_SERVICE_TOKEN requis').toBeTruthy();

    // Rôle de l'agent Schéma (Haiku en prod) : produire le .kicad_sch. Sans lui
    // en cache, `generate_pcb` court-circuite ses deux niveaux Python et rend ""
    // — c'est précisément ce que ce test a révélé le 2026-07-27.
    const res = await fetch(`${url}/schematic/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        components: SCHEMA.components,
        nets: SCHEMA.nets,
        connections: SCHEMA.connections,
        board_width_mm: 60,
        board_height_mm: 45,
        project_id: 'live',
      }),
      signal: AbortSignal.timeout(120_000),
    });
    expect(res.ok, `/schematic/generate a répondu ${res.status}`).toBe(true);
    const sch = (await res.json()) as { success: boolean; kicad_sch_content?: string };
    expect(sch.success).toBe(true);

    pcbStateCache.clear();
    pcbStateCache.set(PROJECT, {
      schema: SCHEMA,
      boardW: 60,
      boardH: 45,
      kicad_sch_content: sch.kicad_sch_content,
    } as never);
  }, 180_000);

  it(
    'enchaîne gen_pcb → placement → routing → drc → export contre le vrai service',
    async () => {
      // ④ Génération PCB
      const gen = await handleGenPcb(PROJECT);
      expect(gen['status']).toBe('success');
      expect(String(gen['kicad_pcb_content'])).toContain('(kicad_pcb');

      // ⑤ Placement — fail fast si le service est injoignable, donc un succès
      //    prouve que le client parle bien au conteneur.
      const placement = await handlePlacement({}, PROJECT);
      expect(placement['status']).toBe('success');
      expect(placement['engine']).toBe('pcbnew');
      expect(Array.isArray(placement['placements'])).toBe(true);
      expect((placement['placements'] as unknown[]).length).toBe(SCHEMA.components.length);

      // ⑥ Routage — le pourcentage doit être RÉEL, pas un 100 de repli.
      const routing = await handleRouting(PROJECT);
      expect(routing['status']).toBe('success');
      expect(routing['engine']).toBe('kicad-tools');
      expect(typeof routing['routed_percent']).toBe('number');
      expect(routing['routed_percent']).toBe(100);

      // ⑦ DRC — doit s'EXÉCUTER (ni sauté, ni erreur) ; propre ou non dépend du
      //    tirage GA, ce n'est pas ce que ce test verrouille.
      const drc = await handleDrc({}, PROJECT);
      expect(drc['status']).toBe('success');
      expect(drc['drc_skipped']).toBe(false);
      expect(drc['engine']).toBe('kicad-cli');
      expect(typeof drc['drc_clean']).toBe('boolean');

      // ⑧ Export — de vrais fichiers de fabrication.
      const exported = await handleExport(PROJECT);
      expect(exported['status']).toBe('success');
      expect(exported['pcb_status']).toBe('PCB_LIVRÉ');
      expect(Number(exported['gerber_layers'])).toBeGreaterThan(0);
      expect(String(exported['bom_csv'])).toContain('R3,330');
    },
    600_000,
  );
});

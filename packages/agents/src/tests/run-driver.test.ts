import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * La chaîne du driver — le pipeline complet SANS le moindre appel au modèle.
 *
 * Le solde de l'API Anthropic est épuisé depuis le 2026-09-06, et
 * l'orchestrateur est la toute première étape : plus aucun PCB ne peut aboutir
 * par la voie normale. Or `call_agent_schema` est le SEUL maillon qui appelle un
 * modèle — le banc des dix cartes a mesuré que tout le reste va jusqu'aux
 * Gerbers sans lui.
 *
 * Ce porteur enchaîne donc les VRAIS handlers, dans l'ordre du pipeline, et émet
 * exactement les mêmes événements que l'orchestrateur : la file, le journal,
 * Realtime et la Timeline n'ont rien à savoir de la différence.
 *
 * ⚠️ Ce n'est PAS le simulateur, qui fabrique des états. Ici tout est réel, DRC
 * compris. Ce qui change est la PROVENANCE — et c'est pourquoi le gate JLCPCB,
 * qui exige `orchestrator`, refuse toujours ces boards.
 */

vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});

const outils = vi.hoisted(() => ({ executeToolStub: vi.fn() }));
vi.mock('../tools', () => outils);

import { runDriver } from '../pipeline/run-driver';
import type { SSEEvent } from '../orchestrator';

const SCHEMA = { components: [{ ref: 'R1', value: '1k', footprint: 'R_0603', symbol: 'Device:R' }], nets: ['GND'] };

/** Réponses nominales, dans l'ordre où le porteur les demande. */
function reponsesNominales(): Record<string, Record<string, unknown>> {
  return {
    call_agent_schema: { status: 'success', pcb_status: 'SCHEMA_DONE', kicad_sch_content: '(sch)' },
    call_agent_erc: { status: 'success', pcb_status: 'ERC_CLEAN' },
    call_agent_gen_pcb: { status: 'success', kicad_pcb_content: '(pcb)' },
    call_agent_placement: { status: 'success', pcb_status: 'PLACEMENT_DONE' },
    call_agent_routing: { status: 'success', pcb_status: 'ROUTING_DONE', routed_percent: 100 },
    call_agent_drc: { status: 'success', pcb_status: 'DRC_CLEAN', drc_clean: true },
    call_agent_export: { status: 'success', pcb_status: 'PCB_LIVRÉ', zip_b64: 'UEs=', bom_csv: 'ref,val' },
  };
}

async function collecter(gen: AsyncGenerator<SSEEvent>): Promise<SSEEvent[]> {
  const out: SSEEvent[] = [];
  for await (const e of gen) out.push(e);
  return out;
}

beforeEach(() => {
  vi.clearAllMocks();
  const r = reponsesNominales();
  outils.executeToolStub.mockImplementation(async (tool: string) => r[tool] ?? { status: 'success' });
});

describe('runDriver', () => {
  it('enchaîne les sept étapes, dans l ordre du pipeline', async () => {
    await collecter(runDriver({ schema: SCHEMA, projectId: 'p1' }));

    expect(outils.executeToolStub.mock.calls.map((c) => c[0])).toEqual([
      'call_agent_schema',
      'call_agent_erc',
      'call_agent_gen_pcb',
      'call_agent_placement',
      'call_agent_routing',
      'call_agent_drc',
      'call_agent_export',
    ]);
  });

  it('passe le schéma du driver au handler, jamais une description', async () => {
    await collecter(runDriver({ schema: SCHEMA, projectId: 'p2' }));

    const premier = outils.executeToolStub.mock.calls[0];
    const entree = premier?.[1];
    expect(entree).toHaveProperty('schema_json');
    // ⚠️ `user_description` déclencherait l'appel à Haiku dans `handleSchema` :
    // le porteur serait « sans modèle » en intention et pas en fait.
    expect(entree).not.toHaveProperty('user_description');
  });

  it('émet les étapes que la Timeline sait afficher', async () => {
    const ev = await collecter(runDriver({ schema: SCHEMA, projectId: 'p3' }));
    const etapes = ev.filter((e) => e.type === 'step').map((e) => (e as { step: string }).step);

    expect(etapes).toEqual(['SCHEMA', 'ERC', 'PLACEMENT', 'ROUTING', 'DRC', 'EXPORT']);
  });

  it('termine en PCB_LIVRÉ — le seul état que le porteur accepte de facturer', async () => {
    const ev = await collecter(runDriver({ schema: SCHEMA, projectId: 'p4' }));

    const etats = ev.filter((e) => e.type === 'pcb_state');
    const dernier = etats[etats.length - 1] as { state: Record<string, unknown> } | undefined;
    expect(dernier?.state['pcb_status']).toBe('PCB_LIVRÉ');
    expect(ev[ev.length - 1]?.type).toBe('done');
  });

  it('ECHOUE FERME dès qu une étape rend une erreur, sans continuer', async () => {
    // Le contrat de toute la chaîne : un routage en panne ne doit pas laisser le
    // DRC puis l'export bâtir un succès par-dessus. Les handlers échouent déjà
    // fermés un par un ; le porteur ne doit pas défaire cette garantie.
    outils.executeToolStub.mockImplementation(async (tool: string) => {
      if (tool === 'call_agent_routing') return { status: 'error', error: 'service injoignable' };
      return reponsesNominales()[tool] ?? { status: 'success' };
    });

    const ev = await collecter(runDriver({ schema: SCHEMA, projectId: 'p5' }));

    const appeles = outils.executeToolStub.mock.calls.map((c) => c[0]);
    expect(appeles).not.toContain('call_agent_drc');
    expect(appeles).not.toContain('call_agent_export');
    expect(ev.some((e) => e.type === 'error')).toBe(true);
    expect(ev.some((e) => e.type === 'done')).toBe(false);
  });

  it('refuse de démarrer sans schéma', async () => {
    const ev = await collecter(runDriver({ schema: null as never, projectId: 'p6' }));
    expect(ev[0]?.type).toBe('error');
    expect(outils.executeToolStub).not.toHaveBeenCalled();
  });

  it('remonte les étapes de raisonnement quand le routage en produit', async () => {
    outils.executeToolStub.mockImplementation(async (tool: string) => {
      if (tool === 'call_agent_routing') {
        return { ...reponsesNominales()[tool], reasoning_steps: ['déplace C12 près de U1'] };
      }
      return reponsesNominales()[tool] ?? { status: 'success' };
    });

    const ev = await collecter(runDriver({ schema: SCHEMA, projectId: 'p7' }));
    const r = ev.find((e) => e.type === 'reasoning') as { steps: string[] } | undefined;
    expect(r?.steps).toEqual(['déplace C12 près de U1']);
  });
});

import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * Le porteur du driver accepte une DESCRIPTION à la place d'un schéma :
 * `call_agent_schema` la confie alors au fournisseur configuré
 * (D-2026-09-13-a, Claude Code en ligne de commande). Le reste de la chaîne
 * est inchangé.
 */
vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});
const outils = vi.hoisted(() => ({ executeToolStub: vi.fn() }));
vi.mock('../tools', () => outils);

import { runDriver } from '../pipeline/run-driver';
import type { SSEEvent } from '../orchestrator';

function nominal(): Record<string, Record<string, unknown>> {
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
  const reponses = nominal();
  outils.executeToolStub.mockImplementation(async (outil: string) => reponses[outil] ?? { status: 'error', error: `outil inconnu ${outil}` });
});

describe('runDriver — description sans schéma', () => {
  it('confie la description à call_agent_schema et va jusqu au bout', async () => {
    const evs = await collecter(runDriver({ prompt: 'un clignotant NE555', projectId: 'p' }));
    const appelSchema = outils.executeToolStub.mock.calls.find((c) => c[0] === 'call_agent_schema')!;
    expect(appelSchema[1]).toMatchObject({ user_description: 'un clignotant NE555' });
    expect(appelSchema[1]).not.toHaveProperty('schema_json');
    expect(evs.at(-1)).toMatchObject({ type: 'done' });
  });

  it('un schéma fourni l emporte sur la description', async () => {
    const schema = { components: [{ ref: 'R1' }], nets: ['GND'] };
    await collecter(runDriver({ schema, prompt: 'ignoré', projectId: 'p' }));
    const appelSchema = outils.executeToolStub.mock.calls.find((c) => c[0] === 'call_agent_schema')!;
    expect(appelSchema[1]).toMatchObject({ schema_json: schema });
    expect(appelSchema[1]).not.toHaveProperty('user_description');
  });

  it('sans schéma ni description, refuse sans appeler un seul outil', async () => {
    const evs = await collecter(runDriver({ projectId: 'p', prompt: '   ' }));
    expect(evs).toHaveLength(1);
    expect(evs[0]).toMatchObject({ type: 'error' });
    expect(outils.executeToolStub).not.toHaveBeenCalled();
  });
});

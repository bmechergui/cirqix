import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * POST /api/jlcpcb/order — dernier verrou avant une commande de fabrication.
 *
 * Le gate historique ne regardait que projects.status. Or resolveAgentMode()
 * renvoie 'simulator' par DÉFAUT (il faut CIRQIX_AGENT_MODE=orchestrator|real
 * pour le vrai pipeline), et simulator.ts persiste status:'DRC_CLEAN' avec des
 * drcViolations:[] fabriqués. Un board entièrement simulé atteignait donc l'état
 * qui autorise la commande.
 *
 * Le gate exige désormais une provenance explicite : seul un projet produit par
 * le pipeline réel (agent_mode = 'orchestrator') est commandable. Fail closed —
 * une provenance inconnue (NULL, projets antérieurs à la migration 007) est
 * refusée, car « inconnu » n'est pas « vérifié ».
 */

const supabaseMock = vi.hoisted(() => ({ createRouteHandlerClient: vi.fn() }));
vi.mock('@/shared/lib/supabase-server', () => supabaseMock);

import { POST } from '@/app/api/jlcpcb/order/route';

interface ProjectRow {
  id: string;
  status: string;
  agent_mode: string | null;
  pcb_state?: Record<string, unknown>;
}

const EXPORTED_STATE = { gerberZipB64: 'UEsDBBQ=', bomCsv: 'ref,value\nR1,1k' };

function makeClient(opts: { user?: { id: string } | null; project?: ProjectRow | null }) {
  const updates: Array<Record<string, unknown>> = [];
  const client = {
    auth: {
      getUser: async () => ({ data: { user: opts.user === undefined ? { id: 'u1' } : opts.user } }),
    },
    from: () => ({
      select: () => ({
        eq: () => ({
          single: async () => ({
            data: opts.project === undefined
              ? { id: 'p1', status: 'DRC_CLEAN', agent_mode: 'orchestrator', pcb_state: EXPORTED_STATE }
              : opts.project,
          }),
        }),
      }),
      update: (payload: Record<string, unknown>) => {
        updates.push(payload);
        return { eq: async () => ({ data: null, error: null }) };
      },
    }),
  };
  return { client, updates };
}

const VALID_BODY = {
  projectId: '3f2504e0-4f89-11d3-9a0c-0305e82c3301',
  qty: 5,
  confirmed: true,
};

function makeRequest(body: unknown) {
  return { json: async () => body } as never;
}

async function order(
  body: unknown,
  clientOpts: Parameters<typeof makeClient>[0] = {},
) {
  const { client, updates } = makeClient(clientOpts);
  supabaseMock.createRouteHandlerClient.mockResolvedValue(client);
  const response = await POST(makeRequest(body));
  return { response, json: await response.json(), updates };
}

beforeEach(() => {
  supabaseMock.createRouteHandlerClient.mockReset();
});

describe('garde-fous existants', () => {
  it('refuse un utilisateur non authentifié', async () => {
    const { response } = await order(VALID_BODY, { user: null });

    expect(response.status).toBe(401);
  });

  it('exige la confirmation explicite', async () => {
    const { response, json } = await order({ ...VALID_BODY, confirmed: false });

    expect(response.status).toBe(400);
    expect(String(json.error)).toContain('OUI JE CONFIRME');
  });

  it('refuse un projet introuvable', async () => {
    const { response } = await order(VALID_BODY, { project: null });

    expect(response.status).toBe(404);
  });

  it('refuse un projet dont le DRC n’est pas passé', async () => {
    const { response } = await order(VALID_BODY, {
      project: { id: 'p1', status: 'ROUTING_DONE', agent_mode: 'orchestrator' },
    });

    expect(response.status).toBe(422);
  });
});

describe('provenance du board — le gate ne doit pas être dupable par le simulateur', () => {
  it('accepte un board DRC_CLEAN issu du pipeline réel', async () => {
    const { response, json, updates } = await order(VALID_BODY, {
      project: { id: 'p1', status: 'DRC_CLEAN', agent_mode: 'orchestrator', pcb_state: EXPORTED_STATE },
    });

    expect(response.status).toBe(200);
    expect(json.success).toBe(true);
    expect(String(json.data.requestRef)).toMatch(/^CIRQIX-PREP-/);
    expect(json.data.submitted).toBe(false);
    expect(json.data.status).toBe('ready_for_manual_submission');
    expect(String(json.data.message)).toContain('No order was sent');
    expect(updates).toHaveLength(0);
  });

  it('accepte un board déjà livré issu du pipeline réel', async () => {
    const { response } = await order(VALID_BODY, {
      project: { id: 'p1', status: 'PCB_LIVRÉ', agent_mode: 'orchestrator', pcb_state: EXPORTED_STATE },
    });

    expect(response.status).toBe(200);
  });

  it('REFUSE un board simulé, même marqué DRC_CLEAN', async () => {
    const { response, json, updates } = await order(VALID_BODY, {
      project: { id: 'p1', status: 'DRC_CLEAN', agent_mode: 'simulator' },
    });

    expect(response.status).toBe(422);
    expect(String(json.error)).toContain('simul');
    expect(updates).toHaveLength(0);
  });

  it('REFUSE un board produit par le repli local', async () => {
    // `runLocalPipeline` enchaîne CINQ étapes sur huit — footprint, gen_pcb et
    // export sont sautés — donc son board n'a ni footprints résolus ni PCB
    // généré nativement. Il se déclarait pourtant `orchestrator` et passait ce
    // gate. Sa provenance porte désormais son propre nom (migration 018), et
    // le fail-closed existant la refuse SANS qu'une ligne d'ici ait changé.
    const { response, json, updates } = await order(VALID_BODY, {
      project: { id: 'p1', status: 'DRC_CLEAN', agent_mode: 'local_fallback' },
    });

    expect(response.status).toBe(422);
    expect(String(json.error).toLowerCase()).toMatch(/pipeline|provenance|simul/);
    expect(updates).toHaveLength(0);
  });

  it('refuse la préparation sans Gerber et BOM exportés', async () => {
    const { response, json, updates } = await order(VALID_BODY, {
      project: { id: 'p1', status: 'DRC_CLEAN', agent_mode: 'orchestrator' },
    });

    expect(response.status).toBe(422);
    expect(String(json.error)).toContain('Gerber');
    expect(updates).toHaveLength(0);
  });

  it('REFUSE une provenance inconnue — fail closed sur les projets pré-migration', async () => {
    const { response, updates } = await order(VALID_BODY, {
      project: { id: 'p1', status: 'DRC_CLEAN', agent_mode: null },
    });

    expect(response.status).toBe(422);
    expect(updates).toHaveLength(0);
  });

  it('ne marque jamais PCB_LIVRÉ un projet refusé', async () => {
    const { updates } = await order(VALID_BODY, {
      project: { id: 'p1', status: 'DRC_CLEAN', agent_mode: 'simulator' },
    });

    expect(updates).toHaveLength(0);
  });
});

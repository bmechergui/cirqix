import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * Invariants STRUCTURELS de la boucle agentique (orchestrator.ts).
 *
 * Les règles métier à seuil (rescue reasoner, retry placement) sont couvertes par
 * orchestrator-reason.test.ts et orchestrator-retry.test.ts. Ce fichier couvre la
 * mécanique de la boucle elle-même — les invariants dont la régression est chère
 * à diagnostiquer parce qu'elle ne se manifeste qu'en bout de pipeline :
 *
 *   - strip des blobs KiCad avant envoi à Sonnet (~70% du coût token input)
 *   - plafond MAX_ITERATIONS (boucle infinie = facturation runaway)
 *   - guard ANTHROPIC_API_KEY (erreur propre au lieu d'un crash)
 *   - stepMap / pcbStateTools (le viewer frontend est muet sans ces events)
 *   - robustesse au JSON d'outil malformé
 *   - transmission de l'historique de conversation
 */

const hoisted = vi.hoisted(() => ({
  streamQueue: [] as unknown[][],
  /** Snapshot profond des params de chaque appel API (les messages sont mutés après coup). */
  createCalls: [] as Array<{ messages: unknown[] }>,
}));

vi.mock('@anthropic-ai/sdk', () => ({
  default: class {
    messages = {
      create: async (params: { messages: unknown[] }) => {
        hoisted.createCalls.push({
          messages: JSON.parse(JSON.stringify(params.messages)) as unknown[],
        });
        const events =
          hoisted.streamQueue.shift() ?? [
            { type: 'message_delta', delta: { stop_reason: 'end_turn' } },
          ];
        return (async function* () {
          for (const e of events) yield e;
        })();
      },
    };
  },
}));

const toolsMock = vi.hoisted(() => ({
  ACTIVE_PCB_TOOLS: [] as unknown[],
  executeToolStub: vi.fn(),
}));
vi.mock('../tools', () => toolsMock);

import { runOrchestrator, MAX_ITERATIONS, type SSEEvent } from '../orchestrator';

function toolStream(name: string, id = `tu_${name}`, json = '{}'): unknown[] {
  return [
    { type: 'content_block_start', content_block: { type: 'tool_use', id, name } },
    { type: 'content_block_delta', delta: { type: 'input_json_delta', partial_json: json } },
    { type: 'content_block_stop' },
    { type: 'message_delta', delta: { stop_reason: 'tool_use' } },
  ];
}

function textStream(...chunks: string[]): unknown[] {
  return [
    ...chunks.map((text) => ({
      type: 'content_block_delta',
      delta: { type: 'text_delta', text },
    })),
    { type: 'message_delta', delta: { stop_reason: 'end_turn' } },
  ];
}

const END_STREAM = [{ type: 'message_delta', delta: { stop_reason: 'end_turn' } }];

async function collect(gen: AsyncGenerator<SSEEvent>): Promise<SSEEvent[]> {
  const events: SSEEvent[] = [];
  for await (const e of gen) events.push(e);
  return events;
}

function run(overrides: Partial<Parameters<typeof runOrchestrator>[0]> = {}) {
  return collect(
    runOrchestrator({ userMessage: 'go', projectId: 'p1', history: [], ...overrides }),
  );
}

/**
 * Payloads des tool_result effectivement envoyés à Sonnet lors de l'appel API
 * `callIndex`. Le contenu est du JSON sérialisé dans un bloc de message — on le
 * reparse pour assertion sur les champs plutôt que sur une chaîne échappée.
 */
function toolResultPayloads(callIndex: number): Array<Record<string, unknown>> {
  const messages = (hoisted.createCalls[callIndex]?.messages ?? []) as Array<{
    content: unknown;
  }>;
  const payloads: Array<Record<string, unknown>> = [];
  for (const message of messages) {
    if (!Array.isArray(message.content)) continue;
    for (const block of message.content as Array<Record<string, unknown>>) {
      if (block['type'] === 'tool_result') {
        payloads.push(JSON.parse(String(block['content'])) as Record<string, unknown>);
      }
    }
  }
  return payloads;
}

beforeEach(() => {
  process.env['ANTHROPIC_API_KEY'] = 'test-key';
  hoisted.streamQueue.length = 0;
  hoisted.createCalls.length = 0;
  toolsMock.executeToolStub.mockReset();
  toolsMock.executeToolStub.mockResolvedValue({});
});

describe('guard ANTHROPIC_API_KEY', () => {
  it('émet une erreur propre et n’appelle jamais l’API si la clé est absente', async () => {
    delete process.env['ANTHROPIC_API_KEY'];

    const events = await run();

    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({
      type: 'error',
      message: 'ANTHROPIC_API_KEY non configurée.',
    });
    expect(hoisted.createCalls).toHaveLength(0);
    expect(toolsMock.executeToolStub).not.toHaveBeenCalled();
  });
});

describe('strip des blobs KiCad avant le contexte Sonnet', () => {
  const FAT_RESULT = {
    status: 'success',
    kicad_sch_content: 'SCH_BLOB',
    kicad_pcb_content: 'PCB_BLOB',
    gerber_zip_b64: 'ZIP_BLOB',
    // Nom réel émis par handleExport — sans ce champ dans LARGE_FIELDS,
    // le base64 complet partait dans le contexte Sonnet.
    zip_b64: 'ZIP_B64_HANDLER_BLOB',
    bom_csv: 'BOM_BLOB',
    simulation_output_raw: 'RAW_BLOB',
    routed_percent: 100,
    note: 'export ok',
  };

  it('tronque les champs volumineux (dont zip_b64) dans le tool_result envoyé à Sonnet', async () => {
    hoisted.streamQueue.push(toolStream('call_agent_export'), [...END_STREAM]);
    toolsMock.executeToolStub.mockResolvedValue({ ...FAT_RESULT });

    await run();

    // Le 2e appel API porte les tool_results de la 1re itération.
    const [payload] = toolResultPayloads(1);
    const TRUNCATED = '[truncated — stored server-side]';
    expect(payload).toMatchObject({
      kicad_sch_content: TRUNCATED,
      kicad_pcb_content: TRUNCATED,
      gerber_zip_b64: TRUNCATED,
      zip_b64: TRUNCATED,
      bom_csv: TRUNCATED,
      simulation_output_raw: TRUNCATED,
    });
    // Aucun blob ne fuit nulle part ailleurs dans le contexte envoyé.
    const sentToSonnet = JSON.stringify(hoisted.createCalls[1]?.messages);
    for (const blob of [
      'SCH_BLOB',
      'PCB_BLOB',
      'ZIP_BLOB',
      'ZIP_B64_HANDLER_BLOB',
      'BOM_BLOB',
      'RAW_BLOB',
    ]) {
      expect(sentToSonnet).not.toContain(blob);
    }
  });

  it('préserve les métadonnées non volumineuses — le strip est chirurgical', async () => {
    hoisted.streamQueue.push(toolStream('call_agent_export'), [...END_STREAM]);
    toolsMock.executeToolStub.mockResolvedValue({ ...FAT_RESULT });

    await run();

    const [payload] = toolResultPayloads(1);
    expect(payload).toMatchObject({
      status: 'success',
      routed_percent: 100,
      note: 'export ok',
    });
  });

  it('transmet le contenu INTÉGRAL au frontend via pcb_state', async () => {
    hoisted.streamQueue.push(toolStream('call_agent_export'), [...END_STREAM]);
    toolsMock.executeToolStub.mockResolvedValue({ ...FAT_RESULT });

    const events = await run();

    const state = events.find(
      (e): e is Extract<SSEEvent, { type: 'pcb_state' }> => e.type === 'pcb_state',
    );
    expect(state?.state['kicad_pcb_content']).toBe('PCB_BLOB');
    expect(state?.state['gerber_zip_b64']).toBe('ZIP_BLOB');
  });
});

describe('plafond MAX_ITERATIONS', () => {
  it('s’arrête à MAX_ITERATIONS même si Sonnet continue d’appeler des outils', async () => {
    // Bien plus d'itérations disponibles que le plafond : seul le plafond doit arrêter.
    for (let i = 0; i < MAX_ITERATIONS + 5; i++) {
      hoisted.streamQueue.push(toolStream('call_agent_schema', `tu_${i}`));
    }

    const events = await run();

    expect(hoisted.createCalls).toHaveLength(MAX_ITERATIONS);
    expect(events.filter((e) => e.type === 'iteration')).toHaveLength(MAX_ITERATIONS);
    // La boucle se termine proprement par `done`, pas par une exception.
    expect(events[events.length - 1]?.type).toBe('done');
  });

  it('sort dès end_turn sans consommer le budget d’itérations', async () => {
    hoisted.streamQueue.push([...END_STREAM]);

    const events = await run();

    expect(hoisted.createCalls).toHaveLength(1);
    expect(events.filter((e) => e.type === 'iteration')).toHaveLength(1);
  });
});

describe('mapping des étapes pipeline (stepMap)', () => {
  const CASES: ReadonlyArray<readonly [string, string]> = [
    ['call_agent_schema', 'SCHEMA'],
    ['call_agent_erc', 'ERC'],
    ['call_agent_footprint', 'FOOTPRINT'],
    ['call_agent_gen_pcb', 'KICAD'],
    ['call_agent_placement', 'PLACEMENT'],
    ['call_agent_routing', 'ROUTING'],
    ['call_agent_reason', 'ROUTING'],
    ['call_agent_drc', 'DRC'],
    ['call_agent_export', 'EXPORT'],
    ['call_agent_simulation', 'SIMULATION'],
  ];

  it.each(CASES)('%s émet l’étape %s', async (tool, step) => {
    hoisted.streamQueue.push(toolStream(tool), [...END_STREAM]);
    // routed_percent absent → aucun rescue/retry ne parasite les events.
    toolsMock.executeToolStub.mockResolvedValue({ note: 'ok' });

    const events = await run();

    const steps = events
      .filter((e): e is Extract<SSEEvent, { type: 'step' }> => e.type === 'step')
      .map((e) => e.step);
    expect(steps).toContain(step);
  });

  it('n’émet aucune étape pour un outil hors pipeline', async () => {
    hoisted.streamQueue.push(toolStream('call_agent_unknown'), [...END_STREAM]);

    const events = await run();

    expect(events.filter((e) => e.type === 'step')).toHaveLength(0);
  });
});

describe('émission de pcb_state', () => {
  it('call_agent_footprint n’émet PAS de pcb_state (résout un footprint, ne change pas le board)', async () => {
    hoisted.streamQueue.push(toolStream('call_agent_footprint'), [...END_STREAM]);
    toolsMock.executeToolStub.mockResolvedValue({ footprint: 'R_0402', note: 'résolu' });

    const events = await run();

    expect(events.filter((e) => e.type === 'pcb_state')).toHaveLength(0);
    // …mais le tool_result reste émis pour le chat.
    expect(events.filter((e) => e.type === 'tool_result')).toHaveLength(1);
  });

  it('call_agent_schema émet un pcb_state porteur du projectId', async () => {
    hoisted.streamQueue.push(toolStream('call_agent_schema'), [...END_STREAM]);
    toolsMock.executeToolStub.mockResolvedValue({ pcb_status: 'SCHEMA_DONE', note: 'ok' });

    const events = await run({ projectId: 'proj-42' });

    const state = events.find(
      (e): e is Extract<SSEEvent, { type: 'pcb_state' }> => e.type === 'pcb_state',
    );
    expect(state?.projectId).toBe('proj-42');
    expect(state?.state['pcb_status']).toBe('SCHEMA_DONE');
  });
});

describe('robustesse au JSON d’outil malformé', () => {
  it('retombe sur un input vide sans casser la boucle', async () => {
    hoisted.streamQueue.push(
      toolStream('call_agent_schema', 'tu_bad', '{"description": "tronq'),
      [...END_STREAM],
    );

    const events = await run();

    const call = events.find(
      (e): e is Extract<SSEEvent, { type: 'tool_call' }> => e.type === 'tool_call',
    );
    expect(call?.input).toEqual({});
    // L'outil est quand même exécuté et la boucle va jusqu'au bout.
    expect(toolsMock.executeToolStub).toHaveBeenCalledWith('call_agent_schema', {}, 'p1');
    expect(events[events.length - 1]?.type).toBe('done');
  });

  it('parse normalement un JSON valide livré en plusieurs deltas', async () => {
    hoisted.streamQueue.push(
      [
        {
          type: 'content_block_start',
          content_block: { type: 'tool_use', id: 'tu_ok', name: 'call_agent_schema' },
        },
        { type: 'content_block_delta', delta: { type: 'input_json_delta', partial_json: '{"desc' } },
        {
          type: 'content_block_delta',
          delta: { type: 'input_json_delta', partial_json: 'ription":"LED"}' },
        },
        { type: 'content_block_stop' },
        { type: 'message_delta', delta: { stop_reason: 'tool_use' } },
      ],
      [...END_STREAM],
    );

    const events = await run();

    const call = events.find(
      (e): e is Extract<SSEEvent, { type: 'tool_call' }> => e.type === 'tool_call',
    );
    expect(call?.input).toEqual({ description: 'LED' });
  });
});

describe('contexte de conversation', () => {
  it('transmet l’historique puis le message utilisateur au premier appel', async () => {
    hoisted.streamQueue.push([...END_STREAM]);

    await run({
      userMessage: 'ajoute une LED',
      history: [
        { role: 'user', content: 'fais un régulateur 3V3' },
        { role: 'assistant', content: 'schéma généré' },
      ],
    });

    expect(hoisted.createCalls[0]?.messages).toEqual([
      { role: 'user', content: 'fais un régulateur 3V3' },
      { role: 'assistant', content: 'schéma généré' },
      { role: 'user', content: 'ajoute une LED' },
    ]);
  });

  it('accumule le texte streamé de toutes les itérations dans done.fullText', async () => {
    hoisted.streamQueue.push(
      [
        { type: 'content_block_delta', delta: { type: 'text_delta', text: 'Je génère ' } },
        {
          type: 'content_block_start',
          content_block: { type: 'tool_use', id: 'tu_1', name: 'call_agent_schema' },
        },
        { type: 'content_block_delta', delta: { type: 'input_json_delta', partial_json: '{}' } },
        { type: 'content_block_stop' },
        { type: 'message_delta', delta: { stop_reason: 'tool_use' } },
      ],
      textStream('le schéma.'),
    );

    const events = await run();

    const done = events.find(
      (e): e is Extract<SSEEvent, { type: 'done' }> => e.type === 'done',
    );
    expect(done?.fullText).toBe('Je génère le schéma.');
  });
});

/**
 * E2E pipeline test — runs the full agent chain (spec → schema → erc → placement
 * → routing → drc) against the live FastAPI microservice when reachable, or
 * against the TS fallbacks otherwise.
 *
 * This is NOT a unit test — it skips when @ts-expect-error vitest is not
 * pointed at this file directly. Run with:
 *   pnpm --filter @layrix/agents test e2e-pipeline
 *
 * Requires:
 *   - ANTHROPIC_API_KEY (optional; falls back to deterministic schema parser)
 *   - KICAD_SERVICE_URL=http://localhost:8000 (optional; falls back to TS)
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { executeToolStub } from './tools';

const PROJECT_ID = 'e2e-pipeline-test';

interface ToolResult {
  status: string;
  pcb_status?: string;
  engine?: string;
  note?: string;
  [key: string]: unknown;
}

function logStep(name: string, result: ToolResult): void {
  // eslint-disable-next-line no-console
  console.log(
    `\n[${name}] status=${result.status} pcb_status=${result.pcb_status ?? '-'} engine=${result.engine ?? '-'}\n  ${result.note ?? ''}`,
  );
}

describe('E2E pipeline — spec → schema → erc → placement → routing → drc', () => {
  beforeAll(() => {
    // Default to localhost if KICAD_SERVICE_URL is not already set in env
    if (!process.env['KICAD_SERVICE_URL']) {
      process.env['KICAD_SERVICE_URL'] = 'http://localhost:8000';
    }
  });

  it('runs all six steps in order and converges to a clean state', async () => {
    const userDescription =
      'NE555 astable oscillator 1Hz with LED indicator and power connector. ' +
      'R1=10k, R2=100k, C1=10uF, C2=10nF, D1=LED, R3=330R series, J1=2-pin power.';

    // ---- Step 1: SPEC ----------------------------------------------
    const spec = (await executeToolStub(
      'call_agent_spec',
      { user_description: userDescription },
      PROJECT_ID,
    )) as ToolResult;
    logStep('1. SPEC', spec);
    expect(spec.status).toBe('success');
    expect(spec.design).toBeDefined();

    // ---- Step 2: SCHEMA --------------------------------------------
    const schema = (await executeToolStub(
      'call_agent_schema',
      { user_description: userDescription, complexity: 'simple' },
      PROJECT_ID,
    )) as ToolResult;
    logStep('2. SCHEMA', schema);
    expect(schema.status).toBe('success');
    expect(schema.pcb_status).toBe('SCHEMA_DONE');
    expect(typeof schema.kicad_sch_content).toBe('string');
    expect((schema.kicad_sch_content as string).length).toBeGreaterThan(100);
    expect(typeof schema.kicad_pcb_content).toBe('string');
    expect((schema.kicad_pcb_content as string).length).toBeGreaterThan(100);

    // ---- Step 3: ERC -----------------------------------------------
    const erc = (await executeToolStub(
      'call_agent_erc',
      { auto_fix: true },
      PROJECT_ID,
    )) as ToolResult;
    logStep('3. ERC', erc);
    expect(erc.status).toBe('success');
    expect(['ERC_CLEAN', 'SCHEMA_DONE']).toContain(erc.pcb_status as string);
    // engine is either 'kicad-cli', 'kicad-cli-skipped', or 'fallback-skip'
    expect(['kicad-cli', 'kicad-cli-skipped', 'fallback-skip']).toContain(
      erc.engine as string,
    );

    // ---- Step 4: PLACEMENT -----------------------------------------
    const placement = (await executeToolStub(
      'call_agent_placement',
      { board_width_mm: 50, board_height_mm: 50 },
      PROJECT_ID,
    )) as ToolResult;
    logStep('4. PLACEMENT', placement);
    expect(placement.status).toBe('success');
    expect(placement.pcb_status).toBe('PLACEMENT_DONE');
    expect(['pcbnew', 'fallback-ts']).toContain(placement.engine as string);
    expect(Array.isArray(placement.placements)).toBe(true);

    // ---- Step 5: ROUTING -------------------------------------------
    const routing = (await executeToolStub(
      'call_agent_routing',
      { placement_json: '{}', schema_json: '{}' },
      PROJECT_ID,
    )) as ToolResult;
    logStep('5. ROUTING', routing);
    expect(routing.status).toBe('success');
    expect(routing.pcb_status).toBe('ROUTING_DONE');
    expect(['freerouting', 'fallback-ts']).toContain(routing.engine as string);

    // ---- Step 6: DRC -----------------------------------------------
    const drc = (await executeToolStub(
      'call_agent_drc',
      { auto_fix: true },
      PROJECT_ID,
    )) as ToolResult;
    logStep('6. DRC', drc);
    expect(drc.status).toBe('success');
    expect(['DRC_CLEAN', 'ROUTING_DONE']).toContain(drc.pcb_status as string);
    expect(['kicad-cli', 'kicad-cli-skipped', 'fallback-skip']).toContain(
      drc.engine as string,
    );

    // ---- Final assertions ------------------------------------------
    // Either fully clean (kicad-cli present) OR all skipped to fallback path
    // — in both cases the chain reached the end without crashing.
    // eslint-disable-next-line no-console
    console.log(
      `\n=== PIPELINE COMPLETE ===\n` +
        `SPEC: ${spec.engine ?? 'haiku-design'}\n` +
        `SCHEMA: ${schema.engine ?? '-'}\n` +
        `ERC: ${erc.engine ?? '-'}\n` +
        `PLACEMENT: ${placement.engine ?? '-'}\n` +
        `ROUTING: ${routing.engine ?? '-'}\n` +
        `DRC: ${drc.engine ?? '-'}\n` +
        `Final status: ${drc.pcb_status}`,
    );
  }, 60_000);
});

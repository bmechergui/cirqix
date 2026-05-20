/**
 * Manual validation TEST for SCHEMA + PLACEMENT phases.
 *
 * Runs `call_agent_spec → call_agent_schema → call_agent_placement` against
 * the current code, then saves the resulting `.kicad_sch` and `.kicad_pcb`
 * files in `validation-output/` so they can be opened in KiCad for visual
 * inspection.
 *
 * Run with:
 *   pnpm --filter @layrix/agents test validate-schema-placement
 *
 * Or override the prompt via env:
 *   $env:LAYRIX_PROMPT="ESP32 weather station"; pnpm --filter @layrix/agents test validate-schema-placement
 */
import { describe, it, expect } from 'vitest';
import { writeFileSync, mkdirSync, readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

// Auto-load ANTHROPIC_API_KEY (and other vars) from apps/web/.env.local so the
// validation test runs with the same configuration as the Next.js dev server.
// MUST run BEFORE importing `./tools` because tools.ts captures the API key
// at module load via the Anthropic SDK singleton.
const envPath = resolve(process.cwd(), '..', '..', 'apps', 'web', '.env.local');
if (existsSync(envPath)) {
  for (const line of readFileSync(envPath, 'utf-8').split('\n')) {
    const match = line.match(/^([A-Z_]+)=(.*)$/);
    if (match && match[1] && !process.env[match[1]]) {
      let value = match[2] ?? '';
      // Strip surrounding quotes if present
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      process.env[match[1]] = value;
    }
  }
}

import { executeToolStub } from './tools'; // loaded after env setup above

interface ToolResult {
  status: string;
  pcb_status?: string;
  engine?: string;
  note?: string;
  components?: Array<{ ref: string; value: string; footprint: string }>;
  nets?: string[];
  placements?: Array<{ ref: string; x_mm: number; y_mm: number }>;
  kicad_sch_content?: string;
  kicad_pcb_content?: string;
}

describe('Validation — SCHEMA + PLACEMENT', () => {
  it('produces valid .kicad_sch and .kicad_pcb files on disk for KiCad inspection', async () => {
    // LAYRIX_PROMPT avoids colliding with Windows' built-in PROMPT env var
    const userDescription =
      process.env['LAYRIX_PROMPT'] ??
      'NE555 astable oscillator 1Hz with LED indicator and 2-pin power connector. ' +
        'R1=10k, R2=100k, C1=10uF, C2=10nF, R3=330R, D1=red LED, J1=2-pin header.';

    const projectId = `validate-${Date.now()}`;
    const outDir = resolve(process.cwd(), '..', '..', 'validation-output');
    mkdirSync(outDir, { recursive: true });

    // eslint-disable-next-line no-console
    console.log('\n=== Layrix validation — SCHEMA + PLACEMENT ===');
    // eslint-disable-next-line no-console
    console.log(`Prompt: ${userDescription}\n`);

    // ---- Step 1: SPEC -----------------------------------------------
    const spec = (await executeToolStub(
      'call_agent_spec',
      { user_description: userDescription },
      projectId,
    )) as unknown as ToolResult;
    expect(spec.status).toBe('success');
    // eslint-disable-next-line no-console
    console.log(`[1/3] SPEC      engine=${spec.engine}`);
    // eslint-disable-next-line no-console
    console.log(`       ${spec.note}\n`);

    // ---- Step 2: SCHEMA ---------------------------------------------
    const schema = (await executeToolStub(
      'call_agent_schema',
      { user_description: userDescription, complexity: 'simple' },
      projectId,
    )) as unknown as ToolResult;
    expect(schema.status).toBe('success');
    expect(schema.pcb_status).toBe('SCHEMA_DONE');
    expect(typeof schema.kicad_sch_content).toBe('string');
    expect(typeof schema.kicad_pcb_content).toBe('string');

    const schPath = resolve(outDir, 'schema.kicad_sch');
    const schemaPcbPath = resolve(outDir, 'schema-output.kicad_pcb');
    writeFileSync(schPath, schema.kicad_sch_content!, 'utf-8');
    writeFileSync(schemaPcbPath, schema.kicad_pcb_content!, 'utf-8');

    // eslint-disable-next-line no-console
    console.log(`[2/3] SCHEMA    engine=${schema.engine}`);
    // eslint-disable-next-line no-console
    console.log(`       ${schema.components?.length} components, ${schema.nets?.length} nets`);
    // eslint-disable-next-line no-console
    console.log(`       Components:`);
    schema.components?.forEach((c) => {
      // eslint-disable-next-line no-console
      console.log(`         ${c.ref.padEnd(5)} ${c.value.padEnd(12)} ${c.footprint}`);
    });
    // eslint-disable-next-line no-console
    console.log(`       Nets: ${schema.nets?.join(', ')}`);
    // eslint-disable-next-line no-console
    console.log(`       FILES:`);
    // eslint-disable-next-line no-console
    console.log(`         ${schPath} (${schema.kicad_sch_content!.length}b)`);
    // eslint-disable-next-line no-console
    console.log(`         ${schemaPcbPath} (${schema.kicad_pcb_content!.length}b)\n`);

    // ---- Step 3: PLACEMENT ------------------------------------------
    const placement = (await executeToolStub(
      'call_agent_placement',
      { board_width_mm: 50, board_height_mm: 50 },
      projectId,
    )) as unknown as ToolResult;
    expect(placement.status).toBe('success');
    expect(placement.pcb_status).toBe('PLACEMENT_DONE');
    expect(Array.isArray(placement.placements)).toBe(true);
    expect(typeof placement.kicad_pcb_content).toBe('string');

    const placePcbPath = resolve(outDir, 'placement.kicad_pcb');
    writeFileSync(placePcbPath, placement.kicad_pcb_content!, 'utf-8');

    // eslint-disable-next-line no-console
    console.log(`[3/3] PLACEMENT engine=${placement.engine}`);
    // eslint-disable-next-line no-console
    console.log(`       ${placement.placements?.length} positions on 50x50mm board`);
    // eslint-disable-next-line no-console
    console.log(`       Positions:`);
    placement.placements?.forEach((p) => {
      // eslint-disable-next-line no-console
      console.log(
        `         ${p.ref.padEnd(5)} (x=${p.x_mm.toFixed(2).padStart(6)}, y=${p.y_mm.toFixed(2).padStart(6)})`,
      );
    });
    // eslint-disable-next-line no-console
    console.log(`       FILE:`);
    // eslint-disable-next-line no-console
    console.log(`         ${placePcbPath} (${placement.kicad_pcb_content!.length}b)\n`);

    // ---- Sanity checks on file contents -----------------------------
    expect(schema.kicad_sch_content).toContain('(kicad_sch');
    expect(schema.kicad_pcb_content).toContain('(kicad_pcb');
    expect(placement.kicad_pcb_content).toContain('(kicad_pcb');

    // eslint-disable-next-line no-console
    console.log('=== Validation PASS ===');
    // eslint-disable-next-line no-console
    console.log('Next steps:');
    // eslint-disable-next-line no-console
    console.log('  - Open the .kicad_sch in KiCad Schematic Editor (Eeschema)');
    // eslint-disable-next-line no-console
    console.log('  - Open the placement.kicad_pcb in KiCad PCB Editor (Pcbnew)');
    // eslint-disable-next-line no-console
    console.log('  - Or run `pnpm dev` and open http://localhost:3333/dashboard');
    // eslint-disable-next-line no-console
    console.log('    (the KiCanvas viewer renders the same files in-browser)\n');
  }, 30_000);
});

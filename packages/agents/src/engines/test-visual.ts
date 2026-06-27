/**
 * Visual test script — generates .kicad_sch + .kicad_pcb via inline engine (no API needed)
 * and writes a self-contained HTML file that loads KiCanvas for inspection.
 *
 * Usage:
 *   pnpm --filter @cirqix/agents exec tsx src/engines/test-visual.ts
 *   Then open http://localhost:3333/test-kicad.html in Chrome
 */

import { runCircuitSynthEngine } from './schematic-engine.js';
import type { SchemaJson } from './schematic-engine.js';
import { writeFileSync } from 'fs';
import { resolve } from 'path';

// --- NE555 1Hz blinker — realistic netlist ---
const NE555_SCHEMA: SchemaJson = {
  components: [
    { ref: 'J1',   value: 'PWR_5V',  footprint: '2PIN',   lcsc: 'C5188' },
    { ref: 'U1',   value: 'NE555P',  footprint: 'DIP-8',  lcsc: 'C46555' },
    { ref: 'R1',   value: '4.7k',    footprint: '0603' },
    { ref: 'R2',   value: '68k',     footprint: '0603' },
    { ref: 'R3',   value: '330R',    footprint: '0603' },
    { ref: 'C1',   value: '10uF',    footprint: '1206' },
    { ref: 'C2',   value: '10nF',    footprint: '0603' },
    { ref: 'C3',   value: '100nF',   footprint: '0603' },
    { ref: 'LED1', value: 'RED_LED', footprint: 'LED' },
  ],
  nets: ['GND', 'VCC', 'OUT', 'THR_DIS', 'CV'],
  connections: [
    // GND: J1-pin2, U1-pin1(GND), C1-pin2, C2-pin2, C3-pin2
    { name: 'GND',     pins: [{ ref: 'J1', pin: 2 }, { ref: 'U1', pin: 1 }, { ref: 'C1', pin: 2 }, { ref: 'C2', pin: 2 }, { ref: 'C3', pin: 2 }] },
    // VCC: J1-pin1, U1-pin8(VCC), U1-pin4(RST), R1-pin1, C3-pin1
    { name: 'VCC',     pins: [{ ref: 'J1', pin: 1 }, { ref: 'U1', pin: 8 }, { ref: 'U1', pin: 4 }, { ref: 'R1', pin: 1 }, { ref: 'C3', pin: 1 }] },
    // OUT: U1-pin3(OUT) → R3-pin1
    { name: 'OUT',     pins: [{ ref: 'U1', pin: 3 }, { ref: 'R3', pin: 1 }, { ref: 'LED1', pin: 1 }] },
    // THR_DIS: R1-pin2 + R2-pin1, U1-pin2(TRIG), U1-pin6(THR), U1-pin7(DIS), C1-pin1, R2-pin2
    { name: 'THR_DIS', pins: [{ ref: 'R1', pin: 2 }, { ref: 'R2', pin: 1 }, { ref: 'U1', pin: 2 }, { ref: 'U1', pin: 6 }, { ref: 'U1', pin: 7 }, { ref: 'C1', pin: 1 }, { ref: 'R2', pin: 2 }] },
    // CV: U1-pin5 + C2-pin1
    { name: 'CV',      pins: [{ ref: 'U1', pin: 5 }, { ref: 'C2', pin: 1 }] },
    // LED cathode → R3-pin2 → GND via LED1-pin2
    { name: 'GND',     pins: [{ ref: 'LED1', pin: 2 }, { ref: 'R3', pin: 2 }] },
  ],
};

// Escape for embedding in HTML (prefixed _ = intentionally unused in current template)
function _esc(s: string): string {
  return s.replace(/`/g, '\\`').replace(/\$/g, '\\$');
}

async function main(): Promise<void> {
const result = await runCircuitSynthEngine(NE555_SCHEMA, 60, 50);

const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Cirqix — Circuit-Synth Visual Test</title>
  <script type="module" src="/kicanvas.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #0A0A0A; color: #ccc; font-family: monospace; display: flex; flex-direction: column; height: 100vh; }
    h1 { padding: 8px 16px; font-size: 13px; color: #D4820A; border-bottom: 1px solid #222; }
    .tabs { display: flex; gap: 4px; padding: 6px 16px; background: #111; border-bottom: 1px solid #222; }
    .tab { padding: 4px 12px; cursor: pointer; border: 1px solid #333; border-radius: 4px; font-size: 11px; color: #888; }
    .tab.active { border-color: #D4820A; color: #D4820A; }
    .viewer { flex: 1; display: flex; }
    kicanvas-embed { width: 100%; height: 100%; }
  </style>
</head>
<body>
  <h1>Circuit-Synth Visual Test — NE555 1Hz Blinker — no API</h1>
  <div class="tabs">
    <button class="tab active" onclick="show('sch')">Schematic (.kicad_sch)</button>
    <button class="tab" onclick="show('pcb')">PCB Routing (.kicad_pcb)</button>
  </div>
  <div class="viewer">
    <kicanvas-embed id="kv" src="/test-ne555.kicad_sch" controls="full" theme="dark"></kicanvas-embed>
  </div>
  <script>
    const kv = document.getElementById('kv');
    const tabs = document.querySelectorAll('.tab');

    function show(type) {
      tabs.forEach((t, i) => t.classList.toggle('active', (i === 0 && type === 'sch') || (i === 1 && type === 'pcb')));
      // Force reload by removing and re-adding the element
      const parent = kv.parentNode;
      const clone = kv.cloneNode(false);
      clone.setAttribute('src', type === 'sch' ? '/test-ne555.kicad_sch' : '/test-ne555.kicad_pcb');
      parent.replaceChild(clone, kv);
    }
  </script>
</body>
</html>`;

const pubDir = resolve('../../apps/web/public');
writeFileSync(`${pubDir}/test-kicad.html`, html, 'utf-8');
writeFileSync(`${pubDir}/test-ne555.kicad_sch`, result.kicad_sch_content, 'utf-8');
writeFileSync(`${pubDir}/test-ne555.kicad_pcb`, result.kicad_pcb_content, 'utf-8');
process.stdout.write(`✅  Written: test-kicad.html + test-ne555.kicad_sch + test-ne555.kicad_pcb\n`);
process.stdout.write(`🌐  Open: http://localhost:3333/test-kicad.html\n`);
process.stdout.write(`\n📊  Stats:\n`);
process.stdout.write(`    .kicad_sch  ${result.kicad_sch_content.length} chars\n`);
process.stdout.write(`    .kicad_pcb  ${result.kicad_pcb_content.length} chars\n`);
}

main().catch(console.error);

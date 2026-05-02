/**
 * Visual test — generates 3 .kicad_sch fixtures via the TS engine (no API, no FastAPI).
 * Uses the inline TS S-expression generator which ships with lib_symbols embedded,
 * so KiCanvas can render them without external symbol libraries.
 *
 * Usage:
 *   pnpm --filter @layrix/agents exec tsx src/engines/test-visual.mts
 */

import { writeFileSync } from 'fs';
import { resolve } from 'path';
import { runCircuitSynthEngine } from './circuit-synth-engine.js';
import type { SchemaJson } from './circuit-synth-engine.js';

// Force the TS inline path (skip FastAPI)
delete process.env.KICAD_SERVICE_URL;

// ---------- Fixture 1 — LM7805 5V regulator ----------
const LM7805: SchemaJson = {
  components: [
    { ref: 'J1', value: 'VIN',    footprint: '2PIN' },
    { ref: 'U1', value: 'LM7805', footprint: 'TO-220-3' },
    { ref: 'C1', value: '330nF',  footprint: '0805' },
    { ref: 'C2', value: '100nF',  footprint: '0805' },
    { ref: 'J2', value: 'VOUT',   footprint: '2PIN' },
  ],
  nets: ['VIN', 'GND', 'VOUT'],
  connections: [
    { name: 'VIN',  pins: [{ ref: 'J1', pin: 1 }, { ref: 'U1', pin: 1 }, { ref: 'C1', pin: 1 }] },
    { name: 'GND',  pins: [{ ref: 'J1', pin: 2 }, { ref: 'U1', pin: 2 }, { ref: 'C1', pin: 2 }, { ref: 'C2', pin: 2 }, { ref: 'J2', pin: 2 }] },
    { name: 'VOUT', pins: [{ ref: 'U1', pin: 3 }, { ref: 'C2', pin: 1 }, { ref: 'J2', pin: 1 }] },
  ],
};

// ---------- Fixture 2 — NE555 1Hz blinker ----------
const NE555: SchemaJson = {
  components: [
    { ref: 'J1',   value: 'PWR_5V',  footprint: '2PIN' },
    { ref: 'U1',   value: 'NE555P',  footprint: 'DIP-8' },
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
    { name: 'GND', pins: [{ ref: 'J1', pin: 2 }, { ref: 'U1', pin: 1 }, { ref: 'C1', pin: 2 }, { ref: 'C2', pin: 2 }, { ref: 'C3', pin: 2 }, { ref: 'LED1', pin: 2 }] },
    { name: 'VCC', pins: [{ ref: 'J1', pin: 1 }, { ref: 'U1', pin: 8 }, { ref: 'U1', pin: 4 }, { ref: 'R1', pin: 1 }, { ref: 'C3', pin: 1 }] },
    { name: 'OUT', pins: [{ ref: 'U1', pin: 3 }, { ref: 'R3', pin: 1 }] },
    { name: 'LED_A', pins: [{ ref: 'R3', pin: 2 }, { ref: 'LED1', pin: 1 }] },
    { name: 'THR_DIS', pins: [{ ref: 'R1', pin: 2 }, { ref: 'R2', pin: 1 }, { ref: 'U1', pin: 2 }, { ref: 'U1', pin: 6 }, { ref: 'U1', pin: 7 }, { ref: 'C1', pin: 1 }] },
    { name: 'CV',  pins: [{ ref: 'U1', pin: 5 }, { ref: 'C2', pin: 1 }] },
  ],
};

// ---------- Fixture 3 — ESP32 + LED blinker ----------
const ESP32: SchemaJson = {
  components: [
    { ref: 'J1',   value: 'USB_5V',    footprint: '2PIN' },
    { ref: 'U2',   value: 'AMS1117',   footprint: 'SOT-223' },
    { ref: 'C1',   value: '10uF',      footprint: '0805' },
    { ref: 'C2',   value: '10uF',      footprint: '0805' },
    { ref: 'U1',   value: 'ESP32',     footprint: 'DIP-8' },
    { ref: 'R1',   value: '330R',      footprint: '0603' },
    { ref: 'LED1', value: 'LED_GREEN', footprint: 'LED' },
  ],
  nets: ['VBUS', 'VCC_3V3', 'GND', 'GPIO2'],
  connections: [
    { name: 'VBUS',    pins: [{ ref: 'J1', pin: 1 }, { ref: 'U2', pin: 1 }, { ref: 'C1', pin: 1 }] },
    { name: 'VCC_3V3', pins: [{ ref: 'U2', pin: 3 }, { ref: 'C2', pin: 1 }, { ref: 'U1', pin: 1 }] },
    { name: 'GND',     pins: [{ ref: 'J1', pin: 2 }, { ref: 'U2', pin: 2 }, { ref: 'C1', pin: 2 }, { ref: 'C2', pin: 2 }, { ref: 'U1', pin: 8 }, { ref: 'LED1', pin: 2 }] },
    { name: 'GPIO2',   pins: [{ ref: 'U1', pin: 2 }, { ref: 'R1', pin: 1 }] },
    { name: 'LED_A',   pins: [{ ref: 'R1', pin: 2 }, { ref: 'LED1', pin: 1 }] },
  ],
};

const FIXTURES: Array<{ name: string; schema: SchemaJson; w: number; h: number }> = [
  { name: 'test-lm7805', schema: LM7805, w: 60, h: 50 },
  { name: 'test-ne555',  schema: NE555,  w: 60, h: 50 },
  { name: 'test-esp32',  schema: ESP32,  w: 60, h: 50 },
];

const PUBLIC_DIR = resolve('../../apps/web/public');

for (const f of FIXTURES) {
  const r = await runCircuitSynthEngine(f.schema, f.w, f.h);
  const schPath = resolve(PUBLIC_DIR, `${f.name}.kicad_sch`);
  writeFileSync(schPath, r.kicad_sch_content, 'utf-8');
  // eslint-disable-next-line no-console
  console.log(`OK  ${f.name}.kicad_sch  ${r.kicad_sch_content.length} bytes`);
}

// eslint-disable-next-line no-console
console.log(`\nOpen: http://localhost:3333/test-cs.html`);

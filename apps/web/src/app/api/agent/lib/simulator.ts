import type { SupabaseClient } from '@supabase/supabase-js';
import type { PCBState, SchemaComponent, SchemaNet } from '@cirqix/types';
import { encodeSse } from './sse';
import { finalizePipelineSuccess } from './credits';
import type { RunSink } from '@cirqix/agents';

interface SimulatedSchema {
  components: SchemaComponent[];
  nets: string[];
  connections: SchemaNet[];
  board_width_mm: number;
  board_height_mm: number;
}

function deriveSchemaFromPrompt(prompt: string): SimulatedSchema {
  const lower = prompt.toLowerCase();
  if (lower.includes('555') || lower.includes('blinker') || lower.includes('timer')) {
    return {
      components: [
        { ref: 'U1', value: 'NE555P', footprint: 'DIP-8', symbol: 'Timer:NE555P' },
        { ref: 'R1', value: '10k', footprint: '0603', symbol: 'Device:R' },
        { ref: 'R2', value: '100k', footprint: '0603', symbol: 'Device:R' },
        { ref: 'C1', value: '10uF', footprint: '0805', symbol: 'Device:CP' },
        { ref: 'C2', value: '10nF', footprint: '0603', symbol: 'Device:C' },
        { ref: 'D1', value: 'LED', footprint: 'LED-0805', symbol: 'Device:LED' },
        { ref: 'R3', value: '330', footprint: '0603', symbol: 'Device:R' },
        { ref: 'J1', value: 'VIN', footprint: 'PinHeader-2', symbol: 'Connector:Conn_01x02' },
      ],
      nets: ['VCC', 'GND', 'TR', 'TH', 'OUT', 'CTRL'],
      connections: [
        { name: 'VCC', pins: [{ ref: 'J1', pin: 1 }, { ref: 'U1', pin: 8 }, { ref: 'R2', pin: 1 }] },
        { name: 'GND', pins: [{ ref: 'J1', pin: 2 }, { ref: 'U1', pin: 1 }, { ref: 'C1', pin: 2 }, { ref: 'C2', pin: 2 }, { ref: 'D1', pin: 2 }] },
        { name: 'TR', pins: [{ ref: 'U1', pin: 2 }, { ref: 'U1', pin: 6 }, { ref: 'R1', pin: 2 }, { ref: 'C1', pin: 1 }] },
        { name: 'TH', pins: [{ ref: 'R1', pin: 1 }, { ref: 'R2', pin: 2 }] },
        { name: 'OUT', pins: [{ ref: 'U1', pin: 3 }, { ref: 'R3', pin: 1 }] },
        { name: 'CTRL', pins: [{ ref: 'U1', pin: 5 }, { ref: 'C2', pin: 1 }] },
      ],
      board_width_mm: 40,
      board_height_mm: 30,
    };
  }
  if (lower.includes('esp32') || lower.includes('weather') || lower.includes('iot')) {
    return {
      components: [
        { ref: 'U1', value: 'ESP32-S3', footprint: 'QFN-56', symbol: 'RF_Module:ESP32-S3-WROOM-1' },
        { ref: 'U2', value: 'BME280', footprint: 'LGA-8', symbol: 'Sensor:BME280' },
        { ref: 'U3', value: 'AMS1117', footprint: 'SOT-223', symbol: 'Regulator_Linear:AMS1117-3.3' },
        { ref: 'J1', value: 'USB-C', footprint: 'USB-C', symbol: 'Connector:USB_C_Receptacle' },
        { ref: 'C1', value: '10uF', footprint: '0805', symbol: 'Device:CP' },
        { ref: 'C2', value: '100nF', footprint: '0603', symbol: 'Device:C' },
        { ref: 'C3', value: '100nF', footprint: '0603', symbol: 'Device:C' },
        { ref: 'R1', value: '10k', footprint: '0603', symbol: 'Device:R' },
        { ref: 'R2', value: '5k1', footprint: '0603', symbol: 'Device:R' },
        { ref: 'R3', value: '5k1', footprint: '0603', symbol: 'Device:R' },
      ],
      nets: ['5V', '3V3', 'GND', 'USB_DP', 'USB_DM', 'I2C_SDA', 'I2C_SCL'],
      connections: [
        { name: '5V', pins: [{ ref: 'J1', pin: 'VBUS' }, { ref: 'U3', pin: 3 }, { ref: 'C1', pin: 1 }] },
        { name: '3V3', pins: [{ ref: 'U3', pin: 2 }, { ref: 'U1', pin: 'VDD' }, { ref: 'U2', pin: 1 }, { ref: 'C2', pin: 1 }, { ref: 'C3', pin: 1 }] },
        { name: 'GND', pins: [{ ref: 'J1', pin: 'GND' }, { ref: 'U3', pin: 1 }, { ref: 'U1', pin: 'GND' }, { ref: 'U2', pin: 4 }, { ref: 'C1', pin: 2 }, { ref: 'C2', pin: 2 }, { ref: 'C3', pin: 2 }] },
        { name: 'I2C_SDA', pins: [{ ref: 'U1', pin: 'IO8' }, { ref: 'U2', pin: 6 }, { ref: 'R2', pin: 1 }] },
        { name: 'I2C_SCL', pins: [{ ref: 'U1', pin: 'IO9' }, { ref: 'U2', pin: 5 }, { ref: 'R3', pin: 1 }] },
      ],
      board_width_mm: 60,
      board_height_mm: 40,
    };
  }
  return {
    components: [
      { ref: 'U1', value: 'LM7805', footprint: 'TO-220', symbol: 'Regulator_Linear:L7805' },
      { ref: 'J1', value: 'VIN', footprint: 'PinHeader-2', symbol: 'Connector:Conn_01x02' },
      { ref: 'J2', value: 'VOUT', footprint: 'PinHeader-2', symbol: 'Connector:Conn_01x02' },
      { ref: 'C1', value: '10uF', footprint: '0805', symbol: 'Device:CP' },
      { ref: 'C2', value: '100nF', footprint: '0603', symbol: 'Device:C' },
      { ref: 'C3', value: '10uF', footprint: '0805', symbol: 'Device:CP' },
      { ref: 'C4', value: '100nF', footprint: '0603', symbol: 'Device:C' },
      { ref: 'D1', value: 'LED', footprint: 'LED-0805', symbol: 'Device:LED' },
      { ref: 'R1', value: '1k', footprint: '0603', symbol: 'Device:R' },
    ],
    nets: ['VIN', 'VOUT', 'GND'],
    connections: [
      { name: 'VIN', pins: [{ ref: 'J1', pin: 1 }, { ref: 'U1', pin: 1 }, { ref: 'C1', pin: 1 }, { ref: 'C2', pin: 1 }] },
      { name: 'VOUT', pins: [{ ref: 'U1', pin: 3 }, { ref: 'J2', pin: 1 }, { ref: 'C3', pin: 1 }, { ref: 'C4', pin: 1 }, { ref: 'R1', pin: 1 }] },
      { name: 'GND', pins: [{ ref: 'J1', pin: 2 }, { ref: 'J2', pin: 2 }, { ref: 'U1', pin: 2 }, { ref: 'C1', pin: 2 }, { ref: 'C2', pin: 2 }, { ref: 'C3', pin: 2 }, { ref: 'C4', pin: 2 }, { ref: 'D1', pin: 2 }] },
    ],
    board_width_mm: 45,
    board_height_mm: 30,
  };
}

async function streamText(
  sink: RunSink,
  text: string,
  chunkSize = 6,
  delayMs = 18,
): Promise<void> {
  for (let i = 0; i < text.length; i += chunkSize) {
    const slice = text.slice(i, i + chunkSize);
    await sink.emit({ type: 'token', content: slice });
    if (delayMs > 0) await new Promise((r) => setTimeout(r, delayMs));
  }
}

function wait(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

interface SimulatorOptions {
  sink: RunSink;
  supabase: SupabaseClient;
  userId: string;
  projectId: string;
  prompt: string;
  iterationStart: number;
  balanceStart: number;
}

export async function runSimulatorAgent(opts: SimulatorOptions): Promise<void> {
  const { sink, supabase, userId, projectId, prompt, iterationStart } = opts;
  const schema = deriveSchemaFromPrompt(prompt);

  await streamText(sink,
    `I'll design that PCB step by step. Starting with the schematic — identifying components and nets…\n\n`,
  );

  await sink.emit({ type: 'step', step: 'SCHEMA' });
  await wait(400);
  const schemaState: PCBState = {
    projectId,
    status: 'SCHEMA_DONE',
    iteration: iterationStart + 1,
    components: schema.components,
    nets: schema.nets,
    connections: schema.connections,
    board_width_mm: schema.board_width_mm,
    board_height_mm: schema.board_height_mm,
  };
  await streamText(sink,
    `**Schematic ready** — ${schema.components.length} components · ${schema.nets.length} nets · ${schema.board_width_mm}×${schema.board_height_mm}mm board.\n\n`,
  );
  await sink.emit({ type: 'pcb_state', state: schemaState });
  await sink.emit({ type: 'status', status: 'SCHEMA_DONE' });
  await supabase
    .from('projects')
    .update({
      status: 'SCHEMA_DONE',
      pcb_state: schemaState,
      // Provenance : états FABRIQUÉS pour la démo. Le gate JLCPCB refuse ce
      // marquage — le simulateur atteint DRC_CLEAN sans qu'aucun DRC ne tourne.
      agent_mode: 'simulator',
      updated_at: new Date().toISOString(),
    })
    .eq('id', projectId);

  await wait(700);
  await sink.emit({ type: 'step', step: 'PLACEMENT' });
  await streamText(sink, `**Placing** ${schema.components.length} components…\n\n`);
  const placementState: PCBState = { ...schemaState, status: 'PLACEMENT_DONE' };
  await sink.emit({ type: 'pcb_state', state: placementState });
  await sink.emit({ type: 'status', status: 'PLACEMENT_DONE' });
  await supabase
    .from('projects')
    .update({ status: 'PLACEMENT_DONE', pcb_state: placementState, agent_mode: 'simulator', updated_at: new Date().toISOString() })
    .eq('id', projectId);

  await wait(800);
  await sink.emit({ type: 'step', step: 'ROUTING' });
  await streamText(sink, `**Routing** signal and power nets…\n\n`);
  const routingState: PCBState = { ...placementState, status: 'ROUTING_DONE' };
  await sink.emit({ type: 'pcb_state', state: routingState });
  await sink.emit({ type: 'status', status: 'ROUTING_DONE' });
  await supabase
    .from('projects')
    .update({ status: 'ROUTING_DONE', pcb_state: routingState, agent_mode: 'simulator', updated_at: new Date().toISOString() })
    .eq('id', projectId);

  await wait(600);
  await sink.emit({ type: 'step', step: 'DRC' });
  await streamText(sink,
    `**DRC clean** — 0 violations.\n\n`
      + `_Simulated run: this board was generated for demonstration and was never `
      + `validated by KiCad. Ordering is disabled for simulated boards — set `
      + `CIRQIX_AGENT_MODE=orchestrator to run the real pipeline._`,
  );
  const drcState: PCBState = { ...routingState, status: 'DRC_CLEAN', drcViolations: [] };
  await finalizePipelineSuccess(supabase, userId, projectId, drcState, 'simulator');
  await sink.emit({ type: 'pcb_state', state: drcState });
  await sink.emit({ type: 'status', status: 'DRC_CLEAN' });
  await sink.emit({ type: 'step', step: null });
  await sink.emit({ type: 'done' });
}

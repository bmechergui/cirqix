import type { SupabaseClient } from '@supabase/supabase-js';
import type { PCBState, SchemaComponent, SchemaNet } from '@cirqix/types';
import { encodeSse } from './sse';

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
  controller: ReadableStreamDefaultController<Uint8Array>,
  encoder: TextEncoder,
  text: string,
  chunkSize = 6,
  delayMs = 18,
): Promise<void> {
  for (let i = 0; i < text.length; i += chunkSize) {
    const slice = text.slice(i, i + chunkSize);
    controller.enqueue(encoder.encode(encodeSse({ type: 'token', content: slice })));
    if (delayMs > 0) await new Promise((r) => setTimeout(r, delayMs));
  }
}

function wait(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

interface SimulatorOptions {
  controller: ReadableStreamDefaultController<Uint8Array>;
  encoder: TextEncoder;
  supabase: SupabaseClient;
  userId: string;
  projectId: string;
  prompt: string;
  iterationStart: number;
  balanceStart: number;
}

export async function runSimulatorAgent(opts: SimulatorOptions): Promise<void> {
  const { controller, encoder, supabase, userId, projectId, prompt, iterationStart, balanceStart } = opts;
  const schema = deriveSchemaFromPrompt(prompt);

  await streamText(
    controller,
    encoder,
    `I'll design that PCB step by step. Starting with the schematic — identifying components and nets…\n\n`,
  );

  controller.enqueue(encoder.encode(encodeSse({ type: 'step', step: 'SCHEMA' })));
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
  await streamText(
    controller,
    encoder,
    `**Schematic ready** — ${schema.components.length} components · ${schema.nets.length} nets · ${schema.board_width_mm}×${schema.board_height_mm}mm board.\n\n`,
  );
  controller.enqueue(encoder.encode(encodeSse({ type: 'pcb_state', state: schemaState })));
  controller.enqueue(encoder.encode(encodeSse({ type: 'status', status: 'SCHEMA_DONE' })));
  await supabase
    .from('projects')
    .update({
      status: 'SCHEMA_DONE',
      pcb_state: schemaState,
      iteration_count: schemaState.iteration,
      updated_at: new Date().toISOString(),
    })
    .eq('id', projectId);

  await wait(700);
  controller.enqueue(encoder.encode(encodeSse({ type: 'step', step: 'PLACEMENT' })));
  await streamText(controller, encoder, `**Placing** ${schema.components.length} components…\n\n`);
  const placementState: PCBState = { ...schemaState, status: 'PLACEMENT_DONE' };
  controller.enqueue(encoder.encode(encodeSse({ type: 'pcb_state', state: placementState })));
  controller.enqueue(encoder.encode(encodeSse({ type: 'status', status: 'PLACEMENT_DONE' })));
  await supabase
    .from('projects')
    .update({ status: 'PLACEMENT_DONE', pcb_state: placementState, updated_at: new Date().toISOString() })
    .eq('id', projectId);

  await wait(800);
  controller.enqueue(encoder.encode(encodeSse({ type: 'step', step: 'ROUTING' })));
  await streamText(controller, encoder, `**Routing** signal and power nets…\n\n`);
  const routingState: PCBState = { ...placementState, status: 'ROUTING_DONE' };
  controller.enqueue(encoder.encode(encodeSse({ type: 'pcb_state', state: routingState })));
  controller.enqueue(encoder.encode(encodeSse({ type: 'status', status: 'ROUTING_DONE' })));
  await supabase
    .from('projects')
    .update({ status: 'ROUTING_DONE', pcb_state: routingState, updated_at: new Date().toISOString() })
    .eq('id', projectId);

  await wait(600);
  controller.enqueue(encoder.encode(encodeSse({ type: 'step', step: 'DRC' })));
  await streamText(
    controller,
    encoder,
    `**DRC clean** — 0 violations. Your PCB is manufacturable. Ready to export Gerbers or order from JLCPCB.`,
  );
  const drcState: PCBState = { ...routingState, status: 'DRC_CLEAN', drcViolations: [] };
  controller.enqueue(encoder.encode(encodeSse({ type: 'pcb_state', state: drcState })));
  controller.enqueue(encoder.encode(encodeSse({ type: 'status', status: 'DRC_CLEAN' })));
  controller.enqueue(encoder.encode(encodeSse({ type: 'step', step: null })));
  await supabase
    .from('projects')
    .update({ status: 'DRC_CLEAN', pcb_state: drcState, updated_at: new Date().toISOString() })
    .eq('id', projectId);

  const totalCost = 8.5;
  await supabase
    .from('credits')
    .update({
      balance: Math.max(0, balanceStart - totalCost),
      updated_at: new Date().toISOString(),
    })
    .eq('user_id', userId);

  controller.enqueue(encoder.encode(encodeSse({ type: 'done' })));
}

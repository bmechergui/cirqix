import type { SchemaJson } from '../../engines/engine-router';
import type { SchemaComponent } from '@cirqix/types';
import { log, getAnthropicClient } from '../shared';

// --- Haiku schema generator ----------------------------------------------

export async function generateSchemaWithHaiku(description: string): Promise<SchemaJson | null> {
  // Review fix HIGH-1: reuse module-level singleton client.
  const client = getAnthropicClient();
  if (!client) {
    log.warn('schema agent: ANTHROPIC_API_KEY missing, using complexity-based fallback');
    return null;
  }

  try {
    const response = await client.messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 4096,
      system: `You are a PCB schematic generator. Given a circuit description, return a single JSON object (no markdown, no comments) with exactly these four keys:

"components": array of { "ref": string, "value": string, "footprint": string, "symbol": string, "lcsc"?: string }
"nets": array of net name strings — every net that appears in connections MUST be listed here
"connections": array of { "name": string, "pins": [{"ref": string, "pin": number|string}, ...] }
  - EVERY net in "nets" MUST appear in "connections"
  - Every component "ref" used in pins MUST exist in "components"
  - "pin" rules:
      • Passives (R, C, LED, D, J/connector): use INTEGER pad number (1 or 2)
      • ICs (NE555, LM7805, regulators, op-amps, transistors): use KiCad PIN NAME string (see table below)

KiCad symbol table — use EXACTLY these values for "symbol":
  Resistor           → "Device:R"
  Capacitor (non-pol)→ "Device:C"
  Capacitor (polar)  → "Device:C_Polarized"
  LED                → "Device:LED"
  Diode (generic)    → "Device:D"
  Diode (Zener)      → "Device:D_Zener"
  NPN transistor     → "Device:Q_NPN_BCE"
  PNP transistor     → "Device:Q_PNP_BCE"
  MOSFET N           → "Device:Q_NMOS_GSD"
  MOSFET P           → "Device:Q_PMOS_GSD"
  NE555 / LM555      → "Timer:NE555P"
  LM7805 (5V reg)    → "Regulator_Linear:L7805"
  LM7812 (12V reg)   → "Regulator_Linear:L7812"
  LM317              → "Regulator_Linear:LM317_TO-220"
  LM1117-3.3         → "Regulator_Linear:LM1117T-3.3"
  LM1117-5.0         → "Regulator_Linear:LM1117T-5.0"
  Op-amp (generic)   → "Amplifier_Operational:LM358"
  2-pin connector    → "Connector_Generic:Conn_01x02"    pins: 1, 2
  3-pin connector    → "Connector_Generic:Conn_01x03"    pins: 1, 2, 3
  4-pin connector    → "Connector_Generic:Conn_01x04"    pins: 1, 2, 3, 4
  6-pin connector    → "Connector_Generic:Conn_01x06"    pins: 1..6
  8-pin connector    → "Connector_Generic:Conn_01x08"    pins: 1..8
  COMPLEX ICs — MANDATORY connector strategy (NEVER use real MCU symbols):
    Arduino Nano/UNO (30-pin) → "Connector_Generic:Conn_02x15_Odd_Even"  footprint: "Connector_PinHeader_2.54mm:PinHeader_2x15_P2.54mm_Vertical"
    Arduino Mega (44-pin)     → "Connector_Generic:Conn_02x22_Odd_Even"  footprint: "Connector_PinHeader_2.54mm:PinHeader_2x22_P2.54mm_Vertical"
    ESP32-WROOM / ESP32-S3    → "Connector_Generic:Conn_02x19_Odd_Even"  footprint: "Connector_PinHeader_2.54mm:PinHeader_2x19_P2.54mm_Vertical"
    Raspberry Pi Pico (40-pin)→ "Connector_Generic:Conn_02x20_Odd_Even"  footprint: "Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical"
    BME280/BMP280 module      → "Connector_Generic:Conn_01x06"           footprint: "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical"
    DHT22 / DHT11             → "Connector_Generic:Conn_01x04"           footprint: "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
    OLED SSD1306 I2C          → "Connector_Generic:Conn_01x04"           footprint: "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
    HC-05 Bluetooth module    → "Connector_Generic:Conn_01x06"
    STM32 bluepill (40-pin)   → "Connector_Generic:Conn_02x20_Odd_Even"
    Any other module (N pins) → "Connector_Generic:Conn_01xNN" where NN = pin count
  ALL connectors use INTEGER pin numbers (1, 2, 3, ...) in connections.
  If no symbol fits   → "Device:R" (fallback)

Footprint keys:
  "0402" / "0603" / "0805" / "1206" = 2 pads  (use pin 1 or 2)
  "LED"  = 2 pads  (pin 1=anode, pin 2=cathode)
  "TO-220" / "SOT-223" = 3 pads
  "DIP-8" / "TSSOP-8"  = 8 pads
  "Conn_2" / "Conn_3" / "Conn_4" = 2/3/4 pads

KiCad pin NAMES for ICs — use these exact strings in "pin":
  NE555P (Timer:NE555P):
    "GND"=1, "TR"=2 (TRIG), "Q"=3 (OUT), "R"=4 (RST), "CV"=5, "THR"=6, "DIS"=7, "VCC"=8
  L7805 (Regulator_Linear:L7805):
    "IN"=1, "GND"=2, "OUT"=3
  LM1117 (Regulator_Linear:LM1117T-x.x):
    "GND"=1, "OUT"=2, "IN"=3
  LM317 (Regulator_Linear:LM317_TO-220):
    "IN"=1, "ADJ"=2, "OUT"=3
  LM358 op-amp (Amplifier_Operational:LM358) — unit A:
    "IN-"=2, "IN+"=3, "VCC"=8, "OUT"=1, "GND"=4
  Q_NPN_BCE (Device:Q_NPN_BCE):
    "B"=1 (base), "C"=2 (collector), "E"=3 (emitter)
  Q_PMOS_GSD (Device:Q_PMOS_GSD):
    "G"=1 (gate), "S"=2 (source), "D"=3 (drain)

Reference designators: R=resistor, C=capacitor, U=module/IC (use U_ESP, U_ARD, U_BME…), D=diode/LED, J=connector, Q=transistor.
IMPORTANT: For MCU/sensor modules, use ref prefix U_ followed by short name (U_ESP1, U_ARD1, U_BME1).
Keep it to ≤ 20 components.

Example — "LED with 330R on 3.3V" (passives use numbers, connectors use numbers):
{"components":[{"ref":"J1","value":"PWR","footprint":"Conn_2","symbol":"Connector_Generic:Conn_01x02"},{"ref":"R1","value":"330R","footprint":"0603","symbol":"Device:R"},{"ref":"D1","value":"LED_RED","footprint":"LED","symbol":"Device:LED"}],"nets":["GND","3V3","NET_R_D"],"connections":[{"name":"GND","pins":[{"ref":"J1","pin":2},{"ref":"D1","pin":2}]},{"name":"3V3","pins":[{"ref":"J1","pin":1},{"ref":"R1","pin":1}]},{"name":"NET_R_D","pins":[{"ref":"R1","pin":2},{"ref":"D1","pin":1}]}]}

Example — "LM7805 5V regulator" (IC uses pin names):
{"components":[{"ref":"U1","value":"LM7805","footprint":"TO-220","symbol":"Regulator_Linear:L7805"},{"ref":"C1","value":"100nF","footprint":"0603","symbol":"Device:C"},{"ref":"J1","value":"VIN","footprint":"Conn_2","symbol":"Connector_Generic:Conn_01x02"}],"nets":["GND","VIN","VOUT"],"connections":[{"name":"VIN","pins":[{"ref":"J1","pin":1},{"ref":"U1","pin":"IN"},{"ref":"C1","pin":1}]},{"name":"VOUT","pins":[{"ref":"U1","pin":"OUT"},{"ref":"C1","pin":1}]},{"name":"GND","pins":[{"ref":"J1","pin":2},{"ref":"U1","pin":"GND"},{"ref":"C1","pin":2}]}]}

Return ONLY valid JSON. No markdown fences. No explanation.`,
      messages: [{ role: 'user', content: `Circuit: ${description}` }],
    });

    const text = response.content[0]?.type === 'text' ? response.content[0].text.trim() : '';
    if (!text) {
      log.warn({ stop_reason: response.stop_reason }, 'Path B: Haiku returned empty text');
      return null;
    }
    if (response.stop_reason === 'max_tokens') {
      log.warn({ len: text.length }, 'Path B: Haiku hit max_tokens — JSON likely truncated');
    }

    // Strip accidental markdown fences if model adds them
    const cleaned = text.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '').trim();
    const parsed = JSON.parse(cleaned) as SchemaJson;
    if (!Array.isArray(parsed.components) || parsed.components.length === 0) return null;

    // Validate + repair connections
    // ICs use KiCad pin name strings ("IN", "GND", "TR"…) — always valid if ref exists
    // Passives use 1-indexed pad numbers — validate against footprint pad count
    const padCountMap: Record<string, number> = {
      '0402': 2, '0603': 2, '0805': 2, '1206': 2, 'LED': 2,
      'SOT-23': 3, 'SOT-23-5': 5, 'TSSOP-8': 8, 'DIP-8': 8,
      'TO-220': 3, 'SOT-223': 3, 'CONN_2': 2, 'CONN_3': 3, 'CONN_4': 4,
    };
    const compPads = new Map(
      parsed.components.map((c) => {
        const key = Object.keys(padCountMap).find((k) =>
          c.footprint.toUpperCase().includes(k.toUpperCase())
        );
        return [c.ref, padCountMap[key ?? '0402'] ?? 2] as [string, number];
      })
    );
    const validRefs = new Set(parsed.components.map((c) => c.ref));

    if (Array.isArray(parsed.connections)) {
      parsed.connections = parsed.connections
        .map((conn) => ({
          ...conn,
          pins: conn.pins.filter((p) => {
            if (!validRefs.has(p.ref)) return false;
            // String pin name → IC pin (e.g. "IN", "GND", "TR") — trust it
            if (typeof p.pin === 'string') return p.pin.length > 0;
            // Numeric pin → validate against pad count
            const maxPin = compPads.get(p.ref) ?? 2;
            return p.pin >= 1 && p.pin <= maxPin;
          }),
        }))
        .filter((conn) => conn.name && conn.pins.length > 0);
    } else {
      parsed.connections = [];
    }

    return parsed;
  } catch (err) {
    // Graceful fallback — never let a Haiku failure block the pipeline.
    // Review fix HIGH-2: log warning so silent fallbacks stay observable.
    log.warn({ err }, 'schema agent: Haiku call or JSON parse failed, using fallback');
    return null;
  }
}

// --- circuit_synth code generator ----------------------------------------

export interface SchematicCodeResult {
  code: string;
  footprints: SchemaComponent[];
}

export async function generateSchematicCodeWithHaiku(description: string): Promise<SchematicCodeResult | null> {
  const client = getAnthropicClient();
  if (!client) return null;

  try {
    const response = await client.messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 3000,
      system: `You are a circuit schematic code generator using the circuit_synth Python library.
Generate Python code using the @circuit decorator pattern.

circuit_synth API — EXACT pattern:
\`\`\`python
import os
from circuit_synth import circuit as cs_circuit, Component, Net

@cs_circuit(name="my_project")
def build():
    gnd = Net("GND")
    vcc = Net("+5V")
    r1 = Component("Device:R", ref="R", value="10k")  # ref PREFIX (no number) is REQUIRED
    r1[1] += vcc   # integer pins for passives
    r1[2] += gnd

os.chdir(_PROJECT_PATH)   # MANDATORY — place output in the right directory
circ = build()
circ.generate_kicad_project(project_name="project", generate_pcb=False, force_regenerate=True)
\`\`\`

_PROJECT_PATH is already defined — use it directly.
CRITICAL: always call os.chdir(_PROJECT_PATH) BEFORE calling generate_kicad_project.
CRITICAL: project_name must be a simple string like "project" — NEVER pass _PROJECT_PATH as project_name.
CRITICAL: ref= is REQUIRED in every Component(). Without ref, the component is NOT added to the circuit.
Use ref PREFIX (no number): ref="R" → auto-becomes R1, R2... | ref="C" → C1, C2... | ref="U_ARD" → U_ARD1

STRICT RULES — NEVER BREAK THESE:
  NEVER use MCU_Microchip_ATmega, MCU_Module, RF_Module:*, Sensor:*, Sensor_Pressure:* symbols
  NEVER use Arduino_Nano_v3.x, ATmega328P-A, ESP32-WROOM-32, BME280, DHT11, DHT22 as symbols
  NEVER use any symbol with more than 4 pins that is not Device:R/C/LED/D
  ALWAYS use Connector_Generic:Conn_XxYY for any Arduino, ESP32, sensor module, or IC with >4 pins
  ALWAYS provide ref= in every Component() — without it the component is invisible in the schematic

CONNECTOR STRATEGY — use generic connectors for complex ICs (better schematics, no missing pins):

  Arduino Nano (30-pin dual-row) → Component("Connector_Generic:Conn_02x15_Odd_Even", value="Arduino_Nano")
    footprint: "Connector_PinHeader_2.54mm:PinHeader_2x15_P2.54mm_Vertical"
    Pins: 1=D12, 2=D11/MOSI, 3=D10/SS, 4=D9, 5=D8, 6=D7, 7=D6, 8=D5, 9=D4,
          10=D3, 11=D2, 12=GND, 13=RST, 14=RX/D0, 15=TX/D1,
          16=D13/SCK, 17=3V3, 18=AREF, 19=A0, 20=A1, 21=A2, 22=A3, 23=A4/SDA, 24=A5/SCL,
          25=A6, 26=A7, 27=+5V, 28=RST, 29=GND, 30=VIN

  BME280/BMP280 module (6-pin) → Component("Connector_Generic:Conn_01x06", value="BME280")
    footprint: "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical"
    Pins: 1=VCC, 2=GND, 3=SCL, 4=SDA, 5=CSB, 6=SDO

  DHT22/DHT11 (4-pin)  → Component("Connector_Generic:Conn_01x04", value="DHT22")
    footprint: "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
    Pins: 1=VCC, 2=DATA, 3=NC, 4=GND

  OLED I2C 128x64 (4)  → Component("Connector_Generic:Conn_01x04", value="SSD1306_OLED")
    footprint: "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
    Pins: 1=GND, 2=VCC, 3=SCL, 4=SDA

  ESP32-WROOM-32 (38-pin dual-row) → Component("Connector_Generic:Conn_02x19_Odd_Even", ref="U_ESP", value="ESP32-WROOM-32")
    footprint: "Connector_PinHeader_2.54mm:PinHeader_2x19_P2.54mm_Vertical"
    Pins: 1=GND, 2=3V3, 3=EN, 4=VP/ADC0, 5=VN/ADC3, 6=IO34, 7=IO35, 8=IO32, 9=IO33,
          10=IO25, 11=IO26, 12=IO27, 13=IO14, 14=IO12, 15=GND2, 16=IO13, 17=SD2, 18=SD3,
          19=CMD, 20=5V, 21=CLK, 22=SD0, 23=SD1, 24=IO15, 25=IO2, 26=IO0, 27=IO4,
          28=IO16, 29=IO17, 30=IO5, 31=IO18, 32=IO19, 33=IO21, 34=RXD0, 35=TXD0,
          36=IO22, 37=IO23, 38=GND3

  HC-05 Bluetooth (6)  → Component("Connector_Generic:Conn_01x06", ref="U_BT", value="HC-05")
    Pins: 1=STATE, 2=RXD, 3=TXD, 4=GND, 5=VCC, 6=EN

  Any other module N   → Component("Connector_Generic:Conn_01xNN", ref="U_MOD", value="Module_Name")

REAL SYMBOLS for passive/simple components:
  "Device:R"                      pins: 1, 2
  "Device:C"                      pins: 1, 2
  "Device:C_Polarized"            pins: +, -
  "Device:LED"                    pins: A, K
  "Device:D"                      pins: A, K
  "Timer:NE555P"                  pins: GND, TR, Q, R, CV, THR, DIS, VCC
  "Regulator_Linear:LM1117T-3.3"  pins: GND, OUT, IN
  "Regulator_Linear:LM1117T-5.0"  pins: GND, OUT, IN
  "Regulator_Linear:L7805"        pins: VI, GND, VO
  "Connector_Generic:Conn_01x02"  pins: Pin_1, Pin_2 (power connector)

REF naming: modules → U_NAME1 (e.g. U_ARD1, U_BME1), passives → R1/C1/D1, connectors → J_PWR1

Return ONLY valid JSON (no markdown):
{
  "circuit_synth_code": "import os\\nfrom circuit_synth import circuit as cs_circuit, Component, Net\\n\\n@cs_circuit(name=\\"project\\")\\ndef build():\\n    gnd = Net(\\"GND\\")\\n    r1 = Component(\\"Device:R\\", ref=\\"R\\", value=\\"10k\\")\\n    r1[1] += gnd\\n\\nos.chdir(_PROJECT_PATH)\\ncirc = build()\\ncirc.generate_kicad_project(project_name=\\"project\\", generate_pcb=False, force_regenerate=True)",
  "footprints": [
    {"ref": "U_ARD1", "value": "Arduino Nano", "footprint": "Connector_PinHeader_2.54mm:PinHeader_2x15_P2.54mm_Vertical", "symbol": "Connector_Generic:Conn_02x15_Odd_Even"},
    {"ref": "R1", "value": "10k", "footprint": "Resistor_SMD:R_0603_1608Metric", "symbol": "Device:R"}
  ]
}`,
      messages: [{ role: 'user', content: `Circuit: ${description}` }],
    });

    const text = response.content[0]?.type === 'text' ? response.content[0].text.trim() : '';
    if (!text) return null;

    const cleaned = text.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '').trim();
    const parsed = JSON.parse(cleaned) as { circuit_synth_code: string; footprints: SchemaComponent[] };
    if (!parsed.circuit_synth_code || !Array.isArray(parsed.footprints)) return null;

    const code = parsed.circuit_synth_code;
    if (!code.includes('cs_circuit') && !code.includes('from circuit_synth') && !code.includes('import circuit')) {
      log.warn('Haiku returned non-Python content in circuit_synth_code — discarding');
      return null;
    }

    return { code, footprints: parsed.footprints };
  } catch (err) {
    log.warn({ err }, 'circuit_synth code generator: Haiku call failed');
    return null;
  }
}

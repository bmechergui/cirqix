import type { SchemaJson } from '../../engines/engine-router';
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

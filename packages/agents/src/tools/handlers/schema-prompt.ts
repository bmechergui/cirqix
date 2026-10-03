import type { SchemaJson } from '../../engines/engine-router';

/**
 * LE contrat du schema, partage par tous les fournisseurs (Haiku par l API,
 * Claude Code en ligne de commande) : un seul prompt, un seul nettoyage, une
 * seule validation. Deux copies divergeraient — c est arrive a `_poser_via_
 * dans_pastille` cote service, dont la docstring promettait de suivre le
 * fanout et ne le faisait plus.
 */
export const SCHEMA_SYSTEM_PROMPT = `You are a PCB schematic generator. Given a circuit description, return a JSON object with the keys "components", "nets" and "connections" described here, plus "board_size_imposed" (and, when you choose the board size, "board_width_mm" / "board_height_mm") described under Rules:

"components": array of { "ref": string, "value": string, "footprint": string, "symbol": string, "lcsc"?: string }
"nets": array of net name strings — every net that appears in connections MUST be listed here
"connections": array of { "name": string, "pins": [{"ref": string, "pin": number|string}, ...] }
  - EVERY net in "nets" MUST appear in "connections"
  - Every component "ref" used in pins MUST exist in "components"
  - "pin" rules:
      • Passives and connectors (R, C, LED, D, J): INTEGER pad number, from 1 to the part's pin count
      • ICs and transistors: the KiCad pin NAME string from the table below — except where the table gives pin numbers (LM358)

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
  "LED"  = 2 pads  (pin 1=K cathode, pin 2=A anode — KiCad Device:LED)
  "TO-220" / "SOT-223" = 3 pads
  "DIP-8" / "TSSOP-8"  = 8 pads
  "Conn_2" / "Conn_3" / "Conn_4" = 2/3/4 pads

KiCad pin names for ICs — use these strings in "pin" (the service maps NE555 datasheet names to KiCad's TRIG/OUT/~{RST}/CONT/THRES/DISCH):
  NE555P (Timer:NE555P):
    "GND"=1, "TR"=2 (TRIG), "Q"=3 (OUT), "R"=4 (RST), "CV"=5, "THR"=6, "DIS"=7, "VCC"=8
  L7805 (Regulator_Linear:L7805):
    "IN"=1, "GND"=2, "OUT"=3
  LM1117 (Regulator_Linear:LM1117T-x.x):
    "GND"=1, "VO"=2 (output), "VI"=3 (input)
  LM317 (Regulator_Linear:LM317_TO-220):
    "ADJ"=1, "VO"=2 (output), "VI"=3 (input)
  LM358 op-amp (Amplifier_Operational:LM358) — its pins have no usable names; use pin NUMBERS:
    1=OUT A, 2=IN− A, 3=IN+ A, 4=V− (GND), 5=IN+ B, 6=IN− B, 7=OUT B, 8=V+
  Q_NPN_BCE (Device:Q_NPN_BCE):
    "B"=1 (base), "C"=2 (collector), "E"=3 (emitter)
  Q_PMOS_GSD (Device:Q_PMOS_GSD):
    "G"=1 (gate), "S"=2 (source), "D"=3 (drain)

Reference designators: 1-2 uppercase letters then a number — R resistor, C capacitor, U IC or module (U1, U2…), D diode/LED, J connector, Q transistor, SW switch.
Include every part the circuit needs (decoupling, pull-ups, connectors) and nothing it does not.

Rules:
  - EVERY net in "connections" joins AT LEAST 2 pins. A one-pin net is an error.
  - For a connector, the footprint pin count MUST equal the symbol pin count:
    Conn_01x04 → "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", never 1x02.
  - "footprint" is a full KiCad footprint "Library:Name" whenever you know it; the short keys listed above are the only accepted shortcuts.
  - Every pin of a power/bus signal named in the description (SDA, SCL, TX, RX…) reaches its connector.
  - "ref" is a KiCad reference: 1-2 uppercase letters then a number (U1, C12, J2, SW1). Never a name like U_TMP1 or SENSOR — the reference is printed on the silkscreen next to a small footprint.
  - If you choose the board size, add "board_width_mm" and "board_height_mm" (numbers) AND "board_size_imposed": true ONLY when the description itself states dimensions ("40 x 30 mm", "carte de 50 mm de large"). Otherwise "board_size_imposed": false — the outline will then be tightened to the placement.

Example — "LED with 330R on 3.3V" (passives use numbers, connectors use numbers):
{"components":[{"ref":"J1","value":"PWR","footprint":"Conn_2","symbol":"Connector_Generic:Conn_01x02"},{"ref":"R1","value":"330R","footprint":"0603","symbol":"Device:R"},{"ref":"D1","value":"LED_RED","footprint":"LED","symbol":"Device:LED"}],"nets":["GND","3V3","NET_R_D"],"connections":[{"name":"GND","pins":[{"ref":"J1","pin":2},{"ref":"D1","pin":1}]},{"name":"3V3","pins":[{"ref":"J1","pin":1},{"ref":"R1","pin":1}]},{"name":"NET_R_D","pins":[{"ref":"R1","pin":2},{"ref":"D1","pin":2}]}]}

Example — "LM7805 5V regulator" (IC uses pin names; one pin belongs to exactly one net):
{"components":[{"ref":"J1","value":"VIN","footprint":"Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical","symbol":"Connector_Generic:Conn_01x02"},{"ref":"U1","value":"LM7805","footprint":"Package_TO_SOT_THT:TO-220-3_Vertical","symbol":"Regulator_Linear:L7805"},{"ref":"C1","value":"330nF","footprint":"Capacitor_SMD:C_0603_1608Metric","symbol":"Device:C"},{"ref":"C2","value":"100nF","footprint":"Capacitor_SMD:C_0603_1608Metric","symbol":"Device:C"},{"ref":"J2","value":"5V_OUT","footprint":"Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical","symbol":"Connector_Generic:Conn_01x02"}],"nets":["VIN","5V","GND"],"connections":[{"name":"VIN","pins":[{"ref":"J1","pin":1},{"ref":"U1","pin":"IN"},{"ref":"C1","pin":1}]},{"name":"5V","pins":[{"ref":"U1","pin":"OUT"},{"ref":"C2","pin":1},{"ref":"J2","pin":1}]},{"name":"GND","pins":[{"ref":"J1","pin":2},{"ref":"U1","pin":"GND"},{"ref":"C1","pin":2},{"ref":"C2","pin":2},{"ref":"J2","pin":2}]}]}
`;

/**
 * Le meme contrat pour l API (output_config.format) : Haiku 4.5 prend en charge
 * les sorties structurees, qui garantissent un JSON conforme. Le chemin
 * `claude -p` ne peut pas le passer ; il garde la consigne en prose
 * (schema-claude-code.ts) et le nettoyage des clotures de parseSchemaText.
 */
export const SCHEMA_JSON_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['components', 'nets', 'connections', 'board_size_imposed'],
  properties: {
    components: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['ref', 'value', 'footprint', 'symbol'],
        properties: {
          ref: { type: 'string' },
          value: { type: 'string' },
          footprint: { type: 'string' },
          symbol: { type: 'string' },
          lcsc: { type: 'string' },
        },
      },
    },
    nets: { type: 'array', items: { type: 'string' } },
    connections: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['name', 'pins'],
        properties: {
          name: { type: 'string' },
          pins: {
            type: 'array',
            items: {
              type: 'object',
              additionalProperties: false,
              required: ['ref', 'pin'],
              properties: {
                ref: { type: 'string' },
                pin: { anyOf: [{ type: 'integer' }, { type: 'string' }] },
              },
            },
          },
        },
      },
    },
    board_width_mm: { type: 'number' },
    board_height_mm: { type: 'number' },
    board_size_imposed: { type: 'boolean' },
  },
} as const;

/**
 * Nombre de pastilles d un footprint, LU dans son nom — ou null si le nom ne
 * le dit pas. Formes reconnues : `_1x04_`, `_2x15_` (produit), `LQFP-48`,
 * `SOIC-8`, `SOT-23-5`, `SOT-223-3`, `DIP-8`, `TO-220-3`, et les cles courtes
 * du prompt (`0603`, `LED`, `Conn_4`, `TO-220`, `SOT-223`).
 */
/** Le message utilisateur : la description, plus les problemes de l essai precedent s il y en a eu. */
export function messageUtilisateur(description: string, retour?: string): string {
  if (!retour) return `Circuit: ${description}`;
  return `Circuit: ${description}\n\nYour previous JSON was rejected for these problems:\n${retour}\nReturn a corrected JSON that fixes every one of them.`;
}

export function padsDuFootprint(footprint: string): number | null {
  const f = (footprint ?? '').trim();
  if (!f) return null;
  const grille = /(\d+)x(\d+)(?:_|$)/i.exec(f);
  if (grille) return Number(grille[1]) * Number(grille[2]);
  const boitier = /(?:LQFP|TQFP|QFP|QFN|SOIC|SOP|TSSOP|SSOP|MSOP|DIP|PDIP|SOT-23|SOT-223|SOT-89|TO-220|TO-252|TO-263|DFN|WSON)-(\d+)/i.exec(f);
  if (boitier) return Number(boitier[1]);
  const conn = /^CONN_(\d+)$/i.exec(f);
  if (conn) return Number(conn[1]);
  const haut = f.toUpperCase();
  if (/^(0402|0603|0805|1206|LED)$/.test(haut) || /_(0402|0603|0805|1206)_/.test(haut)) return 2;
  if (haut === 'SOT-23' || haut === 'SOT-223' || haut === 'TO-220') return 3;
  if (haut === 'TSSOP-8' || haut === 'DIP-8') return 8;
  return null;
}

/**
 * Ce qui rend un schema inutilisable meme s il est lisible : les defauts que
 * le DRC ne voit PAS, parce qu ils ne creent aucune connexion manquante.
 *
 * - une net a moins de deux broches ne relie rien (mesure 2026-09-13 : SDA
 *   a une broche, board « 100 % route, 0 erreur », bus I2C absent) ;
 * - un connecteur dont le symbole (Conn_01xNN) et le footprint n ont pas le
 *   meme nombre de broches perd des broches au trace.
 */
export const REFERENCE_KICAD = /^[A-Z]{1,2}[0-9]{1,3}$/;

export function problemesDuSchema(schema: SchemaJson): string[] {
  const problemes: string[] = [];
  // Une broche dans deux nets les court-circuite : la generation refuse ensuite
  // le board (_courts_circuits, d3b35bbc). Mieux vaut le dire au modele ici.
  const netDeLaBroche = new Map<string, string>();
  for (const conn of schema.connections ?? []) {
    if ((conn.pins?.length ?? 0) < 2) {
      problemes.push(`net "${conn.name}" has ${conn.pins?.length ?? 0} pin(s) — a net must join at least 2 pins`);
    }
    for (const p of conn.pins ?? []) {
      const cle = `${p.ref}.${String(p.pin)}`;
      const deja = netDeLaBroche.get(cle);
      if (deja !== undefined && deja !== conn.name) {
        problemes.push(`pin ${cle} is in nets "${deja}" and "${conn.name}" — a pin belongs to exactly one net`);
      } else {
        netDeLaBroche.set(cle, conn.name);
      }
    }
  }
  for (const c of schema.components ?? []) {
    // Une référence « U_TMP1 » (livrée le 2026-09-13) déborde de son
    // empreinte 1x4 sur la sérigraphie : le préfixe est une lettre KiCad,
    // suivie d un numéro, rien d autre.
    if (!REFERENCE_KICAD.test(c.ref ?? '')) {
      problemes.push(`component "${c.ref}": a reference is 1-2 uppercase letters and a number (U1, C12, J2), not a name`);
    }
    const m = /Conn_(\d+)x(\d+)/i.exec(c.symbol ?? '');
    if (!m) continue;
    const attendu = Number(m[1]) * Number(m[2]);
    const pads = padsDuFootprint(c.footprint);
    if (pads !== null && pads !== attendu) {
      problemes.push(`component ${c.ref}: symbol ${c.symbol} has ${attendu} pins but footprint ${c.footprint} has ${pads} pads`);
    }
  }
  return problemes;
}

/**
 * Le texte rendu par le modele -> SchemaJson, ou null s il est illisible.
 * Retire d eventuelles clotures markdown, refuse un schema sans composant,
 * et ne garde des connexions que les broches plausibles (ref connue, numero
 * dans le compte de pastilles du boitier).
 */
export function parseSchemaText(text: string): SchemaJson | null {
  try {
    const cleaned = text.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '').trim();
    const parsed = JSON.parse(cleaned) as SchemaJson;
    if (!Array.isArray(parsed.components) || parsed.components.length === 0) return null;

    // Validate + repair connections
    // ICs use KiCad pin name strings ("IN", "GND", "TR"…) — always valid if ref exists
    // Passives use 1-indexed pad numbers — validate against footprint pad count
    // ⚠️ Un footprint INCONNU ne vaut pas « 2 pastilles ». Mesure du
    // 2026-09-13 (run 25a6853c) : `PinHeader_1x04` ne figurait pas dans la
    // table, le connecteur etait compte a 2 pastilles, ses broches 3 et 4
    // etaient SUPPRIMEES en silence — et la net SDA finissait a une broche,
    // invisible au DRC (un net a une broche n est pas « manquant »). Le
    // compte se LIT dans le nom du footprint ; s il ne se lit pas, on ne
    // filtre pas : une broche douteuse vaut mieux qu une broche effacee.
    const compPads = new Map(
      parsed.components.map((c) => [c.ref, padsDuFootprint(c.footprint)] as [string, number | null])
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
            const maxPin = compPads.get(p.ref) ?? null;
            if (maxPin === null) return p.pin >= 1;
            return p.pin >= 1 && p.pin <= maxPin;
          }),
        }))
        .filter((conn) => conn.name && conn.pins.length > 0);
    } else {
      parsed.connections = [];
    }

    return parsed;
  } catch {
    return null;
  }
}

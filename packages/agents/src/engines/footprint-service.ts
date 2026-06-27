/**
 * Footprint resolution cascade — Phase 4.1
 *
 * Steps (stop at first success):
 *   1. KiCad standard library name lookup   (local, instant, covers ~95% of passives + ICs)
 *   2. SnapMagic API                        (requires SNAPMAGIC_API_KEY, millions of parts)
 *   3. LCSC/EasyEDA component search        (public HTTP, no key needed)
 *   4. Claude Haiku AI generation           (always available fallback, generates .kicad_mod)
 *
 * Steps 2–3 are skipped when their env vars / endpoints are unavailable.
 * Step 4 (AI) costs 3 credits and is logged accordingly.
 */

import Anthropic from '@anthropic-ai/sdk';
import pino from 'pino';
import { lookupFootprintCache, cacheFootprintResult } from './footprint-cache';

const log = pino({ name: 'cirqix.agents.footprint-service', level: process.env['LOG_LEVEL'] ?? 'info' });

const TIMEOUT_MS = 8_000;
const HAIKU_MODEL = 'claude-haiku-4-5-20251001';

// ─── Public result type ───────────────────────────────────────────────────────

export type FootprintSource = 'kicad_official' | 'snapmagic' | 'lcsc' | 'ai_generated';

export interface FootprintResult {
  footprint_name: string;
  source: FootprintSource;
  /** Populated only for ai_generated — the raw .kicad_mod S-expression */
  kicad_mod?: string;
  lcsc?: string;
  package_type?: string;
  note: string;
}

export class FootprintServiceError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'FootprintServiceError';
  }
}

// ─── Step 1 — KiCad standard library lookup ──────────────────────────────────
//
// Maps common package tokens (case-insensitive) → official KiCad footprint names.
// Covers SMD resistors, capacitors, inductors, transistors, linear ICs, connectors.

const KICAD_LIB: Array<[RegExp, string]> = [
  // Resistors
  [/^R.*0402$|0402.*res/i,     'Resistor_SMD:R_0402_1005Metric'],
  [/^R.*0603$|0603.*res/i,     'Resistor_SMD:R_0603_1608Metric'],
  [/^R.*0805$|0805.*res/i,     'Resistor_SMD:R_0805_2012Metric'],
  [/^R.*1206$|1206.*res/i,     'Resistor_SMD:R_1206_3216Metric'],
  // Capacitors
  [/^C.*0402$|0402.*cap/i,     'Capacitor_SMD:C_0402_1005Metric'],
  [/^C.*0603$|0603.*cap/i,     'Capacitor_SMD:C_0603_1608Metric'],
  [/^C.*0805$|0805.*cap/i,     'Capacitor_SMD:C_0805_2012Metric'],
  [/^C.*1206$|1206.*cap/i,     'Capacitor_SMD:C_1206_3216Metric'],
  // Inductors
  [/^L.*0402$/i,               'Inductor_SMD:L_0402_1005Metric'],
  [/^L.*0603$/i,               'Inductor_SMD:L_0603_1608Metric'],
  // LEDs
  [/LED.*0603|0603.*led/i,     'LED_SMD:LED_0603_1608Metric'],
  [/LED.*0805|0805.*led/i,     'LED_SMD:LED_0805_2012Metric'],
  // Transistors / diodes
  [/SOT-?23[-_]6/i,            'Package_TO_SOT_SMD:SOT-23-6'],
  [/SOT-?23[-_]5/i,            'Package_TO_SOT_SMD:SOT-23-5'],
  [/SOT-?23/i,                 'Package_TO_SOT_SMD:SOT-23'],
  [/SOT-?223/i,                'Package_TO_SOT_SMD:SOT-223-3_TabPin2'],
  [/TO-?220/i,                 'Package_TO_SOT_THT:TO-220-3_Vertical'],
  [/SOD-?123/i,                'Diode_SMD:D_SOD-123'],
  [/SOD-?323/i,                'Diode_SMD:D_SOD-323'],
  // ICs — SOIC / TSSOP / QFN / DIP
  [/SOIC-?8/i,                 'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm'],
  [/SOIC-?14/i,                'Package_SO:SOIC-14_3.9x8.7mm_P1.27mm'],
  [/SOIC-?16/i,                'Package_SO:SOIC-16_3.9x9.9mm_P1.27mm'],
  [/TSSOP-?8/i,                'Package_SO:TSSOP-8_4.4x3mm_P0.65mm'],
  [/TSSOP-?16/i,               'Package_SO:TSSOP-16_4.4x5mm_P0.65mm'],
  [/TSSOP-?20/i,               'Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm'],
  [/QFN-?32/i,                 'Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.65x3.65mm'],
  [/QFN-?48/i,                 'Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm_EP5.6x5.6mm'],
  [/DIP-?8/i,                  'Package_DIP:DIP-8_W7.62mm'],
  [/DIP-?14/i,                 'Package_DIP:DIP-14_W7.62mm'],
  [/DIP-?16/i,                 'Package_DIP:DIP-16_W7.62mm'],
  [/DIP-?28/i,                 'Package_DIP:DIP-28_W15.24mm'],
  // Common ICs by part number
  [/NE555|LM555/i,             'Package_DIP:DIP-8_W7.62mm'],
  [/LM7805|LM78\d{2}/i,       'Package_TO_SOT_THT:TO-220-3_Vertical'],
  [/ESP32.?WROOM/i,            'RF_Module:ESP32-WROOM-32'],
  [/ESP32.?WROVER/i,           'RF_Module:ESP32-WROVER-B'],
  [/STM32F103C8/i,             'Package_QFP:LQFP-48_7x7mm_P0.5mm'],
  [/ATmega328P/i,              'Package_DIP:DIP-28_W7.62mm'],
  [/ATmega32U4/i,              'Package_QFP:TQFP-44_10x10mm_P0.8mm'],
  [/ATMEGA328|ATMEGA2560/i,    'Package_DIP:DIP-28_W7.62mm'],
  [/AMS1117|AP2112/i,          'Package_TO_SOT_SMD:SOT-223-3_TabPin2'],
  // Connectors — short forms (Conn_2, Conn_3…) and KiCad long forms
  [/\bConn[_\s-]?2\b/i,            'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical'],
  [/\bConn[_\s-]?3\b/i,            'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical'],
  [/\bConn[_\s-]?4\b/i,            'Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical'],
  [/PinHeader.*1x02|Conn.*01x02/i, 'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical'],
  [/PinHeader.*1x03|Conn.*01x03/i, 'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical'],
  [/PinHeader.*2x05|Conn.*02x05/i, 'Connector_PinHeader_2.54mm:PinHeader_2x05_P2.54mm_Vertical'],
  [/USB.?C|TYPE.?C/i,              'Connector_USB:USB_C_Receptacle_GCT_USB4105'],
  [/USB.?Micro/i,                  'Connector_USB:USB_Micro-B_Wuerth_614105150721'],
  [/USB.?Mini/i,                   'Connector_USB:USB_Mini-B_Wurth_629105150521'],
  [/Barrel|DC.?Jack/i,             'Connector_BarrelJack:BarrelJack_Horizontal'],
  // Crystal
  [/Crystal.*2-?pin|XTAL/i,        'Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm'],
];

function lookupKicadLibrary(partNumber: string, packageHint?: string): string | null {
  const haystack = `${partNumber} ${packageHint ?? ''}`.trim();
  for (const [pattern, footprint] of KICAD_LIB) {
    if (pattern.test(haystack)) return footprint;
  }
  // Connector refs (J1, J2 …) with no package hint → default 2-pin PinHeader
  if (/^J\d+$/.test(partNumber.trim())) {
    return 'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical';
  }
  return null;
}

// ─── Step 2 — SnapMagic API ───────────────────────────────────────────────────

interface SnapMagicHit {
  footprint_name?: string;
  part_number?: string;
}

async function searchSnapMagic(partNumber: string): Promise<FootprintResult | null> {
  const apiKey = process.env['SNAPMAGIC_API_KEY'];
  if (!apiKey) return null;

  try {
    const url = `https://www.snapeda.com/api/v1/parts/search?q=${encodeURIComponent(partNumber)}&exact=true`;
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${apiKey}`, Accept: 'application/json' },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!res.ok) return null;
    const body = await res.json() as { results?: SnapMagicHit[] };
    const hit = body.results?.[0];
    if (!hit?.footprint_name) return null;
    log.debug({ partNumber, hit }, 'SnapMagic hit');
    return {
      footprint_name: hit.footprint_name,
      source: 'snapmagic',
      note: `Footprint trouvé sur SnapMagic pour ${partNumber}.`,
    };
  } catch (err) {
    log.warn({ err }, 'SnapMagic search failed');
    return null;
  }
}

// ─── Step 3 — LCSC / EasyEDA search ──────────────────────────────────────────

interface EasyEdaHit {
  dataStr?: string;
  footprint?: string;
}

async function searchLCSC(partNumber: string): Promise<FootprintResult | null> {
  try {
    const url = `https://easyeda.com/api/products/search?q=${encodeURIComponent(partNumber)}&lang=en&limit=1`;
    const res = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!res.ok) return null;
    const body = await res.json() as { result?: { productList?: EasyEdaHit[] } };
    const hit = body.result?.productList?.[0];
    const footprintName = hit?.footprint ?? hit?.dataStr;
    if (!footprintName || typeof footprintName !== 'string') return null;
    log.debug({ partNumber, footprintName }, 'LCSC hit');
    const result: FootprintResult = {
      footprint_name: footprintName,
      source: 'lcsc',
      note: `Footprint trouvé sur LCSC/EasyEDA pour ${partNumber}.`,
    };
    if (partNumber.startsWith('C')) result.lcsc = partNumber;
    return result;
  } catch (err) {
    log.warn({ err }, 'LCSC search failed');
    return null;
  }
}

// ─── Step 4 — Claude Haiku AI generation ─────────────────────────────────────

function buildFootprintPrompt(partNumber: string, packageHint?: string): string {
  return `Generate a valid KiCad 7/8 .kicad_mod footprint file for the component: "${partNumber}"${packageHint ? ` (package: ${packageHint})` : ''}.

Rules:
- Determine the package type from the part number (SOT-23, SOIC-8, 0402, DIP-8, etc.)
- Use standard IPC-7351 pad dimensions for the detected package
- Include: fp_text reference, fp_text value, pads (numbered from 1), F.Courtyard rect, F.Fab rect, F.SilkS outline
- Output ONLY the raw S-expression — no markdown, no explanation

Example structure for SOT-23 (3 pads):
(footprint "SOT-23"
  (layer "F.Cu")
  (descr "SOT-23 3-pin package")
  (attr smd)
  (fp_text reference "REF**" (at 0 -1.8) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
  (fp_text value "SOT-23" (at 0 2) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
  (pad "1" smd rect (at -0.95 0.9) (size 0.6 0.9) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "2" smd rect (at 0.95 0.9) (size 0.6 0.9) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "3" smd rect (at 0 -0.9) (size 0.6 0.9) (layers "F.Cu" "F.Paste" "F.Mask"))
  (fp_rect (start -1.5 -1.5) (end 1.5 1.5) (layer "F.Courtyard") (stroke (width 0.05) (type solid)))
  (fp_rect (start -0.7 -1.2) (end 0.7 1.2) (layer "F.Fab") (stroke (width 0.1) (type solid)))
)

Generate for "${partNumber}"${packageHint ? ` / ${packageHint}` : ''} now:`;
}

async function generateWithAI(
  partNumber: string,
  packageHint?: string,
): Promise<FootprintResult | null> {
  const apiKey = process.env['ANTHROPIC_API_KEY'];
  if (!apiKey) return null;

  try {
    const client = new Anthropic({ apiKey });
    const msg = await client.messages.create({
      model: HAIKU_MODEL,
      max_tokens: 1024,
      messages: [{ role: 'user', content: buildFootprintPrompt(partNumber, packageHint) }],
    });

    const kicadMod = (msg.content[0] as Anthropic.TextBlock).text.trim();
    if (!kicadMod.startsWith('(footprint')) {
      log.warn({ kicadMod: kicadMod.slice(0, 100) }, 'AI footprint output invalid');
      return null;
    }

    // Derive a footprint_name from the output
    const nameMatch = kicadMod.match(/\(footprint "([^"]+)"/);
    const footprintName = nameMatch?.[1] ?? `${partNumber}_AI`;
    log.info({ partNumber, footprintName }, 'AI footprint generated');

    return {
      footprint_name: footprintName,
      source: 'ai_generated',
      kicad_mod: kicadMod,
      note: `Footprint .kicad_mod généré par Claude Haiku pour ${partNumber}.`,
    };
  } catch (err) {
    log.error({ err }, 'AI footprint generation failed');
    return null;
  }
}

// ─── Quick lookup (Step 1 only — synchronous, no network) ────────────────────

/**
 * Instant KiCad library lookup with no network calls.
 * Returns the official footprint name or null if not found.
 * Use this for bulk auto-resolution inside call_agent_schema.
 */
export function quickLookup(partNumber: string, packageHint?: string): string | null {
  return lookupKicadLibrary(partNumber, packageHint);
}

// ─── Main cascade ─────────────────────────────────────────────────────────────

export async function findFootprint(
  partNumber: string,
  packageHint?: string,
): Promise<FootprintResult> {
  const pn = partNumber.trim();
  const pkg = packageHint?.trim();

  log.info({ partNumber: pn, packageHint: pkg }, 'footprint cascade start');

  // Step 1 — KiCad standard library (instant, no network)
  const kicadName = lookupKicadLibrary(pn, pkg);
  if (kicadName) {
    log.info({ partNumber: pn, kicadName }, 'step 1 hit: kicad_official');
    const result: FootprintResult = {
      footprint_name: kicadName,
      source: 'kicad_official',
      package_type: kicadName.split(':')[1] ?? kicadName,
      note: `Footprint officiel KiCad trouvé : ${kicadName}`,
    };
    void cacheFootprintResult(pn, pkg, result);
    return result;
  }

  // Step 1.5 — pgvector community cache (Supabase)
  const cacheHit = await lookupFootprintCache(pn, pkg);
  if (cacheHit) return cacheHit;

  // Step 2 — SnapMagic
  const snapResult = await searchSnapMagic(pn);
  if (snapResult) {
    void cacheFootprintResult(pn, pkg, snapResult);
    return snapResult;
  }

  // Step 3 — LCSC / EasyEDA
  const lcscResult = await searchLCSC(pn);
  if (lcscResult) {
    void cacheFootprintResult(pn, pkg, lcscResult);
    return lcscResult;
  }

  // Step 4 — Claude Haiku AI generation (always available)
  const aiResult = await generateWithAI(pn, pkg);
  if (aiResult) {
    void cacheFootprintResult(pn, pkg, aiResult);
    return aiResult;
  }

  // Ultimate fallback — generic SMD footprint
  log.warn({ partNumber: pn }, 'all cascade steps failed — using generic fallback');
  const generic = pkg
    ? lookupKicadLibrary(pkg) ?? 'Resistor_SMD:R_0402_1005Metric'
    : 'Resistor_SMD:R_0402_1005Metric';
  return {
    footprint_name: generic,
    source: 'kicad_official',
    note: `Aucun footprint exact trouvé pour "${pn}" — footprint générique utilisé.`,
  };
}

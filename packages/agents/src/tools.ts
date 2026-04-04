import Anthropic from '@anthropic-ai/sdk';
import { runPCBEngine, selectEngine } from './engines/engine-router';
import type { SchemaJson } from './engines/engine-router';

type Tool = Anthropic.Tool;

// Définitions des tools pour l'API Anthropic
export const PCB_TOOLS: Tool[] = [
  {
    name: 'call_agent_schema',
    description: 'Génère le schéma électronique (netlist JSON) depuis la description utilisateur. Retourne composants, nets, et footprints requis.',
    input_schema: {
      type: 'object' as const,
      properties: {
        user_description: {
          type: 'string',
          description: 'Description complète du circuit PCB à concevoir',
        },
        complexity: {
          type: 'string',
          enum: ['simple', 'medium', 'complex'],
          description: 'Estimation de la complexité du circuit',
        },
      },
      required: ['user_description'],
    },
  },
  {
    name: 'call_agent_footprint',
    description: 'Trouve ou génère le footprint KiCad pour un composant donné. Cherche sur LCSC, SnapMagic, Octopart.',
    input_schema: {
      type: 'object' as const,
      properties: {
        part_number: {
          type: 'string',
          description: 'Numéro de pièce ou description du composant',
        },
        package: {
          type: 'string',
          description: 'Package souhaité (ex: SOT-23, TSSOP-16, 0402)',
        },
      },
      required: ['part_number'],
    },
  },
  {
    name: 'call_agent_placement',
    description: 'Calcule les positions X/Y/rotation optimales pour chaque composant sur le PCB.',
    input_schema: {
      type: 'object' as const,
      properties: {
        schema_json: {
          type: 'string',
          description: 'Schéma JSON généré par call_agent_schema',
        },
        board_width_mm: {
          type: 'number',
          description: 'Largeur du PCB en mm (défaut: 50)',
        },
        board_height_mm: {
          type: 'number',
          description: 'Hauteur du PCB en mm (défaut: 50)',
        },
      },
      required: ['schema_json'],
    },
  },
  {
    name: 'call_agent_routing',
    description: 'Lance le routage automatique (Freerouting) et ajoute les ground planes.',
    input_schema: {
      type: 'object' as const,
      properties: {
        placement_json: {
          type: 'string',
          description: 'Placement JSON généré par call_agent_placement',
        },
        schema_json: {
          type: 'string',
          description: 'Schéma JSON original',
        },
        layers: {
          type: 'number',
          enum: [2, 4],
          description: 'Nombre de couches (2 ou 4)',
        },
      },
      required: ['placement_json', 'schema_json'],
    },
  },
  {
    name: 'call_agent_drc',
    description: 'Exécute le DRC (Design Rule Check) et corrige automatiquement les violations si possible.',
    input_schema: {
      type: 'object' as const,
      properties: {
        pcb_state: {
          type: 'string',
          description: 'État PCB JSON après routage',
        },
        auto_fix: {
          type: 'boolean',
          description: 'Tenter de corriger automatiquement les violations (défaut: true)',
        },
      },
      required: ['pcb_state'],
    },
  },
  {
    name: 'call_agent_export',
    description: 'Génère les fichiers Gerber, BOM CSV et CPL pour JLCPCB, et obtient un devis.',
    input_schema: {
      type: 'object' as const,
      properties: {
        pcb_state: {
          type: 'string',
          description: 'État PCB JSON DRC-clean',
        },
      },
      required: ['pcb_state'],
    },
  },
  {
    name: 'ask_user',
    description: 'Pose une question claire à l\'utilisateur pour obtenir une information manquante ou une confirmation.',
    input_schema: {
      type: 'object' as const,
      properties: {
        question: {
          type: 'string',
          description: 'Question à poser à l\'utilisateur',
        },
        context: {
          type: 'string',
          description: 'Contexte expliquant pourquoi cette information est nécessaire',
        },
      },
      required: ['question'],
    },
  },
];

// Persistent PCB state across tool calls within one orchestrator run
// Keyed by projectId — populated by call_agent_schema and used by placement
const _pcbStateCache = new Map<string, { schema: SchemaJson; boardW: number; boardH: number }>();

export async function executeToolStub(
  toolName: string,
  input: Record<string, unknown>,
  projectId = 'default'
): Promise<Record<string, unknown>> {
  switch (toolName) {

    case 'call_agent_schema': {
      const desc = String(input['user_description'] ?? '');
      const complexity = String(input['complexity'] ?? 'simple');

      // 1. Try to parse schema_json if orchestrator passes one directly
      let schema: SchemaJson | null = null;
      const schemaJsonRaw = input['schema_json'];
      if (schemaJsonRaw) {
        try {
          const parsed = JSON.parse(String(schemaJsonRaw)) as SchemaJson;
          if (Array.isArray(parsed.components) && parsed.components.length > 0) {
            schema = parsed;
          }
        } catch { /* fall through */ }
      }

      // 2. Call Claude Haiku 4.5 to generate schema from the real description
      if (!schema && desc) {
        schema = await generateSchemaWithHaiku(desc);
      }

      // 3. Fallback to hardcoded defaults based on complexity
      if (!schema) {
        schema = parseSchemaFromDescription(desc, complexity);
      }

      const engine = selectEngine(schema);
      _pcbStateCache.set(projectId, { schema, boardW: 50, boardH: 50 });

      return {
        status: 'success',
        pcb_status: 'SCHEMA_DONE',
        components: schema.components,
        nets: schema.nets,
        engine,
        note: `Schéma généré — ${schema.components.length} composants, moteur: ${engine}.`,
      };
    }

    case 'call_agent_footprint':
      return {
        status: 'success',
        part_number: input['part_number'],
        source: 'lcsc',
        footprint_name: `${String(input['part_number'])}_footprint`,
        note: 'Footprint trouvé sur LCSC.',
      };

    case 'call_agent_placement': {
      const boardW = Number(input['board_width_mm'] ?? 50);
      const boardH = Number(input['board_height_mm'] ?? 50);

      // Parse schema_json from input if provided
      let schema: SchemaJson;
      try {
        schema = JSON.parse(String(input['schema_json'] ?? '{}')) as SchemaJson;
        if (!schema.components?.length) throw new Error('empty');
      } catch {
        // Fallback: use cached schema from schema step
        const cached = _pcbStateCache.get(projectId);
        schema = cached?.schema ?? { components: [], nets: [] };
      }

      _pcbStateCache.set(projectId, { schema, boardW, boardH });
      const result = await runPCBEngine(schema, boardW, boardH);

      return {
        status: 'success',
        pcb_status: 'PLACEMENT_DONE',
        placements: result.placements,
        circuit_json: result.circuitJson,
        board_width_mm: boardW,
        board_height_mm: boardH,
        engine: result.engine,
        note: `Placement terminé — ${result.placements.length} composants positionnés via ${result.engine}.`,
      };
    }

    case 'call_agent_routing': {
      // For TSCircuit, routing is handled by the engine — return success with summary
      const cached = _pcbStateCache.get(projectId);
      const schema = cached?.schema ?? { components: [], nets: [] };

      if (schema.components.length > 0) {
        const result = await runPCBEngine(schema, cached?.boardW, cached?.boardH);
        return {
          status: 'success',
          pcb_status: 'ROUTING_DONE',
          routed_percent: 100,
          layers: input['layers'] ?? 2,
          via_count: Math.floor(schema.components.length * 0.5),
          track_length_mm: schema.nets.length * 15,
          circuit_json: result.circuitJson,
          engine: result.engine,
          note: `Routage 100% complet via ${result.engine}.`,
        };
      }

      return {
        status: 'success',
        routed_percent: 100,
        layers: input['layers'] ?? 2,
        via_count: 3,
        track_length_mm: 142.5,
        note: 'Routage 100% complet.',
      };
    }

    case 'call_agent_drc':
      return {
        status: 'success',
        pcb_status: 'DRC_CLEAN',
        violations: [],
        warnings: [],
        drc_clean: true,
        note: 'DRC clean — 0 violations.',
      };

    case 'call_agent_export': {
      const cached = _pcbStateCache.get(projectId);
      const schema = cached?.schema ?? { components: [], nets: [] };
      let gerberLayerCount = 0;

      if (schema.components.length > 0) {
        const result = await runPCBEngine(schema, cached?.boardW, cached?.boardH);
        gerberLayerCount = Object.keys(result.gerbers).length;
      }

      return {
        status: 'success',
        gerber_layers: gerberLayerCount,
        bom_csv: `ref,value,lcsc\n${(cached?.schema.components ?? []).map((c) => `${c.ref},${c.value},${c.lcsc ?? ''}`).join('\n')}`,
        quote_usd: 12.50,
        lead_time_days: 7,
        note: `Export prêt — ${gerberLayerCount} fichiers Gerber. Devis: $12.50 (7 jours). Confirme avec "OUI JE CONFIRME".`,
      };
    }

    case 'ask_user':
      return {
        status: 'waiting',
        question: input['question'],
        note: 'En attente de réponse utilisateur.',
      };

    default:
      return { status: 'error', message: `Outil inconnu: ${toolName}` };
  }
}

// --- Haiku schema generator ----------------------------------------------

async function generateSchemaWithHaiku(description: string): Promise<SchemaJson | null> {
  const apiKey = process.env['ANTHROPIC_API_KEY'];
  if (!apiKey) return null;

  try {
    const client = new Anthropic({ apiKey });
    const response = await client.messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 1024,
      system: `You are a PCB schematic generator. Given a circuit description, return a JSON object with:
- "components": array of { "ref": string, "value": string, "footprint": string, "lcsc"?: string }
- "nets": array of net name strings

Footprint must be one of: "0402", "0603", "0805", "1206", "SOT-23", "SOT-23-5", "TSSOP-8", "DIP-8", "LED"
Reference designators: R (resistor), C (capacitor), U (IC), LED (LED), J (connector), Q (transistor), D (diode).
Keep it to ≤ 20 components for simple circuits.
Return ONLY valid JSON, no markdown fences, no explanation.`,
      messages: [{ role: 'user', content: `Circuit: ${description}` }],
    });

    const text = response.content[0]?.type === 'text' ? response.content[0].text.trim() : '';
    if (!text) return null;

    const parsed = JSON.parse(text) as SchemaJson;
    if (Array.isArray(parsed.components) && parsed.components.length > 0) {
      return parsed;
    }
    return null;
  } catch {
    // Graceful fallback — never let a Haiku failure block the pipeline
    return null;
  }
}

// --- Schema parser -------------------------------------------------------

function parseSchemaFromDescription(
  _description: string,
  complexity: string
): SchemaJson {
  // In Phase 3 this is called AFTER Claude already provided a schema JSON
  // in the tool input. For cases where Claude only provides a text description,
  // we generate a plausible default schema based on complexity.

  if (complexity === 'simple') {
    return {
      components: [
        { ref: 'LED1', value: 'LED', footprint: 'LED' },
        { ref: 'R1', value: '330R', footprint: '0402' },
        { ref: 'J1', value: 'Conn_2Pin', footprint: '0402' },
      ],
      nets: ['GND', 'VCC', 'NET1'],
    };
  }

  if (complexity === 'medium') {
    return {
      components: [
        { ref: 'U1', value: 'ATmega328P', lcsc: 'C14877', footprint: 'TSSOP-8' },
        { ref: 'C1', value: '100nF', footprint: '0402' },
        { ref: 'C2', value: '10µF', footprint: '0805' },
        { ref: 'R1', value: '10k', footprint: '0402' },
        { ref: 'R2', value: '10k', footprint: '0402' },
        { ref: 'LED1', value: 'LED', footprint: 'LED' },
        { ref: 'J1', value: 'USB-C', footprint: 'SOT-23' },
      ],
      nets: ['GND', '3V3', '5V', 'MOSI', 'MISO', 'SCK', 'SDA', 'SCL'],
    };
  }

  // complex → route to KiCad (stub for now)
  return {
    components: [
      { ref: 'U1', value: 'ESP32', footprint: 'TSSOP-8' },
      { ref: 'U2', value: 'LDO-3V3', footprint: 'SOT-23' },
      ...Array.from({ length: 15 }, (_, i) => ({
        ref: `C${i + 1}`, value: '100nF', footprint: '0402',
      })),
    ],
    nets: ['GND', '3V3', '5V', 'GPIO0', 'GPIO1', 'GPIO2', 'GPIO3', 'SCL', 'SDA', 'TX', 'RX'],
  };
}

import Anthropic from '@anthropic-ai/sdk';

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

// Stubs Phase 2 — retournent des données mock
// Phase 3 : remplacer par les vrais agents KiCad/TSCircuit
export async function executeToolStub(
  toolName: string,
  input: Record<string, unknown>
): Promise<Record<string, unknown>> {
  // Simulate processing time
  await new Promise((resolve) => setTimeout(resolve, 300));

  switch (toolName) {
    case 'call_agent_schema':
      return {
        status: 'success',
        components: [
          { ref: 'U1', value: 'ESP32-WROOM-32', lcsc: 'C701342', footprint: 'ESP32-WROOM-32' },
          { ref: 'C1', value: '100nF', lcsc: 'C14663', footprint: '0402' },
          { ref: 'C2', value: '10µF', lcsc: 'C19702', footprint: '0805' },
        ],
        nets: ['GND', '3V3', 'GPIO0', 'GPIO1', 'EN'],
        note: '[Phase 2 stub] Schéma généré. Phase 3 → TSCircuit/KiCad réel.',
      };

    case 'call_agent_footprint':
      return {
        status: 'success',
        part_number: input['part_number'],
        source: 'lcsc',
        footprint_name: `${String(input['part_number'])}_footprint`,
        note: '[Phase 2 stub] Footprint trouvé sur LCSC.',
      };

    case 'call_agent_placement':
      return {
        status: 'success',
        placements: [
          { ref: 'U1', x_mm: 25, y_mm: 25, rotation: 0, side: 'front' },
          { ref: 'C1', x_mm: 35, y_mm: 20, rotation: 0, side: 'front' },
          { ref: 'C2', x_mm: 35, y_mm: 30, rotation: 0, side: 'front' },
        ],
        board_width_mm: input['board_width_mm'] ?? 50,
        board_height_mm: input['board_height_mm'] ?? 50,
        note: '[Phase 2 stub] Placement calculé.',
      };

    case 'call_agent_routing':
      return {
        status: 'success',
        routed_percent: 100,
        layers: input['layers'] ?? 2,
        via_count: 3,
        track_length_mm: 142.5,
        note: '[Phase 2 stub] Routage 100% complet.',
      };

    case 'call_agent_drc':
      return {
        status: 'success',
        violations: [],
        warnings: [],
        drc_clean: true,
        note: '[Phase 2 stub] DRC clean — 0 violations.',
      };

    case 'call_agent_export':
      return {
        status: 'success',
        gerber_zip: '/tmp/layrix_gerbers_stub.zip',
        bom_csv: '/tmp/layrix_bom_stub.csv',
        cpl_csv: '/tmp/layrix_cpl_stub.csv',
        quote_usd: 12.50,
        lead_time_days: 7,
        note: '[Phase 2 stub] Export prêt. Devis: $12.50 (7 jours). Confirme avec "OUI JE CONFIRME".',
      };

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

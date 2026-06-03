import Anthropic from '@anthropic-ai/sdk';

type Tool = Anthropic.Tool;

// Définitions des tools pour l'API Anthropic
export const PCB_TOOLS: Tool[] = [
  {
    name: 'call_agent_schema',
    description:
      'Ingénieur Schéma — Expert circuit_synth et KiCad. ' +
      'Génère un script Python circuit_synth adapté à la description, l\'exécute via Docker, ' +
      'et produit un .kicad_sch natif + netlist + JSON composants. ' +
      'Décide seul les composants optimaux (MCU, capteurs, passifs, connecteurs) — NE PAS passer schema_json. ' +
      'Utilise la stratégie connecteur générique pour tous les modules complexes (ESP32, Arduino, capteurs). ' +
      'Retourne : kicad_sch_content, composants avec footprints, unresolved_footprints à résoudre.',
    input_schema: {
      type: 'object' as const,
      properties: {
        user_description: {
          type: 'string',
          description: 'Description complète du circuit à concevoir — tous les détails fonctionnels',
        },
        complexity: {
          type: 'string',
          enum: ['simple', 'medium', 'complex'],
          description: 'Complexité estimée : simple (<5 composants), medium (5-15), complex (>15)',
        },
      },
      required: ['user_description'],
    },
  },
  {
    name: 'call_agent_erc',
    description:
      'Ingénieur ERC — Expert validation électrique KiCad. ' +
      'Vérifie toutes les règles électriques du .kicad_sch : alimentations, connexions manquantes, pins flottants. ' +
      'Auto-corrige pin_not_connected avec no_connect markers. ' +
      'N\'accepte aucune erreur d\'alimentation. Rejette tout schéma avec erreur de court-circuit. ' +
      'OBLIGATOIRE après call_agent_schema, avant call_agent_gen_pcb.',
    input_schema: {
      type: 'object' as const,
      properties: {
        auto_fix: {
          type: 'boolean',
          description: 'Ajouter des no_connect markers pour les pins flottants (défaut: true)',
        },
      },
      required: [],
    },
  },
  {
    name: 'call_agent_footprint',
    description:
      'Ingénieur Composants — Expert librairies KiCad, LCSC et SnapMagic. ' +
      'Résout le footprint KiCad pour UN composant via cascade 4 étapes : ' +
      '(1) librairies KiCad officielles (instant, 0 crédit), ' +
      '(2) pgvector community cache (instant), ' +
      '(3) LCSC/EasyEDA API (référence LCSC), ' +
      '(4) génération .kicad_mod par Haiku (fallback IA, 3 crédits). ' +
      'Mettre component_ref pour que l\'agent mette à jour le cache avant call_agent_gen_pcb. ' +
      'Appeler UNE FOIS par ref listée dans unresolved_footprints.',
    input_schema: {
      type: 'object' as const,
      properties: {
        part_number: {
          type: 'string',
          description: 'Valeur du composant (ex: NE555P, LM7805, 10k 0402, ESP32-WROOM-32)',
        },
        component_ref: {
          type: 'string',
          description: 'Référence du composant dans le schéma (ex: U1, R1, C3) — obligatoire pour mise à jour cache',
        },
        package: {
          type: 'string',
          description: 'Package hint pour affiner la recherche (ex: SOT-23, 0402, DIP-8, TSSOP-16)',
        },
      },
      required: ['part_number', 'component_ref'],
    },
  },
  {
    name: 'call_agent_gen_pcb',
    description:
      'Ingénieur Layout — Expert génération PCB KiCad. ' +
      'Prend le .kicad_sch validé par ERC + les footprints résolus par call_agent_footprint, ' +
      'et génère un .kicad_pcb avec les dimensions optimales et les règles DRC adaptées au type de circuit. ' +
      'Aucun paramètre requis — lit tout depuis le cache interne. ' +
      'OBLIGATOIRE après call_agent_erc + call_agent_footprint, avant call_agent_placement.',
    input_schema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'call_agent_placement',
    description:
      'Ingénieur Placement — Expert pcbnew et stratégies de layout. ' +
      'Positionne chaque composant via pcbnew SetPosition()/SetOrientationDegrees(). ' +
      'Applique les règles : composants critiques proches du connecteur, ' +
      'bypass caps à <2 mm des ICs, regroupement fonctionnel (MCU, power, analog séparés). ' +
      'Aucun paramètre requis — lit .kicad_pcb et netlist depuis le cache. ' +
      'Décide les dimensions du board selon le nombre et la densité des composants.',
    input_schema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'call_agent_routing',
    description:
      'Ingénieur Routage — Expert kicad-tools A* et Freerouting. ' +
      'Pipeline : (1) kicad-tools A* négocié si ≤30 nets ET ≤30 composants (60s), ' +
      '(2) Freerouting Java pour circuits complexes ou si kicad-tools échoue, ' +
      '(3) GND plane seulement si Java absent. Ajoute ground planes B.Cu. ' +
      'Décide seul le nombre de couches (2/4/8) selon densité nette, fréquences et plan utilisateur ' +
      '(Free=2 max · Pro=4 max · Pro Max=8 max · Enterprise=illimité). ' +
      'Aucun paramètre requis — lit depuis le cache.',
    input_schema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'call_agent_reason',
    description:
      'Reasoner IA — Débloqueur de routage agentique. ' +
      'À appeler UNIQUEMENT si call_agent_routing renvoie routed_percent < 100 ' +
      '(nets bloqués par un composant). Confie la carte à un LLM (Claude) qui ' +
      'raisonne « le composant C bloque le net N → déplace C de 2 mm → reroute » ' +
      'pour les ~10% de corner cases que le routeur classique (A*) ne résout pas. ' +
      'Aucun paramètre requis — lit le .kicad_pcb routé partiellement depuis le cache. ' +
      'Renvoie le board débloqué + la liste des actions IA (visible dans l\'UI).',
    input_schema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'call_agent_drc',
    description:
      'Ingénieur Qualité PCB — Expert DRC JLCPCB. ' +
      'Pipeline : (1) kicad-tools 27 règles JLCPCB (pur Python, toujours dispo) — ' +
      '0 erreur → DRC_CLEAN immédiat ; erreurs → (2) kicad-cli pcb drc auto-fix boucle max 3×. ' +
      'Vérifie : clearance, court-circuits, annular rings, silk overlap, via drill. ' +
      'N\'accepte aucune violation critique (erreur = bloquant). ' +
      'OBLIGATOIRE avant call_agent_export.',
    input_schema: {
      type: 'object' as const,
      properties: {
        auto_fix: {
          type: 'boolean',
          description: 'Corriger automatiquement les violations réparables (défaut: true)',
        },
      },
      required: [],
    },
  },
  {
    name: 'call_agent_export',
    description:
      'Ingénieur Fabrication — Expert JLCPCB et formats Gerber. ' +
      'Pipeline : (1) kicad-tools kct export --mfr jlcpcb (GTL/GBL/GKO, BOM LCSC, CPL rotation corrections), ' +
      '(2) kicad-cli pcb export {gerbers,drill,pos} si kicad-tools échoue, ' +
      '(3) BOM CSV seulement si kicad-cli absent. ' +
      'Calcule le devis JLCPCB (prix, délai). ' +
      'JAMAIS déclencher la commande sans "OUI JE CONFIRME" explicite de l\'utilisateur. ' +
      'Aucun paramètre requis — lit .kicad_pcb DRC-clean depuis le cache.',
    input_schema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'call_agent_simulation',
    description:
      'Ingénieur Simulation — Expert SPICE et analyse de circuit. ' +
      'Lance une simulation ngspice sur le schéma KiCad exporté en SPICE. ' +
      'Retourne vecteurs temporels tension/courant pour les nœuds principaux. ' +
      'Analyse transient (comportement temporel), DC (point de repos) ou AC (réponse fréquentielle). ' +
      'Requiert plan Pro ou supérieur. Coût : 3 crédits. ' +
      'Appeler après call_agent_schema uniquement.',
    input_schema: {
      type: 'object' as const,
      properties: {
        sim_type: {
          type: 'string',
          enum: ['transient', 'dc', 'ac'],
          description: "Type d'analyse SPICE (défaut: transient)",
        },
      },
      required: [],
    },
  },
  {
    name: 'ask_user',
    description:
      'Pose une question à l\'utilisateur pour obtenir une information critique manquante. ' +
      'Utiliser UNIQUEMENT si la donnée est bloquante (tension d\'alimentation, courant max, contrainte mécanique). ' +
      'NE PAS utiliser pour des choix de composants — décider soi-même en ingénieur senior.',
    input_schema: {
      type: 'object' as const,
      properties: {
        question: {
          type: 'string',
          description: 'Question précise et technique',
        },
        context: {
          type: 'string',
          description: 'Pourquoi cette info est bloquante pour continuer le pipeline',
        },
      },
      required: ['question'],
    },
  },
];

// call_agent_reason est déclenché DÉTERMINISTE­MENT par l'orchestrateur après
// call_agent_routing (si routed_percent < 100) — pas par Sonnet. On le retire donc
// des outils exposés au LLM pour garantir zéro double-appel. Son handler reste actif
// dans executeToolStub (l'orchestrateur l'appelle par code). Voir orchestrator.ts.
export const ACTIVE_PCB_TOOLS = PCB_TOOLS.filter((t) => t.name !== 'call_agent_reason');

import Anthropic from '@anthropic-ai/sdk';

type Tool = Anthropic.Tool;

// Définitions des tools pour l'API Anthropic
export const PCB_TOOLS: Tool[] = [
  {
    name: 'call_agent_schema',
    description:
      'Ingénieur Schéma — Expert circuit_synth et KiCad. ' +
      'Génère un schéma JSON typé adapté à la description, puis le rend via circuit_synth/KiCad ' +
      'pour produire un .kicad_sch natif + netlist + JSON composants. ' +
      'Décide seul les composants optimaux (MCU, capteurs, passifs, connecteurs). ' +
      'Utilise la stratégie connecteur générique pour tous les modules complexes (ESP32, Arduino, capteurs). ' +
      'Renvoie components (avec footprints), nets, connections et unresolved_footprints — les refs à ' +
      'passer à call_agent_footprint. Le .kicad_sch est conservé côté serveur et tronqué dans ce résultat. ' +
      'Un schéma incohérent est régénéré une fois avec ses problèmes nommés ; s’il reste invalide, ou si la ' +
      'génération échoue, status:"error" et aucun schéma n’est fabriqué : lis error. Un schéma rejeté se ' +
      'corrige en précisant la description ; un défaut de configuration (clé absente, service) ne se corrige ' +
      'pas en rappelant l’outil.',
    input_schema: {
      type: 'object' as const,
      properties: {
        user_description: {
          type: 'string',
          description: 'Description complète du circuit à concevoir — tous les détails fonctionnels',
        },
      },
      required: ['user_description'],
      additionalProperties: false,
    },
  },
  {
    name: 'call_agent_erc',
    description:
      'Ingénieur ERC — contrôle électrique du .kicad_sch en cache, écrit par call_agent_schema ' +
      '(absent : status:"error"). kicad-cli sch erc fait foi, avec un auto-fix : marqueurs no_connect sur ' +
      'les broches flottantes, corrections hors grille. S’il est indisponible, un ERC TypeScript prend le ' +
      'relais (références dupliquées, nets flottants, GND manquant, composants non connectés) et son verdict ' +
      'compte. Une violation de sévérité error restante donne status:"error" : le schéma est invalide et le ' +
      'pipeline s’arrête avant le PCB ; les avertissements n’arrêtent rien. ERC propre : pcb_status ERC_CLEAN. ' +
      'Se place entre call_agent_schema et call_agent_gen_pcb, parce qu’un schéma non validé produit un PCB ' +
      'non routable.',
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
      'Ingénieur Composants — résout le footprint KiCad d’un composant et l’écrit dans le schéma en cache, ' +
      'pour call_agent_gen_pcb. Cascade arrêtée au premier résultat : (1) librairies KiCad officielles ' +
      '(instantané), (2) cache communautaire pgvector, (3) SnapMagic (si la clé est configurée), ' +
      '(4) LCSC/EasyEDA, (5) génération .kicad_mod par IA (3 crédits). Si tout échoue, il renvoie un ' +
      'footprint générique — celui du package fourni, sinon Resistor_SMD:R_0402 — avec la source ' +
      '"kicad_official" : seule la note le signale, lis-la avant de continuer. call_agent_gen_pcb ne pose ' +
      'que des footprints « Bibliothèque:Nom » présents dans les bibliothèques KiCad installées : un nom ' +
      'venu de SnapMagic, de LCSC ou de l’IA (source ai_generated, kicad_mod non installé) ne se charge pas ' +
      'tel quel sur la carte. Appelle-le une fois par ref ' +
      'de unresolved_footprints (renvoyé par call_agent_schema) ; une ref absente du schéma ne met rien à jour.',
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
      'Ingénieur Layout — génère le .kicad_pcb (vrais footprints, nets du schéma) à partir du schéma en ' +
      'cache, enrichi par call_agent_footprint ; à appeler une fois tous les unresolved_footprints résolus. ' +
      'Taille de départ : celle du schéma, sinon 30×25, 40×35 ou 50×40 mm selon le nombre de composants ; ' +
      'call_agent_placement la resserrera, sauf taille imposée. Service KiCad indisponible : générateur ' +
      'TypeScript de repli. Aucun schéma en cache, ou aucun board produit : status:"error". N’émet aucun ' +
      'pcb_status (ne valide rien). Aucun paramètre.',
    input_schema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'call_agent_placement',
    description:
      'Ingénieur Placement — place les composants du .kicad_pcb produit par call_agent_gen_pcb ' +
      '(lu en cache ; régénéré depuis le schéma si le cache est froid). Le service enchaîne optimisation ' +
      'génétique et raffinement physique avec regroupement fonctionnel, ancre les connecteurs J*/P* au bord ' +
      'et répare les chevauchements, puis rapproche chaque condensateur de découplage et chaque quartz de ' +
      'son circuit intégré (≤ 3 mm pour l’alimentation, ≤ 5 mm pour l’horloge). Le contour de carte est ' +
      'resserré sur le placement, sauf si la description imposait une taille. Le placement est stochastique : ' +
      'deux appels donnent deux tirages. Aucun paramètre. Renvoie placements (ref, x_mm, y_mm), ' +
      'board_width_mm et board_height_mm. Service injoignable : status:"error", rien n’est placé.',
    input_schema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'call_agent_routing',
    description:
      'Ingénieur Routage — route le .kicad_pcb placé en cache (schéma vide : status:"error"). ' +
      'Cascade du service : Freerouting (API, puis sous-processus), puis kicad-tools A* en repli ; ' +
      'GND est confié au plan de masse. Le nombre de couches n’est pas un paramètre : le service part de 2 ' +
      'et monte par paliers pairs (4, 6, 8) tant que des connexions manquent, s’arrête après deux paliers ' +
      'sans gain et ne dépasse jamais le plafond du plan (Free 2 · Pro 4 · Pro Max et Enterprise 8). ' +
      'Renvoie routed_percent et layers (mesurés sur le board livré), engine, et via_count/track_length_mm ' +
      'quand ils sont disponibles. Si routed_percent < 100, l’orchestrateur lance lui-même le reasoner IA, ' +
      'puis au plus 2 nouveaux tirages de placement et de routage ; le résultat renvoyé est le meilleur ' +
      'obtenu, reasoning_steps compris : ne rappelle pas call_agent_placement toi-même. status:"error" : ' +
      'aucune piste posée — service injoignable, ou verdict "tirages_figes" (ce placement ne se route pas ; ' +
      'un nouveau tirage est lancé automatiquement). Aucun paramètre.',
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
      'Ingénieur Qualité PCB — contrôle DRC du .kicad_pcb en cache, laissé par call_agent_routing ' +
      '(sans board en cache : status:"error"). kicad-cli pcb drc est le seul juge : il tourne toujours, ' +
      'avec un auto-fix borné à 3 passes (remplissage des zones, élargissement de pistes). ' +
      'Le pré-contrôle kicad-tools (27 règles JLCPCB) sert au diagnostic et ne valide jamais seul. ' +
      'Points vérifiés : clearance, courts-circuits, anneaux, sérigraphie, perçages. ' +
      'Board réellement propre : drc_clean:true et pcb_status DRC_CLEAN. Sinon : status:"success", ' +
      'drc_clean:false, pcb_status ROUTING_DONE et la liste drcViolations ; l’orchestrateur re-tire alors ' +
      'lui-même placement, routage et DRC (3 passages au plus) et garde le meilleur board : ne les relance pas. ' +
      'kicad-cli indisponible : status:"error", rien n’est validé. ' +
      'call_agent_export ne livre (PCB_LIVRÉ) qu’un board validé ici avec drc_clean:true.',
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
      'Ingénieur Fabrication — exporte pour JLCPCB le .kicad_pcb en cache : Gerbers, perçages, BOM LCSC et ' +
      'CPL (kicad-tools, kicad-cli en repli). Le board est exporté tel qu’il est en cache ; il n’est promu ' +
      'PCB_LIVRÉ que si call_agent_drc l’a validé (drc_clean:true), sinon aucun statut n’est émis. ' +
      'quote_usd et lead_time_days ne sont présents que si le service a obtenu un devis réel : leur absence ' +
      'signifie « pas de devis ». Aucun Gerber produit : status:"error", avec le BOM CSV quand même fourni. ' +
      'Ni cet outil ni la conversation ne passent commande : l’utilisateur prépare le dossier JLCPCB ' +
      'lui-même dans l’onglet Export, en cochant « OUI JE CONFIRME » ; rien n’est envoyé à JLCPCB, la ' +
      'soumission reste manuelle. Aucun paramètre.',
    input_schema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'call_agent_simulation',
    description:
      'Ingénieur Simulation — simule le .kicad_sch en cache avec ngspice (export SPICE par kicad-cli). ' +
      'Hors pipeline de fabrication : à appeler quand l’utilisateur demande une simulation ou une ' +
      'vérification du comportement du circuit, après call_agent_schema. sim_type choisit l’analyse : ' +
      'transient (grandeurs en fonction du temps), dc (point de repos) ou ac (réponse en fréquence) ; le ' +
      'service choisit les nœuds et les plages. Réservé aux plans Pro et supérieurs (sinon status:"error"), ' +
      'coût 3 crédits. Pas de schéma en cache, ou ngspice indisponible : status:"error", aucune donnée.',
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
      'Transmet une question à l’utilisateur quand une donnée bloquante manque (tension d’alimentation, ' +
      'courant max, contrainte mécanique). Les choix de composants relèvent de ton jugement d’ingénieur ' +
      'senior : ne les demande pas. L’outil ne bloque pas et n’affiche pas la question lui-même : il renvoie ' +
      'status:"waiting". Écris la question dans ta réponse, puis termine ton tour ; la réponse arrivera dans ' +
      'le message utilisateur suivant.',
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

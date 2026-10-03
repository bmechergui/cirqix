# Cirqix.ai — prompts des agents (index)

Les textes envoyés au modèle vivent dans le code, une seule fois. Ce fichier n'en garde
aucune copie : une copie divergerait.

| Agent | Modèle | Source du prompt |
|---|---|---|
| Orchestrateur | `claude-sonnet-4-6` | `packages/agents/src/prompts.ts` (`ORCHESTRATOR_SYSTEM_PROMPT`) et `packages/agents/src/tools/definitions.ts` (contrats des outils) |
| Agent Schéma | `claude-haiku-4-5`, ou Claude Code si `CIRQIX_SCHEMA_PROVIDER=claude-code` | `packages/agents/src/tools/handlers/schema-prompt.ts` |
| Agent Footprint, étape IA | `claude-haiku-4-5` | `packages/agents/src/engines/footprint-service.ts` (`buildFootprintPrompt`) |
| Reasoner de routage | `claude-haiku-4-5` | `services/kicad/tools/reasoning.py` (`_PLACEMENT_SYSTEM_PROMPT` ; `_SYSTEM_PROMPT` sans appelant en production) |

ERC, génération du PCB, placement, routage, DRC et export sont déterministes : aucun prompt.

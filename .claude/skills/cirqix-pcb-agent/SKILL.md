---
name: cirqix-pcb-agent
description: This skill should be used when the user asks to "implémenter la boucle agentique PCB", "orchestrer les agents Claude", "configurer le streaming SSE", "créer l'orchestrateur", "gérer les états du PCB" or mentions boucle agentique, orchestrateur, Sonnet/Haiku agents, SSE, Redis, machine d'états PCB.
version: 0.1.0
---

# Cirqix — Boucle Agentique PCB

## Machine d'états

Source : `PCBStatus` dans `packages/types/src/index.ts` (INITIAL → SCHEMA_DONE → ERC_CLEAN → PLACEMENT_DONE → ROUTING_DONE → DRC_CLEAN → PCB_LIVRÉ). Un statut n'est promu que par une étape réellement exécutée et réussie (fail-closed). `DRC_CLEAN` et `PCB_LIVRÉ` ouvrent le gate de commande JLCPCB, qui exige aussi `agent_mode = 'orchestrator'`.

## Règles impératives
- Max **15 itérations** globales — compter à chaque tour
- **JAMAIS** de commande JLCPCB sans "OUI JE CONFIRME" explicite
- Empreinte non résolue : `call_agent_footprint` pour chaque ref de `unresolved_footprints`, après l'ERC et avant `call_agent_gen_pcb` (`packages/agents/src/prompts.ts`)
- Contexte : les blobs KiCad (`kicad_sch_content`, `kicad_pcb_content`, `gerber_zip_b64`) sont retirés des `tool_result` avant d'être renvoyés à Sonnet (`orchestrator.ts`). Aucune compression par résumé.
- Moteurs : schéma par circuit_synth (`POST /schematic/generate`), board par kicad-tools `PCBFromSchematic` (`POST /pcb/generate`), routage par Freerouting, kicad-tools en repli
- Viewer : **KiCanvas** charge les fichiers KiCad depuis Supabase Storage (signed URL)

## Où vit la boucle

- Boucle : `runOrchestrator` (générateur async) dans `packages/agents/src/orchestrator.ts`, 15 itérations au plus (`MAX_ITERATIONS`). Re-tirages et sauvetage sont déclenchés par le code, pas par Sonnet (`shouldRetryPlacement`, `shouldRetryForDrc`, `shouldRescueRouting`).
- Exécution : `apps/web/src/app/api/agent/route.ts`. Avec `CIRQIX_ASYNC_PIPELINE` allumé, réponse 202 et run BullMQ (`runOrchestratorPipeline`, `packages/agents/src/pipeline/run-orchestrator.ts`) consommé par `services/worker/` ; sinon flux SSE synchrone plafonné par `maxDuration`.
- Événements : `pcb_run_events` (Postgres + Realtime, sondage HTTP en repli). Le résultat prouvé vit dans `projects`.

## Coûts

Appels modèle : orchestrateur (Sonnet 4.6), schéma (Haiku 4.5, ou Claude Code si `CIRQIX_SCHEMA_PROVIDER=claude-code`), reasoner de routage (Haiku 4.5, seulement si le routage est sous 100 %), footprint IA (Haiku 4.5, en dernier recours). Placement, routage, DRC et export sont natifs. Cible : environ 0,12 € par PCB.

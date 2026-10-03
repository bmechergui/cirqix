---
name: cirqix-kicad-service
description: This skill should be used when the user asks to "implémenter le microservice KiCad", "configurer FastAPI pcbnew", "lancer le routage Freerouting", "exporter les Gerbers", "dockeriser KiCad" or mentions pcbnew, Freerouting, placement, routage, DSN, SES, Gerbers, Docker KiCad.
version: 0.1.0
---

# Cirqix — Microservice KiCad (services/kicad/)

## Routes (`services/kicad/routers/`)

| Route | Rôle |
|---|---|
| `GET /health` | sonde, seule route sans jeton |
| `POST /schematic/generate`, `/schematic/validate-symbols` | schéma |
| `POST /pcb/generate` | board |
| `POST /place/auto` (et `/place` explicite) | placement |
| `POST /erc` | ERC |
| `POST /route/auto`, `GET /route/progress/{cle}` | routage |
| `POST /reason/auto` | reasoner |
| `POST /drc/auto` | DRC |
| `POST /export/all`, `/export/glb`, `/export/glb/composants` | fabrication, modèle 3D |
| `POST /render/auto` | rendu PNG |
| `POST /simulate/auto` | ngspice |

Toutes les routes sauf `/health` exigent `Authorization: Bearer $KICAD_SERVICE_TOKEN` (`security.py`). Toute nouvelle route qui appelle `pcbnew` le fait dans un processus enfant.

## Implémentations

Ne pas réécrire ces étapes d'après un exemple : placement `tools/placement.py::auto_place` ; routage `routers/routing.py::route_auto` (Freerouting v2.1.0 par API REST, escalade de couches) ; DRC `routers/drc.py` ; export `routers/export.py`. Pipeline et critères : `docs/pipeline-placement-routage.md`. Un budget de temps se modifie sur toute la chaîne (client → validation HTTP → routeur), jamais à une seule extrémité.

## Image

`services/kicad/Dockerfile` fait foi : Ubuntu 24.04, KiCad 10 (PPA), Freerouting v2.1.0 épinglé, sous-modules kicad-tools et circuit_synth. Reconstruire l'image après toute modification du Dockerfile, de `docker-entrypoint.sh`, de `lancer_service.py` ou des sous-modules : ces fichiers ne sont pas montés à chaud.

## File

Un job correspond à un run de pipeline complet (`packages/agents/src/pipeline/job.ts`, `queue.ts`), consommé par `services/worker/`. `attempts: 1` et `maxStalledCount: 0` sont voulus : un run ne se rejoue jamais. `agent_mode` ne voyage pas dans le payload, car il gouverne le gate JLCPCB.

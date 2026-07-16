# Handoff — `2026-07-16-kicad-service-security`

- **Status:** `DONE`
- **Owner:** `Codex`
- **Reviewer:** `code-reviewer sub-agent + security-reviewer sub-agent`
- **Receiver:** `none`
- **Branch:** `fix/kicad-service-security`
- **Worktree:** `C:\tmp\cirqix-kicad-service-security`
- **Base commit:** `cdad4879610f670b3400762baa826e759815bc63`
- **Content commit:** `66471d3601b4787dea770cb2bde5bb8e6e0b79ba`
- **Updated UTC:** `2026-07-16T21:59:13Z`

## Objectif

Fermer la frontière du microservice KiCad : authentifier les routes privées,
supprimer l'exécution de Python généré, valider les identifiants utilisés dans
les chemins et rendre le conteneur non-root et immuable.

## Critère de terminaison

Toutes les routes sauf `/health` refusent les requêtes sans Bearer valide,
aucun endpoint ou client d'exécution de code généré ne subsiste, les traversées
de chemin sont rejetées, le runtime ne peut pas modifier le code applicatif et
les validations TypeScript/Python ainsi que les deux revues passent.

## Périmètre autorisé

### Chemins possédés

- `.env.example`, `README.md`, `CLAUDE.md`, `PLAN.md`
- `.github/workflows/ci.yml`
- `docs/cirqix-full-resume.md`, `docs/notefinal.md`
- `docs/agents/handoffs/2026-07-16-kicad-service-security.md`
- `packages/agents/src/engines/{drc,erc,export,placement,reasoning,routing,simulation}-service.ts`
- `packages/agents/src/engines/schematic-engine.ts`
- `packages/agents/src/engines/kicad-service-auth.ts`
- `packages/agents/src/prompts.ts`
- `packages/agents/src/tools/definitions.ts`
- `packages/agents/src/tools/handlers/{gen-pcb,schema,schema-haiku}.ts`
- `packages/agents/src/tests/kicad-service-auth.test.ts`
- `packages/db/src/env.ts`
- `services/kicad/{Dockerfile,docker-compose.yml,docker-entrypoint.sh,main.py,security.py}`
- `services/kicad/routers/{schematic,pcb,export}.py`
- `services/kicad/tools/schematic.py`
- `services/kicad/tests/test_service_security.py`

### Lecture seule

- `AGENTS.md`
- `docs/agents/COLLABORATION.md`
- `docs/agents/HANDOFF_TEMPLATE.md`
- Sous-modules `services/kicad/circuit_synth` et `services/kicad/kicad-tools`

### Hors périmètre

- Algorithmes de placement, routage, ERC, DRC et export
- Paiement, crédits, RLS et endpoints JLCPCB

## Modifications préexistantes non possédées

- Aucune — worktree propre au démarrage.

## Décisions prises

- Jeton Bearer serveur-à-serveur d'au moins 32 caractères, comparaison
  `compare_digest`, échec fermé si la configuration serveur manque.
- `/health` reste public; aucune surface CORS n'est exposée.
- Suppression complète de `/schematic/execute`, du générateur Python Haiku et
  de l'opt-in : le même UID pouvait relire les secrets via `/proc`, donc une
  allowlist d'environnement n'était pas une sandbox.
- Validation stricte des `project_id` utilisés dans les chemins schéma/PCB/export.
- Port compose lié à `127.0.0.1`; HTTPS ou réseau privé requis hors localhost.
- Runtime UID/GID 10001, code root-owned, mounts FastAPI read-only et seul
  `/tmp/kicad-jobs` writable.
- `kicad-tools` n'est plus masqué par un bind-mount : le backend C++ compilé
  reste immuable et les changements du sous-module imposent un rebuild.

## Travail réalisé

- Middleware d'authentification commun ajouté à FastAPI.
- Helper TypeScript commun propagé à tous les clients KiCad.
- Endpoint et chaîne complète d'exécution de Python généré supprimés.
- Traversées de chemin bloquées et couvertes sur l'application réelle.
- Docker/compose/entrypoint durcis et documentation/configuration alignées.
- Job CI Docker étendu avec les tests de frontière de sécurité.
- Revue code et revue sécurité intégrées; aucun constat restant côté code.

## Fichiers modifiés

- 34 fichiers suivis ou nouveaux dans les seuls chemins possédés ci-dessus.
- Aucun sous-module, secret ou fichier d'environnement modifié.

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `corepack pnpm install --frozen-lockfile --offline --force` | code 0, 937 paquets restaurés depuis le store local | `2026-07-16` |
| `corepack pnpm type-check` | code 0, 7/7 tâches réussies | `2026-07-16` |
| `corepack pnpm test` | code 0, agents 4 fichiers/21 tests; web sans tests | `2026-07-16` |
| `corepack pnpm lint` | code 0, 4/4 tâches; aucun warning/erreur ESLint | `2026-07-16` |
| `.venv/Scripts/python.exe -m unittest services.kicad.tests.test_service_security services.kicad.tests.test_docker_build_context -v` | code 0, 13/13 tests | `2026-07-16` |
| `C:/Program Files/Git/bin/sh.exe -n services/kicad/docker-entrypoint.sh` | code 0 | `2026-07-16` |
| `git diff --check` | code 0 | `2026-07-16` |
| Review code + sécurité en lecture seule | approuvé, aucun constat restant côté code | `2026-07-16` |

## Risques et blocages

- Docker est indisponible localement; le build, l'UID effectif et le démarrage
  avec mounts read-only doivent être confirmés par le job CI bloquant.
- Risque résiduel moyen accepté pour cette PR : tailles JSON/base64, concurrence
  et débit ne sont pas encore bornés; à traiter par un hardening séparé.
- Un futur client KiCad pourrait oublier le helper d'auth; ajouter ultérieurement
  un test d'exhaustivité ou une couche HTTP unique.

## Travail restant

- Aucun dans le périmètre de ce handoff.

## Prochaine action atomique

Vérifier que le job CI Docker KiCad de la PR #50 réussit.

## Git

- **État initial du worktree:** propre sur `cdad487`
- **État final du worktree:** propre après commit
- **Commit:** `66471d3601b4787dea770cb2bde5bb8e6e0b79ba`
- **PR:** `https://github.com/bmechergui/cirqix/pull/50`

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| `2026-07-16T20:51:52Z` | `Codex` | reviewers | `proposé` | Relectures code et sécurité en lecture seule. |
| `2026-07-16T21:54:18Z` | reviewers | `Codex` | `accepté` | High RCE, CORS, traversal, immutabilité et fail-fast corrigés; verdict final sans constat code. |
| `2026-07-16T21:59:13Z` | `Codex` | `none` | `DONE` | Commit poussé et PR #50 ouverte; prochaine action atomique : CI Docker. |

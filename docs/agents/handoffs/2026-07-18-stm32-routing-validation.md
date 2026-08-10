# Handoff — `2026-07-18-stm32-routing-validation`

- **Status:** `IN_PROGRESS`
- **Owner:** `Codex`
- **Reviewer:** `stm32_pipeline_reviewer; stm32_industrial_reviewer`
- **Receiver:** `none`
- **Branch:** `validate/stm32-routing-industrial`
- **Worktree:** `C:\tmp\cirqix-stm32-validation`
- **Base commit:** `c5811645a243d657c1790d469a436d6bd602b260`
- **Content commit:** `uncommitted only`
- **Updated UTC:** `2026-07-18T21:25:00Z`

## Objectif

Reproduire le cas STM32 de validation dans un worktree isolé et établir avec des
preuves si le routage atteint 100 % et une qualité fabricable industrielle.

## Critère de terminaison

Un rapport contient le pourcentage de routage réel et le résultat du DRC KiCad
officiel. Le cas n'est déclaré industriel que si les métriques exigées sont
observées, sans substituer un pourcentage déclaratif au DRC.

## Périmètre autorisé

### Chemins possédés

- `docs/agents/handoffs/2026-07-18-stm32-routing-validation.md`
- `services/kicad/examples/stm32-validation/{README.md,input/generate_design.py,run_agent_chain.py}`
- `services/kicad/tests/test_stm32_validation.py`
- sorties non suivies sous `C:\tmp\cirqix-stm32-validation-output\`

### Lecture seule

- `services/kicad/examples/stm32-validation/**`
- `services/kicad/tools/**`
- `services/kicad/tests/**`

### Hors périmètre

- code applicatif, sous-modules et artefacts suivis
- toute commande JLCPCB

## Modifications préexistantes non possédées

- Aucune — worktree créé propre depuis `c5811645a243d657c1790d469a436d6bd602b260`.

## Décisions prises

- Les sorties vont dans `C:\tmp` afin de préserver le dépôt et les artefacts d'exemple suivis.
- Le DRC KiCad officiel est un gate obligatoire après toute valeur de routage annoncée.

## Travail réalisé

- Worktree isolé créé.
- Deux revues indépendantes lancées : pipeline et qualité industrielle.
- Reproduction tentée dans l'arborescence d'exemple : elle est bloquée avant la
  génération par l'absence de runtime KiCad local.
- Reproduction exécutée dans l'image Docker KiCad : le générateur produit le board,
  puis retourne code 1 après 42 erreurs ERC, avant placement et routage.

## Fichiers modifiés

- `docs/agents/handoffs/2026-07-18-stm32-routing-validation.md` — état de validation.

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `python -c "import pcbnew"` | code 1, module absent | `2026-07-18` |
| `python -c "import kicad_tools"` | code 1, module absent | `2026-07-18` |
| `kicad-cli --version` | code 1, commande introuvable | `2026-07-18` |
| `python services/kicad/examples/stm32-validation/run_agent_chain.py ...` | code 1, création du dossier de sortie refusée dans le worktree, avant import du runtime KiCad | `2026-07-18` |
| `docker version --format '{{.Server.Version}}'` | code 1, commande Docker introuvable | `2026-07-18` |
| `wsl --status` | code 0, WSL 2 disponible mais aucune distribution installée | `2026-07-18` |
| `docker run ... run_agent_chain.py /tmp/kicad-jobs/stm32-20260718` | code 1, génération terminée; 42 erreurs ERC avant kicad-tools | `2026-07-18` |

## Risques et blocages

- Le runtime local ne contient ni `pcbnew`, ni `kicad_tools`, ni `kicad-cli`; le routage réel et le DRC officiel sont bloqués jusqu'à l'exécution dans l'image Docker KiCad ou un poste KiCad préparé.
- Docker Desktop est absent et WSL ne possède aucune distribution : la préparation locale de l'image KiCad nécessite l'installation d'un runtime, qui n'est pas une écriture dans le périmètre du dépôt.
- Le répertoire d'exemple ne permet pas la création des sorties dans ce worktree; ce point doit être résolu par un volume de sortie accessible dans le runtime préparé.
- L'image Docker locale contient `pcbnew`, `kicad_tools` et `kicad-cli 8.0.9`; le blocage est désormais ERC, pas environnemental.

## Travail restant

- Exécuter le pipeline et le DRC officiel dans un runtime KiCad disponible.

## Prochaine action atomique

Exécuter `run_agent_chain.py` dans l'image Docker KiCad puis lancer `kicad-cli pcb drc` sur le PCB final.

## Git

- **État initial du worktree:** propre
- **État final du worktree:** handoff non committé
- **Commit:** `none`
- **PR:** `none`

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| `2026-07-18T20:37:47Z` | `Codex` | `Codex` | `accepté` | Validation isolée; revues parallèles en lecture seule. |
| `2026-07-18T20:40:00Z` | `Codex` | `Codex` | `bloqué` | Runtime KiCad absent localement; aucune métrique de routage ne peut être produite honnêtement. |
| `2026-07-18T21:07:50Z` | `Codex` | `Codex` | `bloqué` | Docker absent; WSL est disponible mais sans distribution. |
| `2026-07-18T21:25:00Z` | `Codex` | `Codex` | `repris` | Ubuntu WSL, Docker 29.1.3 et kicad-tools natif confirmés. |

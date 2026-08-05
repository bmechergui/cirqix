# Handoff — `graphify-multigraph`

- **Status:** `REVIEW`
- **Owner:** `Codex`
- **Reviewer:** `Codex code review`
- **Receiver:** `human`
- **Branch:** `chore/graphify-multigraph`
- **Worktree:** `C:\\tmp\\cirqix-graphify-multigraph`
- **Base commit:** `811f0aa6edcd9ab69b5798f4199e6263812b96da`
- **Content commit:** `uncommitted`
- **Updated UTC:** `2026-08-05T00:47:10Z`

## Objectif

Rendre Graphify automatique par défaut pour Claude Code et Codex, avec un graphe
Cirqix SaaS non dominé par les sous-modules, deux graphes dédiés à `kicad-tools`
et `circuit_synth`, puis un agrégat interrogeable couvrant les trois corpus.

## Critère de terminaison

Les hooks Claude et les instructions Codex appellent un script versionné et
contrôlé par SHA; le script détecte la fraîcheur, sérialise les écritures,
maintient un watcher PID-géré, écrit les graphes des sous-modules hors de leurs
worktrees et régénère l'agrégat. La syntaxe, les signatures, les requêtes sur les
quatre graphes, le type-check, la revue, le commit, le push et la PR sont prouvés.

## Périmètre autorisé

### Chemins possédés

- `.claude/settings.json`
- `.claude/SKILLS.md`
- `.graphifyignore`
- `AGENTS.md`
- `CLAUDE.md`
- `docs/graphify.md`
- `scripts/graphify-refresh.ps1`
- `docs/agents/handoffs/2026-08-05-graphify-multigraph.md`

### Lecture seule

- `.gitmodules`
- `PLAN.md`
- `docs/agents/COLLABORATION.md`
- `services/kicad/kicad-tools/**`
- `services/kicad/circuit_synth/**`

### Hors périmètre

- Code produit, migrations, configuration distante et contenu des sous-modules.
- Fichiers `graphify-out/**`, régénérables et ignorés par Git.

## Modifications préexistantes non possédées

- Aucune dans ce worktree propre créé depuis `origin/main`.
- Le worktree partagé principal reste sale et divergent; aucun de ses changements
  étrangers ne sera déplacé, restauré, stagé ou commité ici.

## Décisions prises

- Utiliser un worktree dédié depuis `origin/main` afin d'exclure les 22 commits
  locaux et les modifications non attribuées du checkout principal.
- Conserver trois graphes sources distincts; l'agrégat reste volontairement trois
  composantes disjointes et n'invente aucune relation inter-dépôt.
- Normaliser LF/CRLF avant le contrôle SHA afin que les hooks restent portables
  sur les clones Windows sans modifier le `.gitattributes` partagé.
- Lancer le watcher avec l'exécutable `graphify` résolu par `Get-Command`; un
  clone neuf ne possède pas encore `graphify-out/.graphify_python`.

## Travail réalisé

- Worktree et branche dédiés créés depuis le dernier `origin/main`; modifications
  étrangères du checkout partagé exclues.
- Script multi-graphe, exclusions, hooks Claude, règles Codex, registre de skill
  et documentation reproduits dans la branche dédiée.
- Sous-modules de premier niveau initialisés aux gitlinks exacts; leurs worktrees
  sont restés propres et ne contiennent aucun `graphify-out`.
- Construction complète mesurée : SaaS 2 193 nœuds initialement, `kicad-tools`
  80 738 nœuds/177 568 arêtes, `circuit_synth` 9 844/15 729, puis agrégat.
- Le test neuf a révélé puis permis de corriger la dépendance implicite à
  `.graphify_python`; le watcher direct a été testé, puis le graphe racine et
  l'agrégat ont été rafraîchis.
- État final mesuré : SaaS 2 980 nœuds/4 547 liens, aucun nœud source des deux
  sous-modules; agrégat 93 562 nœuds/197 844 arêtes; watcher PID 47048 actif.

## Fichiers modifiés

- `.claude/settings.json` — hooks SessionStart/PostToolUse, SHA portable LF/CRLF.
- `.claude/SKILLS.md` — enregistrement du skill Graphify.
- `.graphifyignore` — exclusion des deux sous-modules du graphe SaaS.
- `AGENTS.md` — usage automatique par défaut pour Codex.
- `CLAUDE.md` — politique partagée des trois graphes et de l'agrégat.
- `docs/graphify.md` — architecture, commandes, limites et temps d'initialisation.
- `scripts/graphify-refresh.ps1` — signatures, verrou, refresh ciblé, fusion et watcher.
- `docs/agents/handoffs/2026-08-05-graphify-multigraph.md` — propriété et preuves.

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `git status --short --branch` | branche propre `chore/graphify-multigraph...origin/main` avant handoff | 2026-08-04 |
| `powershell.exe ... scripts/graphify-refresh.ps1 -Mode Ensure` dans le checkout source | exit 0; `root=False kicad-tools=False circuit_synth=False merge=False` | 2026-08-04 |
| `git submodule update --init --recursive` | exit 1 après checkout de `circuit_synth`: URL absente pour le sous-module imbriqué historique `kicad-sch-api` | 2026-08-05 |
| `git submodule update --init services/kicad/kicad-tools services/kicad/circuit_synth` | exit 0; gitlinks `f2afb967` et `08b9b0e4` | 2026-08-05 |
| parseur PowerShell 5.1 + `ConvertFrom-Json` settings + SHA | exit 0; script et JSON valides; SHA initial conforme | 2026-08-05 |
| `corepack pnpm install --frozen-lockfile` | exit 0; 828 paquets réutilisés, lockfile inchangé | 2026-08-05 |
| `$env:TURBO_CACHE_DIR='C:\tmp\cirqix-graphify-typecheck-cache'; corepack pnpm type-check` | exit 0; 7/7 tâches réussies | 2026-08-05 |
| `scripts/graphify-refresh.ps1 -Mode All` | corpus et fusion réussis; exit 1 final révélant `.graphify_python` absent sur clone neuf | 2026-08-05 |
| lancement direct `graphify watch <repo>` pendant 5 secondes | exit 0; processus `graphify` vivant puis arrêté | 2026-08-05 |
| `scripts/graphify-refresh.ps1 -Mode Ensure` après correction | exit 0; watcher direct démarré PID 41012 | 2026-08-05 |
| `scripts/graphify-refresh.ps1 -Mode Root` final | exit 0; racine actualisée, agrégat 93 562/197 844, watcher redémarré PID 47048 | 2026-08-05 |
| `-Mode Ensure -CheckOnly` puis `-Mode Watcher -CheckOnly` | exit 0; quatre fraîcheurs `False`; watcher `True` | 2026-08-05 |
| quatre `graphify query ... --graph <racine|kicad-tools|circuit-synth|full>` | exit 0 pour les quatre corpus | 2026-08-05 |
| audit JSON racine | 2 980 nœuds, 4 547 liens, 0 source sous `services/kicad/{kicad-tools,circuit_synth}` | 2026-08-05 |
| contrôle SHA normalisé et simulation CRLF | exit 0; `2146a932...3c50fce`, présent dans les deux hooks | 2026-08-05 |
| invocation AST isolée de `Assert-RepositoryRoot` | exit 0; chemin absent rejeté et sous-dossier non racine rejeté avec messages guidés | 2026-08-05 |
| `git diff --check` + statuts des deux sous-modules | exit 0; aucune erreur de whitespace; sous-modules propres; aucun cache interne | 2026-08-05 |

## Risques et blocages

- Une reconstruction structurelle initiale des trois corpus peut durer environ
  40 minutes; les exécutions suivantes utilisent les signatures et sont rapides.
- Le sous-module imbriqué historique `kicad-sch-api` de `circuit_synth` n'a pas
  d'URL dans son `.gitmodules`; Graphify ne dépend que des deux sous-modules de
  premier niveau et leur initialisation non récursive réussit.

## Travail restant

- Terminer la revue indépendante, appliquer ses éventuels constats, puis commit,
  push et PR.

## Prochaine action atomique

Relire le diff complet et rendre les constats au propriétaire Codex.

## Git

- **État initial du worktree:** propre sur `811f0aa`, branche suivant `origin/main`.
- **État final du worktree:** en cours.
- **Commit:** `none`
- **PR:** `none`

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| 2026-08-04 | Codex | Codex reviewer | proposé | Installation multi-graphe revendiquée dans un worktree propre. |

# Graphify — knowledge graph du monorepo

> Installé le 2026-07-19. CLI : `graphifyy` (uv tool, `~/.local/bin/graphify`) +
> skill Claude Code `/graphify`. Upstream : https://github.com/safishamsi/graphify (MIT).

## Ce que c'est

Graphify couvre les trois corpus du dépôt avec des graphes séparés : le code Cirqix
de premier niveau, `kicad-tools` et `circuit_synth`. `.graphifyignore` retire les deux
sous-modules du seul graphe racine afin que leurs milliers de nœuds ne dominent pas
les requêtes d'architecture SaaS. Chaque sous-module possède néanmoins son graphe
dédié, et les trois peuvent être réunis dans un graphe agrégé multi-repo.

L'extraction AST tree-sitter est locale, déterministe et sans LLM pour le code.
Chaque arête est taguée `EXTRACTED` (lue dans la source) ou `INFERRED` (résolue).
Les assistants interrogent le graphe **avant** la lecture source ciblée : moins de
tokens et traversées inter-langages dans le corpus Cirqix de premier niveau.

## Commandes utiles

```bash
graphify update .                 # met à jour le graphe AST de façon incrémentale
graphify extract . --code-only --force # reconstruit tout le code, sans les docs
graphify explain "auto_place"     # un nœud + ses connexions
graphify path "call_agent_routing" "kct_route"   # chemin entre deux concepts
graphify query "finalizePipelineSuccess runRealOrchestrator kicad-storage order" --context call --budget 2500 # vue SaaS ciblée
graphify affected "placement.py"  # impact inverse (qui dépend de X)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/graphify-refresh.ps1 -Mode Watcher # watcher géré
```

Reconstruction des sous-modules et du graphe agrégé, sans écrire dans leurs
worktrees :

```powershell
git submodule update --init services/kicad/kicad-tools services/kicad/circuit_synth
graphify extract services/kicad/kicad-tools --code-only --out graphify-out/scopes/kicad-tools
graphify extract services/kicad/circuit_synth --code-only --out graphify-out/scopes/circuit-synth
graphify merge-graphs graphify-out/graph.json graphify-out/scopes/kicad-tools/graphify-out/graph.json graphify-out/scopes/circuit-synth/graphify-out/graph.json --out graphify-out/full-graph.json
```

Après un nouveau clone, initialiser les deux sous-modules de premier niveau avec
la première commande ci-dessus. Le script refuse explicitement un dossier vide ou
un gitlink non initialisé et affiche cette commande; il ne lance pas de téléchargement
réseau silencieux depuis un hook de session.

Sorties dans `graphify-out/` (**gitignoré** — artefact régénérable) :
`graph.html` (visu interactive), `GRAPH_REPORT.md` (résumé), `graph.json` (le graphe).

- SaaS Cirqix : `graphify-out/graph.json`
- `kicad-tools` : `graphify-out/scopes/kicad-tools/graphify-out/graph.json`
- `circuit_synth` : `graphify-out/scopes/circuit-synth/graphify-out/graph.json`
- recherche agrégée multi-repo : `graphify-out/full-graph.json`

Sélectionner un graphe non racine avec `--graph <chemin>` sur `query`, `path`,
`explain`, `affected` ou `god-nodes`.

`merge-graphs` conserve trois composantes disjointes : il permet une recherche
commune, mais ne crée pas d'arêtes entre les dépôts. Un `path` ne traverse donc pas
automatiquement le wrapper Cirqix vers un symbole interne du sous-module.

## Mise à jour automatique

Au démarrage de Claude Code, le hook `SessionStart` lance le script avec
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File
scripts/graphify-refresh.ps1 -Mode Ensure`. Le contournement de politique est limité
à ce script local contrôlé par SHA-256 dans le hook; il est nécessaire sur les postes
Windows en mode `Restricted`.
Codex exécute le même contrôle avant sa première question sur le code, conformément
à `AGENTS.md`. Le contrôle compare le commit, l'index, le worktree, les fichiers non
suivis, `.graphifyignore`, la version de Graphify et les paramètres d'extraction. Il
ne reconstruit que les graphes obsolètes avant de refaire la fusion.

Le watcher respecte `.graphifyignore` et ne met à jour que le graphe AST du code.
Les changements sémantiques dans la documentation demandent une extraction dédiée.
Avant une reconstruction complète avec `graphify extract . --code-only --force`,
arrêter le watcher pour éviter deux écritures concurrentes dans `graphify-out/`.
Après une modification, l'agent appelle le script avec `-Mode Root`,
`-Mode KicadTools`, `-Mode CircuitSynth` ou `-Mode All`. Un verrou de processus évite
deux reconstructions concurrentes. Le script arrête son watcher Cirqix avant toute
écriture puis le redémarre sous le même verrou. Les graphes des sous-modules restent
écrits sous `graphify-out/scopes/`, jamais dans leurs worktrees.

La première migration ou un changement de version/exclusions peut reconstruire les
trois corpus et durer jusqu'à environ 40 minutes. Lorsque les signatures sont
inchangées, `-Mode Ensure` termine en quelques secondes sans réextraction.

## Règles d'usage

- Question d'architecture / « qui appelle quoi » / « pourquoi ce module » →
  interroger le graphe d'abord (skill `graphify`), grep ensuite si besoin.
- Le graphe est un outil d'**exploration**, pas un vérificateur : il ne remplace ni
  les tests, ni les quality gates, ni la lecture du code avant modification.
- Ne jamais committer `graphify-out/`.

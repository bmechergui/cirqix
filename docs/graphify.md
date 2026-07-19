# Graphify — knowledge graph du monorepo

> Installé le 2026-07-19. CLI : `graphifyy` (uv tool, `~/.local/bin/graphify`) +
> skill Claude Code `/graphify`. Upstream : https://github.com/safishamsi/graphify (MIT).

## Ce que c'est

Graphify transforme le monorepo — code TS/Python, workflows YAML, docs, **sous-modules
inclus** (`kicad-tools`, `circuit_synth`) — en knowledge graph interrogeable
(`graphify-out/graph.json`). Extraction AST tree-sitter locale, déterministe, zéro LLM
pour le code. Chaque arête est taguée `EXTRACTED` (lue dans la source) ou `INFERRED`
(résolue). Les assistants IA interrogent le graphe **au lieu de re-grepper** le repo :
moins de tokens, traversées inter-langages (orchestrateur TS → FastAPI → kicad-tools).

## Commandes utiles

```bash
graphify update .                 # (re)construit le graphe — code seul, sans LLM
graphify explain "auto_place"     # un nœud + ses connexions
graphify path "call_agent_routing" "kct_route"   # chemin entre deux concepts
graphify query "où est décidé le revert CMA-ES ?" # sous-graphe pour une question
graphify affected "placement.py"  # impact inverse (qui dépend de X)
graphify watch .                  # rebuild automatique à chaque modification
```

Sorties dans `graphify-out/` (**gitignoré** — artefact régénérable) :
`graph.html` (visu interactive), `GRAPH_REPORT.md` (résumé), `graph.json` (le graphe).

## Mise à jour automatique

Un hook `SessionStart` (`.claude/settings.json`) démarre `graphify watch .` en tâche
de fond si aucun watcher ne tourne : **toute modification de code déclenche un rebuild
incrémental** du graphe, quelle que soit la session (Claude, IDE, autre assistant).
Le watcher est machine-locale ; après un `git pull` massif, un `graphify update .`
manuel garantit la fraîcheur immédiate.

## Règles d'usage

- Question d'architecture / « qui appelle quoi » / « pourquoi ce module » →
  interroger le graphe d'abord (skill `graphify`), grep ensuite si besoin.
- Le graphe est un outil d'**exploration**, pas un vérificateur : il ne remplace ni
  les tests, ni les quality gates, ni la lecture du code avant modification.
- Ne jamais committer `graphify-out/`.

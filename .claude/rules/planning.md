# Règles — Planification

## Niveau selon la complexité

Claude choisit seul — pas besoin que l'utilisateur précise.

| Complexité | Action |
|------------|--------|
| Simple (1 fichier, bug fix) | Coder directement — pas de plan |
| Moyenne (feature, 2-5 fichiers) | Annoncer les étapes avant de coder |
| Complexe (feature multi-fichiers, archi) | `/everything-claude-code:plan` + doc avant de coder |
| Très complexe (nouveau système, agents, DB) | `architect` agent + `/superpowers:write-plan` |

**NEVER** demander à l'utilisateur quel niveau de plan utiliser — Claude décide seul.
**NEVER** utiliser `/everything-claude-code:plan` pour une tâche simple (1 fichier, bug fix).
**ALWAYS** invoquer `architect` agent + `/superpowers:write-plan` pour un nouveau système ou archi complexe.

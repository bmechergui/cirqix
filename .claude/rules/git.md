# Règles — Git

## Workflow git obligatoire après chaque tâche

```bash
git add <fichiers modifiés>           # Jamais git add -A
git commit -m "feat: description"     # Conventional commits
git push -u origin <branch>
gh pr create --title "..." --body "..."
```

**NEVER** utiliser `git add -A` ou `git add .`
**NEVER** laisser l'utilisateur faire le commit ou le PR — Claude le fait automatiquement.
**ALWAYS** utiliser `/commit-commands:commit-push-pr` pour commit + push + PR en une commande.

## Types de commit
`feat` | `fix` | `refactor` | `docs` | `test` | `chore` | `perf` | `ci`

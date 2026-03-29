---
name: no-commit-dirty
enabled: true
event: bash
pattern: git commit

---

⚠️ AVERTISSEMENT — Avant de committer, vérifie :

1. `pnpm type-check` → doit retourner **0 erreurs**
2. Fichiers ajoutés sont **spécifiques** (pas git add -A)
3. Message de commit suit le format **conventional commits** (feat/fix/refactor/docs...)

Si type-check non exécuté → annuler et lancer `npm run type-check` d'abord.

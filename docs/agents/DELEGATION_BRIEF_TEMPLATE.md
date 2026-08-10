# Brief de délégation — `<task-id>`

Modèle de brief remis à un agent externe (`codex`, `kimi`, `grok`, `gemini`).
Il doit être **autonome** : l'agent ne partage pas le contexte de la session
Claude Code. Règles applicables : `docs/agents/COLLABORATION.md`, section
« Isolation par worktree des agents externes ».

---

## 1. Ton rôle

Tu es **delegate externe** sur ce dépôt. Tu implémentes la tâche ci-dessous
dans le worktree indiqué, puis tu t'arrêtes. Tu ne commit pas, tu ne pousses
pas, tu n'ouvres pas de PR. L'owner relit ton diff, exécute les gates et intègre.

## 2. Worktree assigné

- **Chemin :** `<C:\tmp\cirqix-...>`
- **Branche :** `<branche dédiée>`
- **Commit de base :** `<sha>`

Tu ne sors jamais de ce répertoire. Le dépôt principal
`C:\Users\Mechegui\Desktop\dev\cirqix` t'est **interdit en écriture**.

## 3. Objectif

<Résultat observable attendu, en une à trois phrases.>

## 4. Critère de terminaison

<Condition binaire vérifiable par l'owner.>

## 5. Périmètre

### Chemins que tu peux modifier

- `<path>`

### Lecture seule

- `<path>`

### Hors périmètre

- Tout autre chemin.
- Les sous-modules `services/kicad/kicad-tools` et `services/kicad/circuit_synth`.
- Les fichiers d'instructions (`CLAUDE.md`, `AGENTS.md`, `docs/agents/**`).

## 6. Contexte technique nécessaire

<Extraits de règles projet indispensables : conventions, types source de
vérité, pièges connus du périmètre. L'agent n'a pas lu CLAUDE.md.>

## 7. Validations attendues de ta part

| Commande | Attendu |
|---|---|
| `<commande>` | `<résultat>` |

Consigne le résultat **exact** de chaque commande, y compris les échecs.
Écris `non exécuté` si tu ne l'as pas lancée. La formule « tests OK » est
interdite. Ne déclare jamais un résultat que tu n'as pas observé.

## 8. Interdits

- Commit, push, PR, tag, modification de l'historique.
- `git add .`, `git add -A`, `git stash`, `git reset --hard`, `git checkout --`.
- Toucher un fichier hors des chemins listés en §5.
- Installer ou mettre à jour une dépendance sans que ce soit demandé ici.
- Écrire une clé, un token, un `.env` ou une URL signée dans ta sortie.
- Déclarer `ERC_CLEAN`, `DRC_CLEAN` ou une validation de fabrication : ces
  états relèvent d'un contrôle d'autorité que tu n'exécutes pas.

## 9. Format de ta réponse finale

1. **Résumé** — ce que tu as changé, en cinq lignes maximum.
2. **Fichiers modifiés** — liste avec une ligne de justification chacun.
3. **Validations** — le tableau du §7 rempli avec les sorties réelles.
4. **Limites et risques** — ce que tu n'as pas pu vérifier.
5. **Diff** — laisse-le dans le worktree, non commité. Ne le colle pas.

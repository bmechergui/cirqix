# kicad-tools — Stratégie Fork privé + Submodule

> Référence de comment Cirqix gère sa copie **patchée** de kicad-tools, comment la
> synchroniser avec l'upstream, et comment **valider manuellement** chaque mise à jour.
>
> Objectif : une solution posée **une fois pour toutes**, automatisée, où **rien ne migre
> sans validation humaine** et où **les patches Cirqix restent privés**.

---

## 1. TL;DR — le vocabulaire (à lire en premier)

| Mot | Qui c'est concrètement ? |
|---|---|
| **Upstream** | `rjwalters/kicad-tools` — le repo **original de l'auteur** (public). La source d'où descendent les nouveautés. On ne le contrôle pas. |
| **Notre copie privée (fork/miroir)** | `bmechergui/kicad-tools` — notre copie **modifiée et privée**. On la contrôle à 100 %. Seul nous (+ invités) voyons les patches. |
| **Submodule** | le dossier `services/kicad/kicad-tools/` dans cirqix — **un pointeur** vers un commit précis de notre copie privée. Pas une copie de fichiers. |

**Analogie :** upstream = l'usine qui fabrique le logiciel. Nous = le client qui l'achète, le
modifie, et de temps en temps récupère la nouvelle version de l'usine (en validant).
Le submodule = un signet dans le livre cirqix qui dit *« voir le livre kicad-tools, page X »*.

---

## 2. Pourquoi cette stratégie

Cirqix applique des **patches** (corrections) sur kicad-tools qui ne sont pas (encore) dans
l'upstream. Sans stratégie Git propre, on avait un **dossier gitignoré copié en dur** :
- ❌ pas de diff fiable contre upstream
- ❌ mise à jour = copier-coller manuel + réappliquer les patches à la main
- ❌ pas d'historique de nos modifications

Avec **fork privé + submodule** :
- ✅ chaque patch = **un commit isolé** (provenance, rebasable, on voit exactement ce qui est à nous)
- ✅ diff réel : `git log cirqix..upstream/main`
- ✅ mise à jour = vrai `git rebase` (pas du manuel)
- ✅ le pin cirqix (commit SHA) est **tracké dans notre git** → une mise à jour = 1 PR reviewable
- ✅ **patches privés** (repo privé)

---

## 3. L'architecture cible

```
upstream: rjwalters/kicad-tools (main, public)
              │  sync hebdo auto (Action sur le fork privé)
              ▼
   bmechergui/kicad-tools  ← NOTRE COPIE PRIVÉE
   branche « cirqix » = upstream/main + nos patches (1 patch = 1 commit + 1 test garde)
              │  piné à un commit précis
              ▼
   bmechergui/cirqix  ← LE SaaS
   services/kicad/kicad-tools/ = GIT SUBMODULE (pointeur vers le fork privé)
```

---

## 4. Le pipeline de validation — 4 portes (2 auto, 2 humaines)

**Rien ne migre dans cirqix sans que tu merges à 2 endroits** (Porte 2 + Porte 4).

```
upstream rjwalters/kicad-tools  ──(nouveaux commits)──┐
                                                       │
   ┌──────────────────────────────────────────────────┘
   ▼
🚪 PORTE 1 (AUTO) — Action hebdo sur le fork privé
   • détecte le delta, tente rebase de la branche « cirqix »
   • si OK   → ouvre PR « rebase cirqix → upstream <sha> »
   • si conflit → ouvre une issue (patches à retravailler)
        │
        ▼  tu regardes la PR
🚪 PORTE 2 (TOI) — tu valides sur le repo kicad-tools privé
   • tu vois ce qui change, si tes patches tiennent encore
   • tu MERGE la PR        ← 1ʳᵉ validation manuelle
        │
        ▼
🚪 PORTE 3 (AUTO) — une 2ᵉ Action ouvre une PR dans cirqix
   « chore: bump kicad-tools submodule → <sha> »
   → CI cirqix tourne : build Docker + kct build-native
     + test route board STM32 + DRC kicad-cli (le juge)
        │
        ▼  tu regardes le résultat CI (vert/rouge)
🚪 PORTE 4 (TOI) — tu valides sur cirqix
   • CI vert → tu MERGE → cirqix utilise le nouveau kicad-tools ✅
   • CI rouge → tu fermes, rien ne change, tu enquêtes
```

---

## 5. Workflow quotidien

### 5.1 Modifier kicad-tools = **2 pushes** (un par repo)

Rien d'automatique. Le submodule est un repo niché dans cirqix — chaque repo garde son
historique, donc 2 commits + 2 pushes.

```
┌─────────────────────────────────────────────────────┐
│  PUSH 1 → vers le repo kicad-tools (privé)          │
├─────────────────────────────────────────────────────┤
│  cd services/kicad/kicad-tools                      │
│  git checkout cirqix                                 │
│  git add <fichier modifié>                           │
│  git commit -m "fix: ma correction"                 │
│  git push origin cirqix        ← push 1 (kicad-tools)│
└─────────────────────────────────────────────────────┘
                       │
                       ▼  (le pointeur submodule a changé dans cirqix)
┌─────────────────────────────────────────────────────┐
│  PUSH 2 → vers le repo cirqix                       │
├─────────────────────────────────────────────────────┤
│  cd <racine cirqix>                                  │
│  git add services/kicad/kicad-tools   ← le nouveau SHA│
│  git commit -m "chore: bump kicad-tools (...)"      │
│  git push origin <branche>     ← push 2 (cirqix)    │
└─────────────────────────────────────────────────────┘
```

> 👉 En pratique, c'est **Claude** qui tape ces commandes (règle Cirqix : l'utilisateur ne
> fait jamais le git). Tu dis « applique le patch X », Claude fait les 2 pushes et montre le
> résultat.

### 5.2 Vérifier la diff à la demande (n'importe quand)

Tu demandes à Claude : *« vérifie la différence entre notre kicad-tools et upstream »*.

```bash
cd services/kicad/kicad-tools
git fetch upstream                                  # récupère le dernier upstream
git log cirqix..upstream/main --oneline            # ← ce qu'UPSTREAM a et qu'ON n'a PAS
git log upstream/main..cirqix --oneline            # ← ce que NOUS avons (nos patches)
```

Claude répond un rapport structuré :

```
📊 Diff kicad-tools nous vs upstream (au AAAA-MM-JJ)

⏪ Upstream a N commits qu'on n'a pas encore :
   • <sha> <message>
   • ...

⏩ On a N patches qu'upstream n'a pas :
   • #1 fsync Windows
   • #2 net name-only KiCad 9+
   • ...

🟢/🟠 Verdict : mise à jour safe / patches à retravailler
   → tu veux que je prépare le rebase + les 2 PR de validation ?
```

L'**Action hebdo** fait la même chose automatiquement (Porte 1) et ouvre une PR/issue.

---

## 6. État actuel des patches (2026-07-11)

Base du snapshot actuel : upstream `main` commit `fda275d` (2026-06-13).
Upstream est **+197 commits / 300 fichiers** ahead (`5e6eef8`, 2026-07-10).

| # | Patch | Fichier | Statut |
|---|---|---|---|
| 1 | fsync Windows | `cli/route_cmd.py` | local (Windows-only) |
| 2 | net name-only KiCad 9+ | `reasoning/state.py` | local |
| 3 | layer_count 4/6 | `reasoning/interpreter.py` | local |
| 4 | CMA-ES writer 2-pass | `cli/optimize_placement_cmd.py` | local |
| 5 | CMA-ES seed="current" | `cli/optimize_placement_cmd.py` | local |
| 6 | angles pads absolus | `schema/pcb.py`, `router/io.py` | ⭐ **désormais upstream PR #3903** → à supprimer |
| 7 | `KCT_SAFE_OPTIMIZE` | `router/optimizer/config.py` | local (diagnostic) |
| 8 | signe rotation pads (Y bas) | `router/io.py` | ⭐ **désormais upstream PR #3746** → à supprimer |

> Le patch charmap Windows est **hors lib** (`tools/kct_route.py`), durable.
> Issue upstream **#3803** (« kct PASS vs kicad-cli 400+ violations ») = **fermée** upstream
> (PR #3815/#3816/#3817/#3830). Notre #8 adressait le même symptôme → désormais redondant.

**Bilan migration :** on part de 8 patches → on en garde **6** (#1–5, #7) + 2 extensions du #6.

---

## 7. Runbook de mise à jour (quand on valide un update upstream)

```bash
# Sur le fork privé (branche cirqix)
cd services/kicad/kicad-tools
git fetch upstream
git checkout cirqix
git rebase upstream/main          # rejoue nos 6 patches par-dessus le nouvel upstream
# → résoudre les conflits éventuels patch par patch
git push origin cirqix --force-with-lease   # branche patchée = rebase = force OK

# Puis dans cirqix (bump du pointeur)
cd <racine cirqix>
git add services/kicad/kicad-tools
git commit -m "chore: bump kicad-tools -> upstream <sha>"
# → pnpm type-check + Docker build + kct build-native + test route STM32
# → le juge = kicad-cli pcb drc (jamais le DRC interne seul)
```

En production, ce runbook est **automatisé par les 2 Actions** (Portes 1 + 3), qui ouvrent
les PR — l'humain ne fait que merger (Portes 2 + 4) après vérification CI.

---

## 8. Effort & tradeoffs

- **Effort mise en place :** ~1 journée (Claude fait le code ; l'utilisateur crée le repo
  privé vide en 1 clic).
- **Tradeoff :** le build Docker doit faire `git submodule update --init --recursive`
  (1 ligne de plus dans le Dockerfile). Le CI clone un repo privé → **deploy key** SSH
  (Claude configure tout).
- **Bénéfice long terme (Phase D) :** ouvrir de vrais PR upstream pour les patches généraux
  (#2 KiCad 10, #3 layer_count, #1 fsync) → une fois mergés, on les supprime de la branche
  `cirqix` → convergence vers **zéro patch**.

---

## 9. Fichiers concernés

- `services/kicad/kicad-tools/` — devient un submodule (pointeur vers `bmechergui/kicad-tools`)
- `.gitmodules` — déclare le submodule (NOUVEAU)
- `services/kicad/Dockerfile` — `git submodule update --init` au build
- `services/kicad/DEPENDENCIES.md` — runbook détaillé des patches (existant, à mettre à jour)
- `.github/workflows/kicad-tools-sync.yml` — Action hebdo sur le fork privé (NOUVEAU, sur le repo fork)
- `.github/workflows/kicad-tools-bump.yml` — Action PR bump dans cirqix (NOUVEAU, sur cirqix)
- `CLAUDE.md` — référence cette stratégie (section « Dépendances vendorées »)

---

## 10. Étapes de mise en place (checklist)

> ✅ **Mise en place terminée** — PR cirqix [#47](https://github.com/bmechergui/cirqix/pull/47).
> Fork privé `bmechergui/kicad-tools` (branches `main` + `cirqix`) opérationnel.

- [x] **Utilisateur** crée le repo privé vide `bmechergui/kicad-tools` (Private) — *fait*
- [x] Claude clone l'historique upstream dans le repo privé + ajoute remote `upstream` — *main @ `5e6eef8`*
- [x] Claude crée la branche `cirqix` avec les patches en commits isolés — *5 commits @ `6196b6d` (#1, #2+#3, #4+#5, #6+#8, #7)*
- [x] Claude convertit `services/kicad/kicad-tools/` en submodule (branche `cirqix`) — *commit `bd7cdf2`*
- [x] Claude génère la **deploy key** (read-only sur le fork privé + secret `SUBMODULE_DEPLOY_KEY` dans cirqix)
- [x] Claude met à jour le `Dockerfile` (garde + commentaires submodule) — *commit `303a1ca`*
- [x] Claude pose les **2 Actions** (`sync-upstream` sur le fork @ `efe376f` + `kicad-tools-bump` sur cirqix) — *commit `32eed3f`*
- [x] Correction doc `DEPENDENCIES.md` (`#3902 → #3903`) — *fait*
- [ ] **#6/#8 auto-supprimés au prochain rebase** upstream (`--empty=drop` de `sync-upstream` — déjà mergés upstream en PR #3903 / #3746)
- [ ] **Validation finale (utilisateur)** : `docker compose build kicad` + `kct build-native --check` + test route board STM32 (juge = `kicad-cli pcb drc`) → puis merge PR #47

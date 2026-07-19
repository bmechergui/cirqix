# Submodules forkés (`kicad-tools` + `circuit_synth`) — Stratégie canonique

> **Référence unique** pour gérer les deux sous-modules forkés de Cirqix :
> `kicad-tools` (rjwalters) et `circuit_synth` (circuit-synth). Documente les deux
> sens — **local → cloud** (je modifie le sous-module) et **cloud → local** (je tire
> une mise à jour) — ainsi que le pipeline automatique hebdo qui synchronise l'amont
> vers le fork, puis le fork vers cirqix.
>
> Objectif historique conservé : une solution posée **une fois pour toutes**,
> automatisée, où **rien ne migre sans validation humaine** et où **les patches
> Cirqix restent privés**.

---

## 1. TL;DR — le vocabulaire (à lire en premier)

| Mot | Qui c'est concrètement ? |
|---|---|
| **Upstream** | le repo **original** public de l'auteur. `rjwalters/kicad-tools` pour kicad-tools, `circuit-synth/circuit-synth` pour circuit_synth. On ne le contrôle pas. |
| **Notre fork privé** | notre copie **modifiée et privée** : `bmechergui/kicad-tools` et `bmechergui/circuit-synth`. On la contrôle à 100 %. Seul nous (+ invités) voyons les patches. Branche de travail : `cirqix`. |
| **Submodule** | le dossier `services/kicad/<submodule>/` dans cirqix — **un pointeur** vers un commit précis (SHA) de notre fork privé. Pas une copie de fichiers. |

**Analogie :** upstream = l'usine qui fabrique le logiciel. Nous = le client qui l'achète, le
modifie, et de temps en temps récupère la nouvelle version de l'usine (en validant).
Le submodule = un signet dans le livre cirqix qui dit *« voir le livre `<submodule>`, page X »*.

**Inventaire des deux sous-modules** (`.gitmodules` — URLs HTTPS, `branch = cirqix`) :

| Sous-module | Path | Upstream | Fork privé (branch `cirqix`) |
|---|---|---|---|
| kicad-tools | `services/kicad/kicad-tools/` | `rjwalters/kicad-tools` | `bmechergui/kicad-tools` |
| circuit_synth | `services/kicad/circuit_synth/` | `circuit-synth/circuit-synth` | `bmechergui/circuit-synth` |

---

## 2. Pourquoi cette stratégie

Cirqix applique des **patches** (corrections) sur kicad-tools et circuit_synth qui ne
sont pas (encore) dans l'upstream. Sans stratégie Git propre, on avait un **dossier
gitignoré copié en dur** :
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
upstream (main, public)         rjwalters/kicad-tools        circuit-synth/circuit-synth
       │                              │                              │
       │  sync hebdo auto (Action sur chaque fork privé)             │
       ▼                              ▼                              ▼
  NOTRE FORK PRIVÉ (branch « cirqix » = upstream/main + nos patches, 1 patch = 1 commit + 1 test garde)
       bmechergui/kicad-tools        bmechergui/circuit-synth
       │                              │                              │
       │  piné à un commit SHA précis (gitlink dans cirqix)          │
       ▼                              ▼                              ▼
  bmechergui/cirqix (LE SaaS)
    services/kicad/kicad-tools/   = GIT SUBMODULE → bmechergui/kicad-tools@cirqix
    services/kicad/circuit_synth/ = GIT SUBMODULE → bmechergui/circuit-synth@cirqix
```

---

## 4. Les DEUX flux (bien les distinguer)

Cirqix échange avec les sous-modules dans **deux sens opposés**. Suivre le bon flux
selon ce qu'on fait ; ne jamais mélanger.

### 4.1 FLUX A — « Je modifie le sous-module » (patch : **local → cloud**)

Tu corriges un bug dans kicad-tools ou circuit_synth lui-même. Rien d'automatique :
le submodule est un repo niché dans cirqix, chaque repo garde son historique, donc
**2 commits + 2 pushes**.

```
┌─────────────────────────────────────────────────────────────────┐
│  PUSH 1 → vers le repo du fork privé (branche cirqix)           │
├─────────────────────────────────────────────────────────────────┤
│  cd services/kicad/<submodule>            # kicad-tools OU circuit_synth │
│  git checkout cirqix                                            │
│  git add <fichier modifié>                                      │
│  git commit -m "fix: ma correction"                             │
│  git push origin cirqix              ← push 1 (fork privé)      │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼  (le pointeur submodule a avancé dans cirqix)
┌─────────────────────────────────────────────────────────────────┐
│  PUSH 2 → vers le repo cirqix (bump du pointeur + PR)           │
├─────────────────────────────────────────────────────────────────┤
│  cd <racine cirqix>                                             │
│  git checkout -b fix/<ce-que-je-fais>                           │
│  git add services/kicad/<submodule>       ← le nouveau SHA      │
│  git commit -m "chore: bump <submodule> -> <sha-court>"         │
│  git push -u origin fix/<ce-que-je-fais>                        │
│  gh pr create --title "..." --body "..."                        │
└─────────────────────────────────────────────────────────────────┘
```

> 👉 En pratique, c'est **Claude** qui tape ces commandes (règle Cirqix :
> l'utilisateur ne fait jamais le git). Tu dis « applique le patch X sur
> kicad-tools », Claude fait les 2 pushes et ouvre la PR de bump.

⚠️ **Tag de pin obligatoire sur le fork** (vécu sur circuit_synth `302e22d`) :
la Porte 1 (rebase hebdo) force-push `cirqix` → les SHA épinglés deviennent
orphelins et GitHub refuse de les servir (`upload-pack: not our ref`, CI cassée).
**À chaque bump de gitlink, pousser en plus le tag `cirqix-pin-<short>` sur le
fork AVANT de merger la PR** (ex. `cirqix-pin-302e22d`, `cirqix-pin-c2482b8`).
Les vieux tags peuvent être supprimés une fois le gitlink avancé.

### 4.2 FLUX B — « Upstream publie » (**cloud → fork → cirqix → local**)

L'auteur publie de nouveaux commits sur `upstream/main`. On veut les récupérer
**sans rien casser**. Pipeline à **4 Portes** (2 auto, 2 humaines) — voir
détails §5, §6.

```
upstream <submodule>  ──(nouveaux commits)──┐
                                            │
   ┌────────────────────────────────────────┘
   ▼
🚪 PORTE 1 (AUTO — lundi, sur le FORK)
   sync-upstream.yml rebases « cirqix » sur upstream/main.
   • Rebase propre   → force-push direct sur cirqix (PAS de PR).
   • Conflit         → ouvre une issue (gh api REST) → va en Porte 2.
        │
        ▼  (seulement si issue ouverte)
🚪 PORTE 2 (TOI — sur le fork, SEULEMENT si conflit)
   Résoudre à la main (git rebase --skip si patch devenu redondant,
   ou merge manuel), tester, force-push cirqix. Rien à faire sinon.
        │
        ▼
🚪 PORTE 3 (AUTO — mardi, sur CIRQIX)
   *-bump.yml compare FETCH_HEAD de cirqix (fork) vs SHA pinné dans cirqix.
   • Fork en avance → ouvre PR « chore: bump <submodule> -> <sha-court> »
     + le CI cirqix tourne (build Docker + tests).
   • Fork identique  → rien à faire.
        │
        ▼
🚪 PORTE 4 (TOI — sur cirqix)
   • CI vert → MERGE la PR → cirqix utilise le nouveau <submodule>. ✅
   • CI rouge → FERME / investigue.
```

**Règle d'or : rien n'atteint `main` de cirqix sans la Porte 4.**

---

## 5. Tableau récapitulatif — qui fait quoi aux 4 Portes

| Porte | Qui | Quand | Dépôt | Action |
|---|---|---|---|---|
| **1** | 🤖 Auto (cron GH Actions) | lundi **08:17 UTC** (kicad-tools) / **07:17 UTC** (circuit_synth) | fork privé | `sync-upstream.yml` rebase `cirqix` sur `upstream/main`. Propre → force-push direct. Conflit → issue (REST). |
| **2** | 🧑 Toi | si issue ouverte par Porte 1 | fork privé | Résoudre à la main (rebase local, `--skip` ou merge), tester, force-push `cirqix`. |
| **3** | 🤖 Auto (cron GH Actions) | mardi **08:27 UTC** (kicad-tools) / **08:43 UTC** (circuit_synth) | cirqix | `*-bump.yml` compare fork cirqix vs SHA pinné. En avance → PR `chore: bump <submodule> -> <sha-court>` (+ CI cirqix tourne). |
| **4** | 🧑 Toi | à la réception de la PR Porte 3 | cirqix | CI vert → merge. CI rouge → ferme / investigue. |

Notes :
- **Porte 1 ne crée jamais de PR de rebase** sur `cirqix`. Un rebase ne peut pas se
  fusionner via le bouton GitHub standard dans sa propre branche : `mergeable:
  CONFLICTING` quelle que soit la stratégie (merge commit, squash, rebase-merge —
  vérifié empiriquement le 2026-07-18 sur kicad-tools PR #2). Un rebase propre est
  déterministe et préserve chaque patch à l'identique (sinon git le signale comme
  conflit) → pas besoin de revue humaine sur ce chemin. D'où force-push direct.
- **Porte 1 ouvre les issues de conflit via REST**, pas `gh issue create` :
  `gh issue create` (mutation GraphQL `createIssue`) échoue avec
  `Resource not accessible by integration` sur un dépôt privé/perso même quand le
  token de run rapporte `Issues: write`. Fallback : `gh api --method POST
  repos/${GITHUB_REPOSITORY}/issues`. `gh pr create` est REST, non concerné.
  Prérequis côté dépôt : `default_workflow_permissions: write`
  (`gh api repos/<owner>/<repo>/actions/permissions/workflow`) — sans ça, le bloc
  `permissions:` du YAML ne suffit pas à débloquer push/issue.
- **Job `sync-health` (déployé — commit `4b7227f`, PR #57)** : les workflows
  `kicad-tools-bump.yml` et `circuit-synth-bump.yml` embarquent un job `sync-health`
  qui détecte le « silence ambigu » (fork en retard sur upstream = AUCUN PR de bump
  ne s'ouvre = silence indistinguable d'un upstream inactif). Il compare les deux
  refs par git pur et ouvre une issue **dans cirqix** (marqueur caché
  `<!-- sync-health:<submodule> -->`, dédup par le body, via `gh api` REST) si la
  branche `cirqix` du fork est en retard sur `upstream/main`. Côté circuit_synth
  (privé), ce job fetche le fork via la deploy key SSH (commit `c5efccc`).

---

## 6. C'est quoi un rebase ? (sections pédagogique)

### 6.1 Le mécanisme, pas à pas

Un `git rebase upstream/main` appliqué à la branche `cirqix` :
1. **décolle** tous les commits Cirqix (nos patches) qui ne sont pas dans upstream ;
2. **recule** la pointe de `cirqix` sur le nouveau `upstream/main` ;
3. **repose** nos commits un par un, dans l'ordre, sur cette nouvelle base.

Pour **chaque patch**, git teste s'il recolle proprement sur le nouvel upstream :
- **Clean ✅** = le patch touche des lignes qu'upstream n'a pas modifiées → git
  l'applique tel quel, on passe au suivant. Aucune intervention humaine.
- **Conflit ⚠️** = le patch touche des lignes qu'upstream a **également modifiées**
  (différemment) → git s'arrête, on entre en **Porte 2**.

```
Avant le rebase :              Après le rebase (clean) :

  C3 (patch #3) ──┐              upstream-main-new
  C2 (patch #2) ──┤                   │
  C1 (patch #1) ──┤                   ├── C1' (patch #1 rejoué)
                  │                   ├── C2' (patch #2 rejoué)
              upstream-main-old       ├── C3' (patch #3 rejoué)
                  │                   │
                  │                   ▼
                  ▼               cirqix (avancée propre)
              cirqix
```

### 6.2 Quand « clean » vs « conflit » : exemple réel du 2026-07-13

Le 2026-07-13, la Porte 1 de kicad-tools a détecté un conflit sur les patches **#6**
(angles pads absolus — `schema/pcb.py`, `router/io.py`) et **#8** (signe rotation
pads — `router/io.py`). Cause : l'upstream avait mergé entretemps les PR **#3903** et
**#3746** sur les mêmes lignes, avec un fix plus complet et testé contre l'oracle
`pcbnew` réel. Notre patch était donc **devenu redondant**.

Résolution (Porte 2, terminée le 2026-07-18) : `git rebase --skip` — abandon
intentionnel du patch devenu inutile. Validé par **50/51 tests de rotation** passés
(`test_rotation_convention.py`, `test_rotation_convention_audit.py`,
`test_footprint_rotation.py`). Force-push `cirqix` → `ef86defa`. Issue
[#1](https://github.com/bmechergui/kicad-tools/issues/1) et PR
[#2](https://github.com/bmechergui/kicad-tools/pull/2) fermées/mergées.

### 6.3 Pourquoi tu ne peux pas ignorer une Porte 2

Une Porte 2 non traitée **gèle le fork** :
- `cirqix` reste sur l'ancienne version d'upstream → cirqix ne profite d'aucune
  nouveauté en amont (fixes, perf, features).
- L'écart avec `upstream/main` **grandit** chaque semaine → le conflit grossit
  aussi → il sera de plus en plus dur à résoudre.
- La Porte 3, faute d'avance du fork, **n'ouvre aucune PR** dans cirqix = silence
  total côté SaaS.
- Rappel hebdomadaire automatique via l'issue de conflit (tant qu'elle reste ouverte).

**Trade-off accepté :** cirqix reste **stable** sur l'ancienne version pendant la
fenêtre de résolution — aucun risque pour la prod, juste du retard.

---

## 7. Statut privé/public — kicad-tools vs circuit_synth (point d'attention)

| Aspect | kicad-tools | circuit_synth |
|---|---|---|
| Statut historique | Privé depuis le départ | Était **PUBLIC** jusqu'au **2026-07-18**, désormais **privé** |
| Deploy key CI | `SUBMODULE_DEPLOY_KEY` | `CIRCUIT_SYNTH_DEPLOY_KEY` (ajoutée lors du passage privé) |
| Alias SSH côté CI | `git@github.com:bmechergui/kicad-tools.git` | `git@github.com-circuit-synth:bmechergui/circuit-synth.git` (alias dédié — **deux deploy keys ne peuvent pas partager l'hôte `github.com`**, GitHub fige l'identité sur la 1ʳᵉ clé acceptée) |
| `.gitmodules` | URL HTTPS | URL HTTPS (inchangé) |
| Auth côté CI | rewrite `insteadOf` SSH + deploy key (voir `ci.yml`, `*-bump.yml`) | idem |
| Auth côté local | credentials persos (SSH ou HTTPS + token) | idem — mais **attention** : désormais privé, voir §8 |

### Conséquences du passage privé de circuit_synth

1. **CI cirqix (`ci.yml`, job `kicad-docker`)** — met déjà en place la deploy key
   dédiée `CIRCUIT_SYNTH_DEPLOY_KEY` + l'alias SSH `github.com-circuit-synth`
   (voir bloc `Configure SSH deploy keys` dans `ci.yml`). Mise à jour livrée.
2. **`circuit-synth-bump.yml`** — deploy key `CIRCUIT_SYNTH_DEPLOY_KEY` branchée
   (voir commentaire du workflow). Le `GITHUB_TOKEN` de cirqix **n'avait aucun
   droit** sur le fork privé — sans deploy key, la Porte 3 cassait.
3. **Local développeur** — voir §8 (recette `gh auth setup-git` ou rewrite SSH
   permanent). Sans ça, `git submodule update` demande un mot de passe.

> ✅ La mise à jour CI cirqix correspondant au passage privé est **livrée** (PR #57,
> commits `c5efccc` + `4b7227f`) : deploy key `CIRCUIT_SYNTH_DEPLOY_KEY` + alias SSH
> `github.com-circuit-synth` dans `ci.yml` (job `kicad-docker`) et `circuit-synth-bump.yml`.
> Toute régression sur un clone CI du circuit_synth (erreur `could not read Username` ou
> `Permission denied (publickey)`) doit être rapprochée de ce changement de statut.

### Pourquoi `.gitmodules` reste en HTTPS

Les URLs restent en HTTPS dans `.gitmodules` (lisibles publiquement, neutres). La
traduction en SSH + deploy key se fait **à l'exécution** côté CI via
`git config --global url."git@github.com…".insteadOf "https://github.com…"` —
**rewrite chirurgical** qui ne touche QUE l'URL du submodule concerné, sans toucher
au checkout principal cirqix ni à l'autre submodule. Côté local, idem via
credentials persos ou rewrite global (voir §8).

---

## 8. Tirer les mises à jour sur sa machine (**CLOUD → LOCAL**)

Le réflexe à avoir quand la Porte 4 a mergé une PR de bump (ou que tu veux juste
synchro ta branche locale avec `main`).

### 8.1 Recette de base

```bash
# 1. Récupère les derniers commits de cirqix (y compris le bump du gitlink)
cd <racine cirqix>
git fetch origin
git checkout main
git pull --ff-only origin main

# 2. Met à jour le CONTENU des sous-modules (pas juste le pointeur)
git submodule update --init -- services/kicad/kicad-tools services/kicad/circuit_synth
```

⚠️ **Un `git pull` seul ne suffit pas.** Il met à jour le **pointeur** (le gitlink
dans cirqix), pas le **contenu** du sous-module sur disque. Sans l'étape 2, tu
aurais un `git status` qui te dirait « submodule pointer has changed » et un
dossier `services/kicad/<submodule>/` encore à l'ancien SHA — source de bugs
silencieux.

⚠️ **`submodules: true` sur `actions/checkout` est interdit ici** — il ferait un
nettoyage récursif qui visite les gitlinks optionnels historiques de Circuit-Synth
(inutiles à l'image, font échouer le job). On initialise **manuellement** les deux
seuls sous-modules directs de cirqix (même pattern qu'en CI — voir `ci.yml`,
`*-bump.yml`).

### 8.2 Piège circuit_synth devenu privé

Le fork `bmechergui/circuit-synth` est passé **privé le 2026-07-18**. Avant, un
simple clone HTTPS anonyme suffisait ; maintenant, `git submodule update` va te
demander un mot de passe (ou échouer en silent si non-interactif). Deux recettes
au choix :

```bash
# Option A — utiliser ton auth GitHub déjà configurée (recommandé)
gh auth setup-git    # enregistre ton token gh comme credential helper HTTPS

# Option B — rewrite SSH permanent pour tous les repos GitHub
git config --global url."git@github.com:".insteadOf "https://github.com/"
# (à condition d'avoir une clé SSH enregistrée sur ton compte GitHub)
```

Sans l'une de ces deux configs, tu verras :
```
Username for 'https://github.com': ^C
fatal: could not read Username for 'https://github.com': terminal prompts disabled
```

### 8.3 Piège detached HEAD

Après `git submodule update`, le sous-module est **toujours en HEAD détachée** (sur
le SHA précis pointé par cirqix — c'est attendu, c'est ce qu'on veut en tant que
*consommateur*). Si tu veux **coder** dans le sous-module (FLUX A), il faut
d'abord rebasculer sur la branche de travail :

```bash
cd services/kicad/<submodule>      # kicad-tools OU circuit_synth
git checkout cirqix                # indispensable avant tout commit
```

Sans ça, `git commit` fonctionne (crée un commit « orphan » détaché), mais tu ne
pourras pas le pousser proprement sur `cirqix` et tu perdras la trace du commit
au prochain `git submodule update`.

### 8.4 Inspecter le delta du fork sans bouger le pin

Tu veux voir ce que le fork a de plus que ce que cirqix a pinné, **sans bouger le
pointeur** (par exemple pour anticiper une Porte 3 ou décider de pousser une
avance manuelle) :

```bash
cd services/kicad/<submodule>
git fetch origin cirqix
git log HEAD..origin/cirqix --oneline    # ← ce que le fork a et qu'on n'a PAS pinné
git log origin/cirqix..HEAD --oneline    # ← ce qu'on a (rare : commits locaux non poussés)
```

Pour un diff complet contre upstream (plus rare — sert surtout pour préparer un
rebase manuel), voir §9.2.

---

## 9. Workflow quotidien — détails

### 9.1 Modifier le sous-module = FLUX A (rappel)

Voir §4.1. Les **2 pushes** (un vers le fork privé sur `cirqix`, un vers cirqix qui
bump le pointeur + ouvre une PR de validation). En pratique, c'est Claude qui tape
les commandes.

### 9.2 Vérifier la diff à la demande (n'importe quand)

Tu demandes à Claude : *« vérifie la différence entre notre kicad-tools et
upstream »*.

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

L'**Action hebdo** (Porte 1) fait la même chose automatiquement et ouvre une
issue/force-push. Sur circuit_synth, même pattern avec `cd services/kicad/circuit_synth`.

---

## 10. Runbook de mise à jour (quand on valide un update upstream — Porte 2)

```bash
# Sur le fork privé (branche cirqix)
cd services/kicad/<submodule>
git fetch upstream
git checkout cirqix
git rebase upstream/main          # rejoue les patches Cirqix encore nécessaires
# → résoudre les conflits éventuels patch par patch :
#   git rebase --skip              si le patch est devenu redondant (upstream a mergé le fix)
#   ou merge manuel + git add + git rebase --continue
git push origin cirqix --force-with-lease   # branche patchée = rebase = force OK

# Si le SHA pinné dans cirqix change, pousser le tag de pin AVANT de merger le bump
git tag cirqix-pin-$(git rev-parse --short HEAD)
git push origin cirqix-pin-$(git rev-parse --short HEAD)

# Puis dans cirqix (bump du pointeur) — Porte 4
cd <racine cirqix>
git checkout -b chore/bump-<submodule>-<sha-court>
git add services/kicad/<submodule>
git commit -m "chore: bump <submodule> -> upstream <sha>"
git push -u origin chore/bump-<submodule>-<sha-court>
gh pr create --title "..." --body "..."
# → pnpm type-check + Docker build + kct build-native + test route STM32
# → le juge = kicad-cli pcb drc (jamais le DRC interne seul)
# → CI vert → MERGE (Porte 4)
```

En production, la Porte 1 et la Porte 3 sont **automatisées par les Actions** —
l'humain ne fait que Porte 2 (si nécessaire) et Porte 4.

---

## 11. État actuel des patches kicad-tools (2026-07-11)

Base du snapshot actuel : upstream `main` commit `fda275d` (2026-06-13).
Upstream est **+197 commits / 300 fichiers** ahead (`5e6eef8`, 2026-07-10).

| # | Patch | Fichier | Statut |
|---|---|---|---|
| 1 | fsync Windows | `cli/route_cmd.py` | local (Windows-only) |
| 2 | net name-only KiCad 9+ | `reasoning/state.py` | local |
| 3 | layer_count 4/6 | `reasoning/interpreter.py` | local |
| 4 | CMA-ES writer 2-pass | `cli/optimize_placement_cmd.py` | local |
| 5 | CMA-ES seed="current" | `cli/optimize_placement_cmd.py` | local |
| 6 | angles pads absolus | `schema/pcb.py`, `router/io.py` | ⭐ **désormais upstream PR #3903** → résolu par `--skip` le 2026-07-18 (voir §6.2) |
| 7 | `KCT_SAFE_OPTIMIZE` | `router/optimizer/config.py` | local (diagnostic) |
| 8 | signe rotation pads (Y bas) | `router/io.py` | ⭐ **désormais upstream PR #3746** → résolu par `--skip` le 2026-07-18 (voir §6.2) |

> Le patch charmap Windows est **hors lib** (`tools/kct_route.py`), durable.
> Issue upstream **#3803** (« kct PASS vs kicad-cli 400+ violations ») = **fermée** upstream
> (PR #3815/#3816/#3817/#3830). Notre #8 adressait le même symptôme → désormais redondant.

**Bilan migration :** on part de 8 patches → on en garde **6** (#1–5, #7).

### 11.1 Patches circuit_synth

Deux patches seulement (détails dans `services/kicad/DEPENDENCIES.md`) :
- `kicad/sch_gen/circuit_loader.py` ~ligne 286 — **fix pin_identifier vide** :
  `pin_data["name"] not in ("~", "", None)` au lieu de `!= "~"` (sinon Device:R
  et Device:C → tous au même pin = R1.pin2 unconnected).
- `kicad/schematic/geometry_utils.py` — **fallback index-based** seulement si
  **toutes** les broches sont non numérotées ; jamais si un numéro explicite ne
  correspond (pour ne jamais connecter silencieusement la mauvaise broche).

Tests : `tests/unit/test_cirqix_empty_pin_name.py` +
`tests/unit/test_cirqix_pin_index_fallback.py` (3 scénarios). Base upstream :
v0.12.1 (`f52f491`).

---

## 12. Effort & tradeoffs

- **Effort mise en place :** ~1 journée (Claude fait le code ; l'utilisateur crée
  le repo privé vide en 1 clic). Pour circuit_synth, similaire — une fois le
  pipeline cloné de kicad-tools.
- **Tradeoff :** le CI initialise manuellement les deux sous-modules directs Cirqix
  (`git submodule update --init -- services/kicad/kicad-tools
  services/kicad/circuit_synth`). Ne pas utiliser l'option `submodules` d'
  `actions/checkout` : son nettoyage récursif visite les gitlinks optionnels
  historiques de Circuit-Synth, inutiles à l'image. (1 ligne de plus dans le
  Dockerfile + le bloc `Configure SSH deploy keys` dans `ci.yml`).
  Le CI clone des repos privés → **2 deploy keys SSH** dédiées
  (`SUBMODULE_DEPLOY_KEY` + `CIRCUIT_SYNTH_DEPLOY_KEY`, alias
  `github.com-circuit-synth` pour la 2ᵉ car deux deploy keys ne peuvent pas
  partager l'hôte).
- **Tradeoff tags de pin :** chaque bump de gitlink exige un tag `cirqix-pin-<short>`
  sur le fork, sinon le rebase hebdo (force-push) orphelinise le SHA et le CI
  casse (`upload-pack: not our ref`, vécu sur `302e22d`). À automatiser plus tard
  si besoin.
- **Bénéfice long terme (Phase D) :** ouvrir de vrais PR upstream pour les patches
  généraux (#2 KiCad 10, #3 layer_count, #1 fsync) → une fois mergés, on les
  supprime de la branche `cirqix` → convergence vers **zéro patch**.

---

## 13. Fichiers concernés

- `services/kicad/kicad-tools/` — submodule (pointeur vers `bmechergui/kicad-tools@cirqix`)
- `services/kicad/circuit_synth/` — submodule (pointeur vers `bmechergui/circuit-synth@cirqix`)
- `.gitmodules` — déclare les deux submodules (URLs HTTPS, `branch = cirqix`)
- `services/kicad/Dockerfile` — `git submodule update --init` au build
- `services/kicad/DEPENDENCIES.md` — runbook détaillé des patches par sous-module
- `.github/workflows/kicad-tools-bump.yml` — Porte 3 kicad-tools (sur cirqix, mardi 08:27 UTC)
- `.github/workflows/circuit-synth-bump.yml` — Porte 3 circuit_synth (sur cirqix, mardi 08:43 UTC)
- `.github/workflows/ci.yml` — job `kicad-docker` : init manuel des 2 submodules + deploy keys SSH
- `sync-upstream.yml` — Porte 1 (vit sur chaque fork privé, lundi — pas dans cirqix)
- `CLAUDE.md` — référence cette stratégie (section « Dépendances Git »)

---

## 14. Étapes de mise en place (checklist — kicad-tools)

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
- [x] **#6/#8 auto-supprimés au prochain rebase** upstream (résolus manuellement le
  2026-07-18 via `git rebase --skip` — voir §6.2)
- [x] **Validation finale** (2026-07-12, Docker WSL) : `docker compose build kicad` ✓ + `kct build-native --check` → *C++ backend available v1.0.0* ✓ + route board STM32 dans l'image → placement 17 composants 0 conflit, routage natif **91%** (SWDIO 1/2 — pris en charge par le Reasoner ⑥b en prod), `kicad-cli pcb drc` opérationnel (juge) → merge PR #47.
  ⚠️ Bug trouvé pendant la validation : le Dockerfile n'installait pas `make` → `kct build-native` échouait silencieusement dans l'image (générateur cmake « Unix Makefiles » sans make) → fallback routeur Python pur. Fix : paquet `make` ajouté à l'apt install.

### 14.1 Mise en place circuit_synth (résumée)

> ✅ **Terminée** — même modèle que kicad-tools (PR cirqix #54 + commits associés).
> Fork privé `bmechergui/circuit-synth` (branche `cirqix`), passé privé le 2026-07-18.

- [x] Fork privé `bmechergui/circuit-synth` créé (branche `cirqix` + 2 patches Cirqix)
- [x] `services/kicad/circuit_synth/` converti en submodule (`branch = cirqix`)
- [x] `sync-upstream.yml` déployé sur le fork (lundi 07:17 UTC) — vit sur `main` du fork
- [x] `circuit-synth-bump.yml` déployé sur cirqix (mardi 08:43 UTC)
- [x] **Passage privé 2026-07-18** : deploy key `CIRCUIT_SYNTH_DEPLOY_KEY` + alias
  SSH `github.com-circuit-synth` déployés dans `ci.yml` (job `kicad-docker`) et
  `circuit-synth-bump.yml`
- [x] Issue de conflit Porte 1 par `gh api` REST (pas `gh issue create`)
- [x] **Mise à jour CI cirqix pour le passage privé** (PR #57) — deploy key
  `CIRCUIT_SYNTH_DEPLOY_KEY` + alias SSH `github.com-circuit-synth` livrés dans
  `ci.yml` (job `kicad-docker`) et `circuit-synth-bump.yml`. À surveiller en cas
  de régression.

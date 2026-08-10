# RL PCB Cirqix — pipelines & phases (source de vérité)

> Lab seulement tant que les gates sont NO-GO.
> **Prod inchangée** tant qu’aucun flag GO : hybrid + CMA-ES (place) · routage conditionnel
> (voir § Prod) · reasoner si % &lt; 100.

## Contrat unique (2026-08-02)

| Élément | Contrat réel (code) |
|---------|---------------------|
| **Hard gate** | Implémentée dans `tools/rl/quality_gate.py` |
| **Où elle est branchée** | **Éval** : `eval_route_arms.py` · **Pipeline lab** : `run_phase_pipeline.py` (après route) |
| **Exit pipeline** | Piloté par hard gate (pas seulement KCT ok / % &gt; 0) ; `--skip-route` / `--skip-hard-gate` = pas d’autorité GO |
| **Phase 5** | **PARTIAL** — hard gate branchée ; **lab GO** LED clean+full kct (2026-08-05) ; multi-board CI encore ouvert |
| **GO prod / déploiement** | **OFF** — lab hard-gate GO ≠ flag Phase 6 ; e2e multi-board + Dreamer/FR place encore manquants |
| **Gates A/B historiques** | **Legacy** — non éligibles au GO (voir placement PLAN) |

> Hard gate : **éval** (`eval_route_arms`) **et** pipeline lab (`run_phase_pipeline`).
> Exit pipeline piloté par la gate. Phase 5 reste PARTIAL si `kicad-cli` absent en CI.

### Hard gate — règles effectives

Code : `evaluate_board_hard_gate()` dans `quality_gate.py`.

| Check | Obligatoire par défaut ? |
|-------|---------------------------|
| `error_conflicts == 0` | **Oui** (fail si non mesuré) |
| `routed_percent >= 100` | **Oui** |
| `unrouted_count == 0` | **Non** par défaut (`require_unrouted_count=False`) ; fail seulement si mesuré et ≠ 0 |
| `drc_error_count == 0` | **Oui** si `require_drc=True` (défaut) — **fail-closed** si non mesuré |
| `unconnected_items == 0` | **Oui** si `require_unconnected=True` (défaut) — **fail-closed** si non mesuré |

`eval_route_arms` appelle la hard gate avec `require_unrouted_count=False` (DRC/unconnected requis).
Donc aujourd’hui un board **sans DRC mesuré** → **NO-GO hard** (fail-closed).
`unrouted_count` n’est **pas** dans la chaîne obligatoire tant que le flag n’est pas activé.

**Cible doc (quand instrumenté partout) :** rendre `unrouted_count` obligatoire aussi.
**État code actuel :** ne pas prétendre qu’il l’est déjà.

### Filet kicad-tools vs autorité fab (kicad-cli sur le **worker**)

Politique figée (lab RL **et** prod cloud) :

| Niveau | Outils | Où ça tourne | Rôle |
|--------|--------|--------------|------|
| **Filet** (rapide, toujours possible) | **ERC-like** : `Schematic.validate()` / `kct sch validate` · **DRC-like** : `kct check --mfr jlcpcb` (règles fab Python) | Worker Cirqix (kicad-tools only) | Pré-filtre, lab RL, itérations, CI sans image KiCad complète |
| **Autorité fab** (GO / commande / hard gate) | **ERC officiel** : `kicad-cli sch erc` (via `kct erc` si dispo) · **DRC officiel** : `kicad-cli pcb drc` (via chemin DRC prod) | **Même worker Docker**, image avec KiCad | Juge final fabricable |

```text
User (navigateur)     →  PAS de KiCad installé
Worker Docker Cirqix  →  kicad-tools (filet)  +  kicad-cli (autorité fab)
```

| On peut | On ne peut pas |
|---------|----------------|
| S’appuyer sur **filet only** pour lab / smoke / pré-filtre | Déclarer `DRC_CLEAN` / GO hard gate / order JLCPCB **sans** DRC officiel mesuré |
| **Ne pas** appeler `kct erc` / `kct drc` en lab si on accepte le filet | Prétendre que `kct check` = DRC KiCad (faux négatifs mesurés historiquement) |
| Scale = **N workers** avec KiCad **dans l’image** | Imposer KiCad sur le PC de chaque utilisateur |

**Résumé :**  
**filet = kicad-tools only** · **autorité fab = kicad-cli sur le worker** (pas chez l’utilisateur).

---

## Rôles — manager / opérateur / géométrie / physique

Vocabulaire **canonique** Cirqix RL (ne pas confondre) :

| Rôle | Qui | Fait quoi |
|------|-----|-----------|
| **Manager** (stratégie) | **PPO** ou **DreamerV3** | Choisit *quoi* faire (net, strategy, stop…) |
| **Opérateur** (exécution) | **KCT** (kicad-tools) | Exécute l’action demandée |
| **Géométrie** | **KCT** (même couche que l’opérateur) | Pose pistes, vias, positions X/Y |
| **Physique** / juge | ERROR · DRC · unconnected · hard gate | Dit si c’est légal / fabricable → reward + GO/NO-GO |

```text
┌─────────────────────────────────────┐
│  MANAGER  =  PPO  ou  DreamerV3     │
│  « quel net / strategy / stop »     │
└─────────────────┬───────────────────┘
                  │ action
                  ▼
┌─────────────────────────────────────┐
│  OPÉRATEUR + GÉOMÉTRIE  =  KCT      │
│  route_net · kct_net · place · CMA  │
└─────────────────┬───────────────────┘
                  │ board + métriques
                  ▼
┌─────────────────────────────────────┐
│  PHYSIQUE / JUGE                    │
│  ERROR · DRC · unconnected · %      │
│  → reward RL + hard gate GO/NO-GO   │
└─────────────────────────────────────┘
```

**Une phrase par mot :**

| Mot | Signifie |
|-----|----------|
| **Manager** | Cerveau RL — **décide** |
| **Opérateur** | Main qui exécute — **KCT** |
| **Géométrie** | Ce que la main dessine — **fait par KCT** |
| **Physique** | Est-ce légal / fabricable ? — **DRC / conflicts / hard gate** |

→ **Opérateur ≈ géométrie** (KCT en principal ; **FR** en fallback cible).  
→ **Physique** = validation *après* (ou pendant) la géométrie.  
→ **KCT / FR ne sont pas le manager.** **PPO et Dreamer ne dessinent pas les pistes.**

### Objectif route — 2 étapes de **choix** (feuille de route)

On **choisit d’abord le manager** sur KCT, **puis** le couple manager+fallback FR.

| Étape | Question | Comparaison | Opérateur |
|-------|----------|-------------|-----------|
| **1 — Principal** | Quel manager ? | **PPO vs DreamerV3** (même env, mêmes actions/obs) | **KCT** (`kct_net` / `route_net` / batch) |
| **2 — Fallback** | Quel manager en secours ? | **PPO vs DreamerV3** (même contrat d’actions si possible) | **FR** (FreeRouting — reprise partielle) |

```text
Étape 1 (obligatoire d’abord)
  Manager ∈ {PPO, DreamerV3}  +  opérateur KCT
  → best-of / hard gate → retenir le meilleur manager pour KCT

Étape 2 (après étape 1 stabilisée)
  Manager ∈ {PPO, DreamerV3}  +  opérateur FR
  → best-of / hard gate → retenir le meilleur couple fallback

Prod / lab pipeline (cible) :
  Manager* + KCT  →  si hard fail / % < 100  →  Manager† + FR  →  hard gate
  (* / † = gagnants des comparaisons, éventuellement le même algo)
```

| Règle | Détail |
|-------|--------|
| Un manager à la fois par bras | Pas PPO+Dreamer en parallèle en prod |
| Même env pour comparer | PPO et Dreamer partagent actions/obs/reward **par opérateur** |
| Ordre | **Ne pas** prioriser FR avant d’avoir un manager viable sur **KCT** |
| Interim lab | `kct_alt` (2ᵉ passe KCT) peut servir de secours **en attendant** le bras manager+FR |

### PPO ou Dreamer = le manager (route **et** place)

| Phase | Algo manager | Opérateur |
|-------|----------------|-----------|
| Lab / transition | **PPO** | KCT (étape 1) |
| Cible principal | **DreamerV3** ou gagnant PPO↔Dreamer | **KCT** |
| Cible fallback | Gagnant PPO↔Dreamer (étape 2) | **FR** |
| Comparaison lab | **PPO vs Dreamer** | D’abord KCT, **puis** FR |

- Seul change entre PPO et Dreamer : **comment** on choisit l’action (et le world model).  
- Le **reward** ne dépend pas de l’algo : métriques opérateur + hard gate.

```text
PCB courant
  → encodeur CNN/GNN (± Transformer)
  → policy / world model
       ├─ PPO        (transition)
       └─ DreamerV3  (cible)
  → action stratégique
  → opérateur géométrie : KCT (principal) | FR (fallback)
  → métriques → reward
```

### Place vs route (même découpage)

| | Manager | Opérateur / géométrie | Physique |
|--|---------|------------------------|----------|
| **Route (principal)** | PPO \| Dreamer | **KCT** `kct_net` / batch | %, DRC, unconnected |
| **Route (fallback)** | PPO \| Dreamer | **FR** (cible étape 2) | idem + hard gate |
| **Place** | PPO \| Dreamer (cible) | hybrid + **CMA 1×** (+ bras RL) | ERROR place, dérive 20 mm, hard gate |

### Ce qui n’est **pas** le manager

| Non-manager | Rôle réel |
|-------------|-----------|
| KCT | Opérateur + géométrie **principal** |
| FR | Opérateur + géométrie **fallback** (cible étape 2) |
| CMA 1× | Opérateur place (refine fixe prod) |
| `kct_alt` | Interim secours KCT (en attendant manager+FR) |
| Hard gate / DRC | Physique / autorité GO |

---

## Décisions d’architecture (manager + KCT puis manager + FR)

| Décision | Choix |
|----------|--------|
| Rôle RL | **Manager stratégique** (PPO \| Dreamer) — **pas** le géomètre |
| Étape 1 | Comparer **PPO vs Dreamer** + opérateur **KCT** → choisir le manager principal |
| Étape 2 | Comparer **PPO vs Dreamer** + opérateur **FR** → choisir le fallback |
| Place RL | Best-of vs **CMA 1×** ; **PPO vs Dreamer** ; méta short/long = **legacy** ; **NO-GO prod** |
| Livraison | Best-of vs baseline ; hard gate ; jamais pire |

**Paper :** Liao/Pan/Chiang 2026 DreamerV3+FR
([ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0957417426003374)).
Traduction Cirqix : manager = PPO\|Dreamer ; opérateur principal **KCT** ; fallback **FR** (après choix manager sur KCT) ; physique = hard gate.

---

## Architecture cible — manager + KCT (+ FR fallback)

```text
Manager (PPO | DreamerV3)     = stratégique
KCT                           = opérateur principal + géométrie
FR                            = opérateur fallback + géométrie (étape 2)
Hard gate / DRC               = physique / juge

# Étape 1
PCB → encodeur → PPO|Dreamer → action → KCT → métriques → reward / hard gate

# Étape 2 (si principal insuffisant)
PCB partiel → encodeur → PPO|Dreamer → action → FR → métriques → reward / hard gate
```

### Strategy (stratégie) — taxonomie **proposée Cirqix**

> **Taxonomie Cirqix proposée — mapping KCT partiel ; non extraite
> de l’article.** L’article soutient le rôle manager / ordre des nets ;
> le dépôt public expose 100 actions discrètes **sans** dictionnaire Java
> publié pour chaque ID.

| `strategy` (proposé) | Intention |
|----------------------|-----------|
| `shortest` | piste courte |
| `low_vias` | minimiser vias |
| `low_congestion` | éviter congestion |
| `preferred_layer` | privilégier F.Cu / B.Cu |
| `power` | rails larges |
| `ripup_retry` | rip-up puis retry |
| `balanced` | compromis |
| `vcc_traces` / `vcc_planes` | flags power Cirqix (mappé en partie sur `vcc_as_traces`) |

Exemple d’action manager :

```json
{ "net_id": 12, "strategy": "low_vias", "preferred_layer": "F.Cu", "ripup": false }
```

### Espace d’actions

| | |
|--|--|
| **Legacy route** | 0/1/2 = kct vcc traces / planes / stop — **sélecteur full-board** |
| **Manager route** | net/groupe, strategy, stop (`ManagerRoutingEnv` + `kct_net`) |
| **Legacy place** | short/long/stop méta-CMA — **non cible** |
| **Cible place** | placeur RL (PPO\|Dreamer) best-of vs CMA 1× |

### Observation / reward

Obs : métriques manager (+ spatiale GNN/CNN **cible**).  
Reward : connectivité / −step / −vias-length / −ERROR ; succès lab = hard gate.

### API opérateur route (état)

```text
route_net(board, net_id, strategy, backend=mock|kct_net|kct_full)
  mock     — TDD
  kct_net  — kct route --nets NAME  (géométrie par net — livré)
  kct_full — full-board proxy lab-only
```

---

## Pipeline **production** (réel, conditionnel)

Ne pas simplifier en « kct → FR → reasoner » linéaire.

```text
POST /route/auto (services/kicad/routers/routing.py) :

  si board « simple » (≤30 nets et ≤30 comps) :
      kicad-tools A* / chemin kct
      si routed_percent >= 95 → ACCEPTÉ (retour)
      si < 95 → garder partial, tenter Freerouting
  Freerouting (API puis subprocess) sur PCB d’entrée (tracks purgés en Specctra)
  sinon skipped / partial

Orchestrateur agents (packages/agents) :
  si shouldRescueRouting (typ. % < 100) → reasoner
```

| Fait prod | Fait lab RL (cible) |
|-----------|---------------------|
| FR souvent depuis **entrée** clean tracks | Manager reprend **board partiel post-kct** |
| Accept kct dès **≥ 95 %** sur simple | Hard gate exige **100 %** + DRC + unconnected |
| Reasoner si résultat &lt; 100 % | Reste filet prod |

---

## Pipeline lab cible (manager)

```text
Place : hybrid → CMA baseline | RL candidat → best-of
Route : manager (Dreamer|PPO) → KCT incrémental (cible)
        si hard fail → manager → FR (cible reprise partielle)
        reasoner prod si encore besoin
Juge  : hard gate (quand branchée) + best-of vs kct full
```

---

## État lab (héritage — NO-GO prod)

| Domaine | Réalité | Verdict |
|---------|---------|---------|
| Place PPO+kct méta | short/long/stop ; 400 steps | **Legacy lab** / NO-GO prod |
| Place RL cible | PPO vs Dreamer ; best-of vs CMA **1×** ; GNN±Transformer | TODO env |
| Route grille PPO | ~17 % vs kct | NO-GO |
| Route PPO+kct 3 actions | sélecteur ; mock 512 / real 16 | NO-GO |
| Hard gate module | `quality_gate.py` + tests | **éval + pipeline** |
| Phase 5 pipeline | `run_phase_pipeline.py` | **PARTIAL** (hard gate branchée ; DRC host-dependent) |
| DreamerV3 | non branché | TODO |

### Statut route_net / manager (ne pas confondre)

| Livrable | Statut | Note |
|----------|--------|------|
| API + mock `route_net` | **livré** | TDD / PPO-transition |
| Proxy `backend=kct_full` | **livré, non incrémental** | lab-only ; 1× full-board |
| Vrai routage géométrique **par net** | **livré (`kct_net`)** | `kct route --nets` via `route_kct_net` |
| PPO manager (`--env manager`) | **code + train mock** | train **non validé** hard gate / `kct_net` réel |
| Bras secondaire lab (ex-« FR ») | **kicad-tools only** | `route_kct(vcc_as_traces=False)` — **pas** pcbnew |

---

## Phases 0–6

### Phase 0 — Gel prod ✓

### Phase 1 — Env opérateurs — **évoluer**

Fait : wrappers sélecteur v1 + API/mock `route_net` + `kct_net` + proxy `kct_full`.
Suite : obs spatiale + stratégies riches.

### Phase 2 — Placement

**Prod safe :** hybrid → **1× CMA** (toujours) ; RL optionnel en **best-of** (flag).  
**Cible :** placeur RL **PPO vs DreamerV3** (même env ; encodeurs **GNN** + **Transformer** optionnel) — **pas** RL méta short/long/stop.  
Méta-CMA 400 steps = **legacy lab**. Gate A/B = **legacy**.  
Autorité : hard gate toutes cartes + DRC (voir [placement/PLAN.md](placement/PLAN.md)).

### Phase 3 — Manager + KCT — **PARTIAL**

- Env manager + PPO mock : code présent ; train mock 5k (non validé hard gate).
- `kct_net` : vrai par-net via `kct route --nets`.
- `kct_full` : proxy full-board lab-only.
- Legacy sélecteur 3 actions = smoke only.

### Phase 4 — Manager + FR fallback (cible lab)

### Phase 5 — Pipeline intégré — **PARTIAL**

- [x] Script `run_phase_pipeline.py` (best-of %, flags)
- [x] Appel `evaluate_final_hard_gate` → `quality_gate.evaluate_board_hard_gate`
- [x] Mesure ERROR place + tentative kicad-cli DRC/unconnected (fail-closed si absent)
- [x] Comparaison baseline vs bras kct
- [x] Exit code = hard gate (sauf `--skip-route` / `--skip-hard-gate`)
- [x] FR : % via `estimate_routed_percent_from_pcb` (segments/vias vs multi-pad)
- [ ] DRC mesurable de façon fiable en CI Docker (kicad-cli)
- [ ] unrouted_count instrumenté

**Phase 5 ≠ DONE prod** tant que DRC/unconnected ne sont pas mesurables en CI.
Aucun GO déploiement.

### Phase 6 — Flag prod **OFF**

Hard gate + e2e + best-of prod ; jamais sur GO-A/B legacy.

---

## Ordre de livraison

```text
1. Doc contrat unique (ce fichier) ✓
2. Hard gate dans run_phase_pipeline ✓
3. API route_net mock + ManagerRoutingEnv ✓
4. PPO-transition mock manager ✓ (train non validé hard gate)
5. Sync état kct_full + bras secondaire kct_alt ✓
6. route_net réel par net (`kct_net` / `--nets`) ✓
7. Eval manager + hard gate ; train `kct_net` validé  ← prochaine
8. Obs spatiale + stratégies riches
9. DreamerV3 + KCT
10. Phase 6 seulement si hard gate + e2e + kicad-cli CI
```

---

## Réseaux (options encodeur)

| Rôle | Archi |
|------|--------|
| Encodeur place | **GNN** prioritaire |
| Encodeur route | CNN / GNN (obs spatiale cible) |
| Glue optionnelle | **Transformer** |
| Policy / world model | DreamerV3 (cible) ; **PPO** (transition, **même env**) |
| Opérateur place | hybrid + **1× CMA** (prod) ; RL candidat best-of |
| Opérateur route | KCT (`kct_net` / full) — hors réseau |

Détail place : [placement/PLAN.md](placement/PLAN.md) · route : [routing/PLAN.md](routing/PLAN.md).

### Schéma optionnel encodeurs

```text
# Place (cible PPO vs Dreamer)
GNN (composants/nets) → [Transformer option] → [CNN occupancy option] → PPO|Dreamer
  → candidat placement → best-of vs CMA 1×

# Route (manager)
GNN/CNN → [T option] → PPO|Dreamer → route_net / KCT
```

---

## Code & docs

| Chemin | Rôle |
|--------|------|
| `docs/rl/README.md` | Source de vérité |
| `docs/rl/PHASES_STATUS.md` | Statut / audit |
| `docs/rl/routing/` | Manager + KCT |
| `docs/rl/placement/` | Place best-of + legacy gates |
| `tools/rl/quality_gate.py` | Hard gate (éval **et** pipeline) |
| `tools/rl/run_phase_pipeline.py` | Pipeline lab **avec** hard gate (exit = gate) |
| `tools/rl/routing/route_net_api.py` | mock + proxy `kct_full` + estimate FR % |
| `tools/rl/routing/manager_env.py` | Env manager (net+strategy) |
| `tools/rl/placement/eval_route_arms.py` | Hard gate branchée |

---

## Critères de succès

1. Phase 5 appelle hard gate + baseline.
2. Manager + `route_net` compétitif vs kct full sous hard gate.
3. Best-of jamais pire que prod.
4. Aucun déploiement sur GO-A/B legacy.

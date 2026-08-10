# PLAN — RL placement (Phase 6a)

Plan d'implémentation étape par étape. La spec et les critères d'abandon
restent dans [README.md](README.md) ; ce fichier décrit l'ordre des travaux.

## Pipeline

```text
LLM strategy (groupes, ancres, nets sensibles)
  → Architecte kicad-tools (hybrid + clusters)
  → Inspecteur initial (PlacementAnalyzer)
  → snapshot pré-RL
  → candidat RL placement (PPO/MLP, inférence bornée)
  → Inspecteur final (PlacementAnalyzer + PlacementFixer)
  → décision :
      ERROR restant ou dérive > 20 mm  → restore snapshot
      sinon                            → comparer FOM vs CMA-ES, garder le meilleur propre
```

Le RL ne touche que les composants non ancrés. KiCad/`kicad-cli` reste le
juge final en bout de pipeline produit.

## Étapes

### 1. `reward.py` — adaptateur FOM ✅ (2026-07-28)

Envelopper `compute_fom()` de `kicad-tools` tel quel (compacité, wirelength,
groupes, collisions, hors-carte). Aucune réinvention du score.

- Validation : sur 3 fixtures, `reward.py` reproduit exactement le FOM calculé
  en appel direct. → `tests/test_rl_placement_reward.py` (4 verts).

### 2. `observation.py` — tenseur d'état ✅ (2026-07-28)

PCB + contraintes → tenseur fixe `OBS_DIM` : positions normalisées, pads,
present/anchored, contour. Ancres `J*`/`P*` + extras optionnels.

- Validation : shape/dtype fixes et déterministes → `test_rl_placement_env.py`.

### 3. `env.py` — Gymnasium PlacementEnv ✅ (2026-07-28)

`reset()` / `step()`. Action MultiDiscrete (slot, dx, dy). Reward = Δ FOM.
kicad-tools `PCB` only. Ancres immobiles.

- Validation : ancres fixes + déplacement mobile → `test_rl_placement_env.py`.

### 4. Smoke run 100 k pas (go/no-go de coût) — script prêt, run long à faire

Script : `tools/rl/placement/train_placement.py`
(`--algo random` sans SB3 ; `--algo ppo` si `stable-baselines3` installé).

```bash
cd services/kicad
python -m tools.rl.placement.train_placement \
  --pcb examples/led-blinker-full-pipeline/output/5_placed.kicad_pcb \
  --steps 100000 --algo random --board-width 60 --board-height 45
```

- Validation : débit mesuré compatible avec le budget 2–8 h GPU annoncé ;
  sinon, réviser le chiffrage avant toute suite. **Smoke 100k pas encore
  non exécuté en CI** (coût) — lancer manuellement et mettre à jour
  [../README.md](../README.md) « Coûts estimés ».

### 5. Entraînement 1–5 M pas

Run complet sur les fixtures. Modèle versionné avec le commit `kicad-tools`
et la version KiCad. Toutes les trajectoires sont loggées (`obs`, `action`,
`reward`, `done`) en npz/jsonl par épisode — c'est le futur replay buffer
d'un éventuel switch DreamerV3 (voir « Chemin de migration » dans
[../README.md](../README.md)).

- Validation : courbe de reward convergente ; checkpoint sauvegardé ;
  trajectoires loggées et relisibles.

### 6. `candidate.py` + `policy.py` — inférence

`policy.py` charge le modèle en lecture seule ; `candidate.py` applique le
candidat via l'API **kicad-tools ``PCB``** (positions + save) avec
snapshot/revert — **pas de pcbnew** dans la boucle RL (aligné Phase 6a v1).

- Validation : inférence < 1 s par candidat ; le revert restaure le snapshot
  à l'identique.

### 7. Intégration `tools/placement.py::auto_place` (feature flag)

Le candidat RL remplace progressivement le micro-raffinement CMA-ES, sans
supprimer le chemin actuel. Fallback placement hybride si RL indisponible.
Le contrôle de dérive appelle `_max_displacement_mm()` et
`_CMAES_MAX_DISPLACEMENT_MM` existants (pas de constante dupliquée), et la
comparaison FOM utilise la même configuration de poids `compute_fom()` des
deux côtés.

- Validation : pipeline inchangé quand le flag est off ; le contrôle de
  dérive réutilise les primitives de `tools/placement.py`.

### 8. Mesure du critère de vie ou de mort

Comparer le FOM du candidat RL vs CMA-ES sur ≥ 10 fixtures représentatives,
à configuration `compute_fom()` identique. Le FOM étant un proxy de
routabilité, la mesure inclut le taux de routage effectivement obtenu en
aval sur un échantillon des fixtures.

- **Go Phase 6a** : RL bat CMA-ES de > 5 % de FOM.
- **Abandon** : sinon — le placement hybride reste le chemin unique, le code
  RL est retiré ou archivé. Un échec documenté est un résultat valide.

## Rappel des invariants

Un candidat n'est jamais livré sans les quality gates réels. La Phase 6b
(encodeur GNN) ne démarre qu'après un go mesuré à l'étape 8.

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

### 1. `reward.py` — adaptateur FOM

Envelopper `compute_fom()` de `kicad-tools` tel quel (compacité, wirelength,
groupes, collisions, hors-carte). Aucune réinvention du score.

- Validation : sur 3 fixtures, `reward.py` reproduit exactement le FOM calculé
  en appel direct.

### 2. `observation.py` — tenseur d'état

PCB + contraintes LLM → tenseur : positions, tailles/courtyards, nets,
groupes fonctionnels, contour de carte, composants ancrés.

- Validation : shape/dtype fixes et déterministes pour une fixture donnée ;
  deux appels sur le même PCB donnent le même tenseur.

### 3. `env.py` — Gymnasium PlacementEnv

`reset()` / `step()`. Une action déplace un seul composant non ancré de
`dx_mm, dy_mm`. Pénalité forte sur toute collision ERROR.

- Validation : tests d'invariants — les ancres (`J*`, `P*`) ne bougent jamais,
  les déplacements restent dans le contour de carte.

### 4. Smoke run 100 k pas (go/no-go de coût)

Entraîner PPO/MLP sur 100 k pas. Mesurer le débit réel (pas/s) et mettre à
jour la section « Coûts estimés » de [../README.md](../README.md) avec les
valeurs mesurées.

- Validation : débit mesuré compatible avec le budget 2–8 h GPU annoncé ;
  sinon, réviser le chiffrage avant toute suite.

### 5. Entraînement 1–5 M pas

Run complet sur les fixtures. Modèle versionné avec le commit `kicad-tools`
et la version KiCad.

- Validation : courbe de reward convergente ; checkpoint sauvegardé.

### 6. `candidate.py` + `policy.py` — inférence

`policy.py` charge le modèle en lecture seule ; `candidate.py` applique le
candidat via `pcbnew` avec snapshot/revert.

- Validation : inférence < 1 s par candidat ; le revert restaure le snapshot
  à l'identique.

### 7. Intégration `tools/placement.py::auto_place` (feature flag)

Le candidat RL remplace progressivement le micro-raffinement CMA-ES, sans
supprimer le chemin actuel. Fallback placement hybride si RL indisponible.

- Validation : pipeline inchangé quand le flag est off.

### 8. Mesure du critère de vie ou de mort

Comparer le FOM du candidat RL vs CMA-ES sur ≥ 10 fixtures représentatives.

- **Go Phase 6a** : RL bat CMA-ES de > 5 % de FOM.
- **Abandon** : sinon — le placement hybride reste le chemin unique, le code
  RL est retiré ou archivé. Un échec documenté est un résultat valide.

## Rappel des invariants

Un candidat n'est jamais livré sans les quality gates réels. La Phase 6b
(encodeur GNN) ne démarre qu'après un go mesuré à l'étape 8.

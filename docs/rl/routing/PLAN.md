# PLAN — RL routing (routeur direct)

Plan d'implémentation étape par étape. La spec (observation, reward, hors
scope v1, critères de passage) reste dans [README.md](README.md) ; ce fichier
décrit l'ordre des travaux.

## Pipeline

```text
PCB placé (fixture ou production)
  → Contrôleur PPO : net actif, paire de pads, couche de départ
  → Routeur local PPO : pas de grille (8 directions + switch_layer + place_via)
      → validateur rapide en mémoire (clearance, keepouts, contour)
  → finish_net / fin d'épisode
  → exporter.py : segments/vias → .kicad_pcb temporaire
  → pré-filtre : DRC natif kicad-tools (27 règles JLCPCB)
  → juge final : kicad-cli pcb drc --format json
  → candidat accepté seulement si 0 violation + 0 unconnected item
  → sinon : fallback kct route (+ placement-feedback actuel)
```

Le RL produit des candidats, jamais un résultat livré sans gates. `kct route`
reste la baseline et le fallback derrière un feature flag.

## Étapes

### 1. `board_grid.py` — grille 2 couches

Construire la grille depuis le PCB placé du LED
(`services/kicad/examples/led-blinker-full-pipeline/`), pas fixé à 0,1 mm.
Rasteriser les 8 canaux d'observation (pads source/cible, cuivre du net,
cuivre des autres nets, courtyards/keepouts, Edge.Cuts, congestion, curseur,
distance cible).

- Validation : la rasterisation correspond au `.kicad_pcb` (test sur la
  fixture immuable).

### 2. `actions.py` — actions + validateur rapide

8 déplacements (N/S/E/W + diagonales 45°), `switch_layer`, `place_via`,
`finish_net`. Le validateur rapide confirme largeur, clearance, couche,
contour avant toute écriture de cuivre.

- Validation : une action invalide n'écrit aucun cuivre et reçoit sa pénalité
  (tests unitaires).

### 3. `reward.py` + `env.py` — Gymnasium

Reward selon le barème du README (+1000 cible atteinte, −2/pas, −20/via,
−500 collision, −1000 abandon). `reset()` / `step()` surrogate.

- Validation : débit surrogate mesuré ≥ l'hypothèse 10–50 µs/pas (sinon
  réviser les coûts).

### 4. `exporter.py` + `validate.py` — sortie et juges

Exporter les segments gagnants vers un `.kicad_pcb` temporaire ; chaîner le
pré-filtre DRC kicad-tools puis `kicad-cli pcb drc --format json`.

- Validation : roundtrip export → DRC sur la fixture ; la cadence et le
  plafond d'évaluations réelles sont consignés dans `summary.json`.

### 5. Smoke run 100 k pas (go/no-go de coût)

Mesurer le débit réel du surrogate et la durée réelle du DRC kicad-cli sur le
LED. Mettre à jour « Coûts estimés » de [../README.md](../README.md) avec les
valeurs mesurées.

- Validation : compatible avec le budget 12–48 h GPU annoncé ; sinon réviser
  avant toute suite.

### 6. Entraînement LED — curriculum

1. Un épisode par net (VCC, LED_ANODE, GND), sans via.
2. Les trois nets dans un ordre choisi par le contrôleur.
3. Artefacts dans `output/rl-routing/` : `episode_metrics.jsonl`,
   `candidate.kicad_pcb`, `kicad_drc.json`, `summary.json`.

- Validation : `kct route` lancé comme baseline de comparaison sur le même
  PCB placé.

### 7. Gate de passage — quantifiée

10 épisodes consécutifs réussis × 3 seeds (30/30) avec :

```text
routing_complete = true
unrouted_count = 0
KiCad 10 violations = 0
KiCad 10 unconnected_items = 0
```

- **Passage** : gate atteinte → étape 8.
- **Plafond** : PPO plafonne → essayer RecurrentPPO (LSTM, sb3-contrib) une
  fois. Toujours plafonné → abandon documenté, ou réplication DreamerV3+FR
  (Chiang et al., 2026) si les conditions de réexamen sont remplies.

### 8. Générateur procédural de boards

Seulement après la gate LED : boards aléatoires 2–10 composants, densités
variées, validés par `kicad-cli pcb drc` avant d'entrer au corpus.

- Validation : chaque board généré passe le DRC officiel avant usage.

## Rappel des invariants

Le reward n'est pas une preuve de succès ; seul le DRC officiel compte. Hors
scope v1 : paires différentielles, length matching, RF — ces nets restent sur
`kct route` ou en manuel.

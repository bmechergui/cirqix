# RL placement — candidat protégé par les gates actuelles

> Plan d'implémentation étape par étape : [PLAN.md](PLAN.md).

## But

RL_PCB optimise les positions X/Y des footprints non ancrés. Il ne décide ni
des règles DRC, ni des contraintes mécaniques, ni des pistes.

Le LLM fournit une stratégie de haut niveau ; la politique RL optimise la
géométrie ; `pcbnew` écrit le candidat ; les outils KiCad valident le résultat.

```text
LLM strategy
→ Architecte kicad-tools (hybrid + clusters)
→ Inspecteur initial
→ candidat RL placement
→ Inspecteur final
→ sélection ou revert
```

## Entrée de stratégie LLM

Le LLM ne donne pas de coordonnées finales. Il produit des contraintes
structurées, par exemple :

```json
{
  "groups": [["U1", "C1", "C2"], ["R1", "D1"]],
  "anchors": ["J1"],
  "sensitive_nets": ["USB_D+", "USB_D-"],
  "preferred_side": {"U1": "F.Cu"}
}
```

Les connecteurs `J*` et `P*` restent ancrés, comme dans le pipeline actuel.

## État, action et reward

L'observation contient les positions, tailles/courtyards, nets, groupes
fonctionnels, contour de carte et composants ancrés. Une action déplace un seul
composant non ancré de `dx_mm`, `dy_mm`.

La récompense réutilise le FOM multi-objectif de `kicad-tools` au lieu de
réinventer un score : compacité, wirelength, qualité des groupes, collisions
et hors-carte. Toute collision ERROR reçoit une pénalité forte.

## Point d'intégration proposé

Le candidat RL remplace progressivement le micro-raffinement CMA-ES dans
`tools/placement.py::auto_place`, sans supprimer le chemin actuel :

```text
snapshot Architecte + Inspecteur
→ RL candidate
→ PlacementAnalyzer + PlacementFixer
→ ERROR restant ou dérive > 20 mm : restore snapshot
→ sinon : comparer le FOM au candidat CMA-ES et conserver le meilleur propre
```

Le fallback est déjà défini : le placement hybride actuel est conservé si RL
est indisponible, échoue ou dégrade le PCB.

## Implémentation Phase 6a

```text
services/kicad/tools/rl/placement/
├── env.py          # Gymnasium PlacementEnv
├── observation.py  # PCB + contraintes → tenseur
├── reward.py       # adaptateur compute_fom()
├── policy.py       # PPO/MLP chargé en lecture seule
└── candidate.py    # applique un candidat via pcbnew
```

Le modèle est entraîné hors requête HTTP. En production, le service charge un
modèle versionné et exécute seulement l'inférence avec un budget borné.

## Critère d'abandon Phase 6a

La Phase 6a est abandonnée si le candidat RL ne bat pas le FOM CMA-ES de plus
de 5 % sur au moins 10 fixtures représentatives après l'expérience initiale,
ou si le coût d'inférence dépasse le budget par requête. Le placement hybride
actuel reste alors le chemin unique et le code RL est retiré ou archivé.

## Passage à la Phase 6b

Un GNN/Transformer ne vient qu'après des résultats stables avec PPO/MLP. Il
encode mieux le graphe composants/nets, mais ajoute PyTorch Geometric et un
coût d'inférence supérieur.

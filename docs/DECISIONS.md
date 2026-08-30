# Journal des décisions produit — Cirqix

> Créé le 2026-08-30 après constat que des décisions produit avaient été prises
> et implémentées sans validation de l'utilisateur (voir CLAUDE.md §« Autonomie bornée »).
>
> Règles :
> - Toute décision produit (stratégie placement/routage, seuil chiffré, limite levée,
>   gate de sécurité, droits/facturation) DOIT figurer ici AVANT implémentation.
> - Statut : `en attente` → `validée` UNIQUEMENT sur confirmation explicite de
>   l'utilisateur dans la conversation. Jamais auto-validée par Claude.
> - `annulée` : décision inversée avant ou après livraison (garder la trace + la cause).

---

## En attente de validation

### D-2026-08-29-a — Snap bypass : levée de la limite « adjacence 13-28 mm »
- **Ce qui a été décidé sans validation :** la limite acceptée le 2026-06-18
  (« clusters à 13-28 mm du MCU, routable, adjacence serrée → Phase 6 RL_PCB ») a été
  levée via `tools/placement_bypass.py::snap_cluster_members` (étape ⑤ du placement).
- **Mesure l'appuyant :** 8 règles violées sur 9 avant, 0 après ; écart libre moyen
  7,2 → 4,7 mm (`examples/stm32-validation/output/2_placement`).
- **Ce que l'utilisateur doit arbitrer :** garder le snap bypass (et ratifier la levée),
  ou le retirer et restaurer la décision 2026-06-18.
- **Code concerné :** `services/kicad/tools/placement_bypass.py`, appel dans
  `tools/placement.py::auto_place`, gardes `tests/test_placement_bypass_snap.py`,
  `tests/test_snap_apres_geometre.py`.

### D-2026-08-21-a — kicad-tools devant Freerouting dans la cascade
- **Ce qui a été décidé sans validation :** « Décision produit du 2026-08-21 » —
  kicad-tools reste le Niveau 1 car seul chemin d'escalade de couches (plans Pro 4/8),
  malgré 58 erreurs de fabricabilité et ~10 min contre 4-5 s / 0 connexion manquante
  pour Freerouting.
- **Ce que l'utilisateur doit arbitrer :** confirmer l'ordre, ou router Freerouting
  d'abord sur les cartes 2 couches et n'appeler kicad-tools qu'à l'escalade.

### D-2026-08-29-b — Seuils chiffrés du routage
- `_SEUIL_REDRAW_PCT = 80` (ne pas re-tirer un palier hors d'atteinte)
- `_CAPACITE_ECHAPPEMENT = 3.0` (plancher de couches déduit du board)
- `_TIRAGES_ROUTAGE_PAR_PALIER = 3`
- Calibrés sur les 7 boards du banc, mais les VALEURS sont des choix produit
  (coût de fabrication vs taux de réussite).

### D-2026-08-11-a — `canView3D` appliqué côté client seulement
- Documenté comme « assumé » sans trace d'arbitrage utilisateur. Différenciateur
  produit : à ratifier ou rendre exécutoire côté serveur (export STEP/GLB).

### D-2026-08-11-b — Mode démo simulation en opt-in (`CIRQIX_SIMULATION_DEMO=1`)
- Choix d'UX/produit : aucune donnée de secours sur erreur, démo locale uniquement.

---

## Validées par l'utilisateur

### D-2026-08-29-v1 — Séquence intérieure d'un palier de routage
Plan de masse coulé ET rempli avant routage (mesuré : 68-71 % → 94 % sur Nucleo),
vias d'échappement réservés, signaux routés, vias replacés, plans re-coulés,
couture répétée. *« demandée par l'utilisateur »* — CLAUDE.md.

### D-2026-08-29-v2 — Escalade des couches en gardant toujours le meilleur
Tirages multiples par palier (Freerouting stochastique), classement
(pourcentage, erreurs DRC), jamais le dernier. *« demandée par l'utilisateur »*.

---

## Annulées (trace conservée)

### D-2026-08-28-x — Budget GA divisé par 3 (commit 2744899)
Réduire `generations/population/iterations` du GA pour la vitesse. **Reverté**
au commit c312c07 : le budget réduit livrait une carte NON fabricable
(filtre anti-aberration en contrepartie insuffisant). État final = budget d'origine.

### D-2026-06-18-a — Limite « 13-28 mm » ACCEPTÉE
Limitation de `detect_functional_clusters` acceptée faute de levier. **Levée sans
validation** le 2026-08-29 → voir D-2026-08-29-a ci-dessus (à ratifier ou non).

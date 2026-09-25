---
name: cirqix-quality-gate
version: 1.0.0
description: Grille de validation obligatoire avant chaque transition de pipeline PCB. Bloque la progression si les critères de qualité ne sont pas atteints. Invoquer après chaque étape agentique.
---

## Quand invoquer

**OBLIGATOIRE** après chaque étape du pipeline avant de passer à la suivante :
- Après `call_agent_schema` → avant ERC
- Après `call_agent_erc` → avant Placement
- Après `call_agent_placement` → avant Routing
- Après `call_agent_routing` → avant DRC
- Après `call_agent_drc` → avant Export

---

## Grille de qualité par étape

### ✅ SCHEMA → ERC

**Critères obligatoires :**
- [ ] Tous les composants ont ≥ 1 connexion dans `connections[]`
- [ ] Tous les nets ont ≥ 2 pins (pas de net flottant)
- [ ] Les noms de nets sont explicites (pas de "NET1", "NET2" — utiliser "VCC_3V3", "I2C_SDA", etc.)
- [ ] GND existe comme net global
- [ ] Pas de composant dupliqué (même `ref`)
- [ ] Footprints assignés à chaque composant (`footprint` non vide)

**Blocage si :**
- Un composant n'a aucune connexion → l'ajouter ou le supprimer
- Un net a 1 seule pin → net ouvert = erreur électrique

**NEVER** progresser vers ERC si le schéma a des composants non connectés.

---

### ✅ ERC → PLACEMENT

**Critères obligatoires :**
- [ ] ERC d'autorité exécuté (`kicad-cli sch erc`) ; s'il est `skipped`, verdict de `runErcFallback()` (`packages/agents/src/engines/erc-fallback.ts`). Un `skipped` n'est jamais un succès.
- [ ] Toute violation restante est corrigée ou documentée explicitement
- [ ] Aucune violation `pin_not_connected` ou `wire_not_connected` non résolue
- [ ] Footprints au format `Library:Footprint` (ex : `Resistor_SMD:R_0402_1005Metric`)

**Blocage si :** aucun contrôle ERC n'a réellement tourné, en développement comme en production.

---

### ✅ PLACEMENT → ROUTING

**Critères obligatoires :**
- [ ] DRC kicad-cli du board PLACÉ, sans piste : 0 `courtyards_overlap`, 0 erreur. Le board doit se charger : un rapport vide n'est pas un zéro.
- [ ] Composants dans `Edge.Cuts`, connecteurs collés au bord le plus proche
- [ ] Membres de cluster à portée de leur ancre (`FunctionalCluster.max_distance_mm`)

---

### ✅ ROUTING → DRC

**Critères obligatoires :**
- [ ] `routed_percent` mesuré = 100 et 0 connexion manquante au DRC
- [ ] Plan GND coulé et rempli sur les faces extérieures, îlots cousus
- [ ] Largeurs et dégagements : profil fabricant (`services/kicad/tools/drc.py`), jamais des constantes recopiées ici

---

### ✅ DRC → EXPORT

**Critères obligatoires :**
- [ ] Aucune violation bloquante au sens de `est_bloquante` (`services/kicad/tools/drc.py`) : toute `error`, plus `hole_to_hole` et `holes_co_located` même en avertissement
- [ ] Tout avertissement restant est listé et justifié dans le rapport, jamais passé sous silence
- [ ] 0 connexion manquante
- [ ] Contour de carte fermé (Edge.Cuts)
- [ ] Carte ≤ 200×200 mm (MVP)

**NEVER** exporter vers JLCPCB avec une violation bloquante : `DRC_CLEAN` ouvre le gate de commande.

---

## Format de rapport qualité

Quand une étape échoue, afficher :

```
❌ QUALITÉ [ÉTAPE] — BLOQUÉ

Critères non satisfaits :
  • [critère 1] : [valeur actuelle] → [valeur attendue]
  • [critère 2] : ...

Action requise : [instruction précise de correction]
Ne pas progresser tant que ces critères ne sont pas atteints.
```

Quand une étape passe :

```
✅ QUALITÉ [ÉTAPE] — OK
  • [N] composants, [M] nets — tous connectés
  • Footprints : [N] résolus / [N] total
  • Prêt pour [ÉTAPE SUIVANTE]
```

---

## Critères de qualité visuelle (viewer)

### Schéma (KiCanvas native)
- Symboles groupés par fonction (gauche → droite : connecteurs, power, core, passives)
- Labels de nets visibles sans zoom (font ≥ 1.524mm)
- Stubs de fils ≥ 5mm (lisibles dans KiCanvas)
- Référence et valeur en bold lisible

### PCB (KiCanvas native)
- Composants visibles avec contours (fab layer présent)
- Traces visibles (width ≥ 0.25mm)
- GND plane couvre ≥ 60% de la surface
- Board outline clairement visible

### PCB (Spec canvas)
- Tous les composants avec label REF + VALUE lisibles
- Traces affichées (showRouting = true après routing)
- Zoom auto-fit centré sur les composants

---

## Règle d'or

> **Un PCB ne doit jamais arriver à l'étape suivante avec des composants flottants, des nets ouverts, des DRC violations, ou des stubs de connexion invisibles.**
>
> Si l'étape précédente ne satisfait pas les critères, **corriger d'abord** et **re-valider** avant de progresser.

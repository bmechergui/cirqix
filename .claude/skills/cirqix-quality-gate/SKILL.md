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
- [ ] ERC = 0 violations (ou violations documentées comme acceptables)
- [ ] Si ERC skipped : afficher avertissement explicite et demander confirmation utilisateur
- [ ] Tous les footprints sont au format `Library:Footprint` (ex: `Resistor_SMD:R_0402_1005Metric`)

**Blocage si :**
- ERC a des violations de type `pin_not_connected` non résolues
- ERC a des violations de type `wire_not_connected`
- ERC skipped en production (accepté seulement en développement local avec avertissement)

**NEVER** skip ERC sans afficher `⚠️ ERC non validé en dev — obligatoire en production`.

---

### ✅ PLACEMENT → ROUTING

**Critères obligatoires :**
- [ ] Tous les composants placés à l'intérieur des limites du PCB
- [ ] Espacement minimum entre composants : 1.5mm (passives), 2mm (ICs)
- [ ] Composants groupés logiquement :
  - Connecteurs : bords gauche/droit
  - Découplage : à côté de leur IC (distance < 10mm)
  - ICs : zone centrale
- [ ] Aucun composant à (0,0)
- [ ] Orientation des composants cohérente (SMD face Up)

**Blocage si :**
- Des composants se chevauchent (overlap > 50%)
- Un composant est hors de la zone utile du PCB

---

### ✅ ROUTING → DRC

**Critères obligatoires :**
- [ ] 0 nets non routés (ratsnest = 0)
- [ ] Trace width : ≥ 0.25mm pour signaux, ≥ 0.3mm pour power
- [ ] Clearance minimum : ≥ 0.15mm
- [ ] GND plane ajouté sur B.Cu (ground fill)
- [ ] Vias de stitching pour GND plane si 2+ layers

**Blocage si :**
- Des nets sont non routés
- Width < 0.15mm (non fabricable)

---

### ✅ DRC → EXPORT

**Critères obligatoires :**
- [ ] DRC = 0 violations
- [ ] Aucune violation de type `clearance`, `annular_ring`, `drill`
- [ ] Board outline fermée (Edge.Cuts)
- [ ] Taille board raisonnable (≤ 200×200mm pour MVP)

**Blocage si :**
- DRC > 0 violations → corriger avant export
- Board outline ouverte ou manquante

**NEVER** exporter vers JLCPCB avec des violations DRC actives.

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

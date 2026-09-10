# Méthodologie de routage PCB — référence

> Synthèse fournie par l'utilisateur le 2026-09-10, à partir des pratiques
> recommandées par Rick Hartley, Eric Bogatin, Philip Salmony (Phil's Lab),
> Robert Feranec (FEDEVEL), Zachariah Peterson, et des normes IPC.
>
> **Délégation :** sur la méthode de routage, l'assistant valide seul en
> s'appuyant sur ce document (`docs/DECISIONS.md`, entrée du 2026-09-10). Les
> seuils chiffrés et les choix commerciaux restent à l'utilisateur.
>
> La colonne « chez nous » est tenue à jour : elle dit ce que Cirqix fait
> réellement, mesuré, pas ce qu'on aimerait qu'il fasse.

---

## Principe

Le succès du routage dépend à **90 %** de l'empilage (stackup) et du placement
initial. Le routage n'est que l'aboutissement.

## 1. Avant le routage

| Étape | Recommandation | Chez nous |
|---|---|---|
| Stackup et impédance | Nombre de couches, diélectriques, lignes 50 Ω / paires 90-100 Ω | 2 couches par défaut ; escalade 2→4→6→8 sur preuve d'échec (`_layer_ladder`). Pas d'impédance contrôlée. |
| Règles DRC et net classes | Clearances, largeurs selon IPC-2221, diaphonie 3W/5W | Règles JLCPCB via `kct` + `kicad-cli pcb drc`. Pas de net classes. |
| Classification de la netlist | Horloges, RF, paires diff., DDR, alim. fort courant, GPIO | Détection native `is_power_net`, clusters POWER/TIMING/DRIVER/INTERFACE. Pas de classes de priorité. |
| Placement fonctionnel et découplage | Blocs numérique / analogique / puissance séparés ; découplage au plus près des broches d'alim. | Clusters fonctionnels + snap (POWER 3 mm) + paires en série (5 mm) + grille 0,5 mm. Pas de séparation par domaine de bruit. |

## 2. Ordre canonique de routage

```
1. Fanout / échappement BGA et fine-pitch
2. Signaux critiques et haute vitesse
3. Nets d'alimentation
4. Signaux secondaires / GPIO
5. Vias de couture et plans de masse
```

| Étape | Recommandation | Chez nous |
|---|---|---|
| Fanout | En premier, dog-bones ou via-in-pad | Halo d'escape 5 mm au placement ; vias d'échappement réservés dans le DSN. |
| Signaux critiques | Trajets directs, sans vias superflus, plan de référence continu | Pas de priorisation — Freerouting route tout d'un bloc. |
| Masse | Multicouche : via court vers le plan, pas de pistes | **2 couches : GND confié au plan coulé**, dogbones + couture. Essayé en pistes le 2026-09-10, réfuté par A/B sur le même board (92 % contre 100 %, D-2026-09-10-c). |
| Alimentation | Après les critiques, en zones ou pistes larges | Routée avec les signaux. |
| GPIO | En dernier | Pas de priorisation. |

## 3. Cartes 2 couches — la masse sans plan dédié

| Recommandation | Chez nous |
|---|---|
| **Grille de masse** : pistes H sur Top, V sur Bottom, pistes GND entrelacées reliées par vias | GND en pistes : réfuté sur 2 couches (D-2026-09-10-c) ; réglage `gnd_route` pour un A/B sur 4-6 couches. H/V par couche : **à faire** (préférence de direction Freerouting, validé d'avance). |
| **Ground pour** : remplir Bottom en GND, **ne pas le découper** par de longues pistes transversales | Plan coulé avant routage ✓. La découpe par les signaux n'est pas contrôlée ; les dogbones et la couture la compensent, et l'A/B du 2026-09-10 montre que confier GND au plan reste ce qui route à 100 %. |
| **Discontinuités du chemin de retour** : vias de couture aux transitions | Couture d'îlots répétée (`_recoudre_les_ilots`), devenue un complément et non un rattrapage. |

⚠️ Mesure du 2026-08-28, gardée pour mémoire : router GND en pistes rendait
`arduino-uno` complète (100 % / 0 manquante) là où le plan seul donnait 93 % / 1.
La décision de garder le plan en charge a produit douze fonctions de rattrapage.
Renversée le matin du 2026-09-10, puis **rétablie le jour même** par l'A/B sur le
même board (`carte-05` : pistes 92 %/92 %, plan 100 %/100 %). Le « plantage
natif sur les cartes denses » attribué au plan était en réalité le superviseur
uvicorn qui abattait un worker occupé à relire 564 Mo de journal — voir
`docs/DECISIONS.md`.

## 4. Cartes multicouches

| Stackup 4 couches | Usage |
|---|---|
| SIG1 – GND – PWR – SIG2 | Standard historique |
| **GND – SIG1/PWR – SIG2/PWR – GND** | Recommandé par Hartley : blindage naturel contre les EMI |
| SIG1 – GND – GND – SIG2 | Très haute vitesse ; alimentation en zones sur les couches externes |

Règles : plan de référence **continu** sous toute piste rapide ; routage
**orthogonal** H/V entre couches adjacentes ; **symétrie** du stackup contre le
vrillage à la refusion.

**Chez nous :** `_expand_stackup` ajoute des couches internes ; aucun choix de
stackup, aucune symétrie contrôlée. À traiter quand une carte exigera 4 couches
réellement — aucune du banc ne l'exige aujourd'hui (`carte-11`, 32 signaux
croisés, tient sur 2).

## 5. Placement double face

| Recommandation | Chez nous |
|---|---|
| Plan de référence continu adjacent à chaque face | — |
| Via-in-pad (IPC-4761 / VIPPO) rempli et métallisé pour BGA denses | — |
| Refusion en deux passages ; composants lourds collés en Bottom | — |

**Chez nous : rien en Bottom.** Mesuré le 2026-09-08 : 0 composant au dos sur
nos 18 cartes, contre 12 sur la référence humaine `astra_piNas`. Ce n'est pas un
défaut de placement mais une **capacité absente**.

## Comparatif

| | 2 couches | 4 couches | 6+ couches |
|---|---|---|---|
| Ordre | Grille GND / power → critiques → pour Bottom | Fanout → critiques → power → GPIO → vias GND | Fanout → stripline critiques → power pours → GPIO |
| Masse | Grille manuelle / pour à découpes minimales | ≥ 1 plan continu, idéalement 2 | Plusieurs plans GND (stripline) |
| Impédance | Difficile (pistes > 1 mm) | Bonne (diélectrique ~0,1 mm → piste 0,15-0,2 mm) | Excellente |
| CEM | Faible à modérée | Élevée (CISPR / FCC) | Très élevée (PCIe 4/5, DDR4/5, RF) |
| Coût | Très faible | Standard | Modéré à élevé |

## Désaccords entre experts

**Masses séparées (AGND / DGND).** Ancienne école (notes TI / ADI) : couper le
plan sous l'ADC, relier en un point. Experts CEM modernes (Hartley, Bogatin,
Ott) : **ne jamais couper le plan** — une coupe franchie par une piste devient
une antenne fente. Séparation *spatiale* des composants, plan unique.

**Plan d'alimentation dédié.** Camp « plan VCC » : une couche entière. Camp
Hartley : un plan VCC loin du GND n'apporte presque rien ; préférer
SIG–GND–GND–SIG et router VCC en pistes larges ou zones.

## Références

- Rick Hartley — *How to Achieve Proper Grounding* (Altium Academy) : 20:00
  physique des champs et impédance du retour ; 45:15 mythe AGND/DGND.
- Eric Bogatin — *Signal and Power Integrity – Simplified* (Prentice Hall).
- Philip Salmony — *High-Speed PCB Design Tips*, Phil's Lab #25 : 02:40 plans
  de référence ; 04:42 impédance contrôlée.
- Robert Feranec (FEDEVEL) — interviews et tests sur les courants de retour.
- IPC-2221 (pistes / courants), IPC-7351 (empreintes), IPC-4761 (vias / VIPPO).

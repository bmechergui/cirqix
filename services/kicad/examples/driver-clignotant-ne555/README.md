# driver-clignotant-ne555 — le driver LLM est Claude Code

**Question posée :** la chaîne réelle (file BullMQ → worker → service KiCad)
livre-t-elle un PCB complet quand le schéma est écrit par Claude Code lui-même,
sans aucun appel à l'API Anthropic ?

**Réponse (2026-09-13) : oui.** Run `6d3af3b3`, projet `645802b1`, provenance
`driver`, 156 s de bout en bout, 0 crédit.

## Ce que le driver a écrit

`input/schema.json` : un clignotant NE555 en astable alimenté en 5 V — R1 10k,
R2 100k, C3 4,7 µF (f = 1,44 / ((R1 + 2·R2)·C3) ≈ 1,46 Hz), C1 100 nF de
découplage, C4 10 nF sur CTRL, LED rouge D1 en série avec R3 330 Ω (≈ 9 mA).
Neuf composants, sept nets, carte de 45 × 30 mm.

## Ce que la chaîne a produit

| étape | temps cumulé | résultat |
|---|---|---|
| SCHEMA | 4 s | `.kicad_sch` écrit depuis le JSON |
| ERC | 42 s | `ERC_CLEAN` |
| PLACEMENT | ~90 s | `PLACEMENT_DONE` |
| ROUTING | ~120 s | 100 % routé, 2 couches, 20 vias, 104 mm de piste |
| DRC | | `drc_clean: true` (kicad-cli officiel) |
| EXPORT | 156 s | 20 fichiers Gerber + perçage + `pos.csv` + BOM, `PCB_LIVRÉ` |

Vérifié en local sur `expected/final.kicad_pcb` avec `kicad-cli pcb drc` :
**0 erreur, 0 connexion manquante**, 3 `silk_overlap` (cosmétique).

## Ce que ce run ne prouve pas

- Le board n'est **pas commandable** : `POST /api/jlcpcb/order` exige la
  provenance `orchestrator`, et c'est voulu — ce schéma n'a pas traversé la
  boucle autonome que le produit vend.
- La soumission depuis le dashboard avec un compte connecté (RLS + Realtime
  côté navigateur) n'a pas été jouée ici : le run a été enfilé par
  `services/worker/scripts/enfiler-driver.mjs`, qui reproduit le chemin de la
  route sans l'authentification.

## Fichiers

- `input/schema.json` — le schéma écrit par le driver
- `expected/schema.kicad_sch` — le schéma KiCad produit
- `expected/final.kicad_pcb` — le board routé livré
- `expected/rendu-3d.png` — rendu `kicad-cli pcb render`
- `expected/mesures.json` — mesures du run

# Exemple de référence — Pipeline COMPLET, description → Gerbers

> **1 dossier = 1 cas = 1 question.** Ce cas : « la chaîne 8 agents tient-elle de
> bout en bout contre le service réel, avec le backend C++ disponible ? »
> Pour le cas de STRESS du routage (fine-pitch LQFP-48, plafond DFM), voir
> `../stm32-validation/`.

Exécuté le **2026-07-27** contre le conteneur `cirqix-kicad` (kicad-cli 10.0.4,
backend natif C++ 1.0.0 disponible). Le rôle du LLM est tenu par le **driver**
(cf. « Driver LLM » plus bas) : aucune `ANTHROPIC_API_KEY` n'est requise.

## Le board

LED blinker 5 V : NE555 astable ~1 Hz pilotant une LED.
8 composants (1 DIP-8 + 7 SMD 0805 + header 2 pts), 6 nets, board 60×45 mm.

Volontairement **simple** — DIP/0805, pas de fine-pitch — pour que la question
posée soit « le pipeline tient-il ? » et non « le routeur sait-il faire du
0.5 mm ? ». Le second cas est déjà couvert par `stm32-validation`.

## Reproduire

```bash
# Conteneur (depuis services/kicad/) — le token doit faire ≥32 caractères,
# sinon le service échoue fermé en 503 sur TOUTES les routes sauf /health.
KICAD_SERVICE_TOKEN=$(python -c "import secrets;print(secrets.token_hex(24))") \
  docker compose up -d kicad

export KICAD_SERVICE_URL=http://127.0.0.1:8766
export KICAD_SERVICE_TOKEN=<le même token>
export PYTHONUTF8=1                      # obligatoire sous Windows
python run_pipeline.py                   # artefacts dans output/ (gitignoré)
```

## Driver LLM

Là où la prod appelle un modèle, le driver fournit la sortie :

| Étape prod | Modèle | Ici |
|---|---|---|
| `call_agent_schema` | Haiku 4.5 | `input/schema.json`, écrit à la main |
| `call_agent_footprint` | Haiku (cascade) | footprints déjà résolus dans le JSON |
| `call_agent_reason` | Haiku | non déclenché (routage à 100 %) |

Même dispositif que `../stm32-validation/` (`decisions.json`) : c'est ainsi qu'a
été trouvé le bug `_refresh_agent` du reasoner en 2026-06-03.

## Résultat — objectif atteint (2026-07-27)

`expected/led_blinker_final.kicad_pcb` : **100 % routé, 0 violation DRC,
0 net non connecté**, 20 fichiers de fabrication. Vérifié indépendamment du
service, par `kicad-cli pcb drc --severity-all --refill-zones` relancé sur le
fichier (hash confirmé identique à l'artefact du run).

| Étape | Résultat | Temps |
|---|---|---|
| ① Schéma | `.kicad_sch` 39 528 o | 0.9 s |
| ② ERC | clean, 0 violation — kicad-cli officiel | 0.9 s |
| ④ gen_pcb | `.kicad_pcb` 21 547 o, niveau 1 kicad-tools | 0.3 s |
| ⑤ Placement | 8/8 placés | 34 s |
| ⑥ Routage | **100 %**, 2 couches | 40 s |
| ⑥b Reasoner | non déclenché — conforme au seuil `< 100` | — |
| ⑦ DRC | **0 violation, drc_clean=True** | 1.5 s |
| ⑧ Export | **20 fichiers** (Gerbers + drill + `pos.csv`), devis $15 | 6.4 s |

### Campagne de mesure — 3 runs par configuration

Le placement GA est stochastique et sans seed : toute conclusion demande
plusieurs runs. Violations DRC totales (le service additionne violations et
`unconnected_items`) :

| Configuration | run 1 | run 2 | run 3 |
|---|---|---|---|
| Départ | 8 | 67 | 58 |
| \+ VCC routé en pistes | 10 | 17 | 6 |
| \+ marge courtyard 0.5 mm | **0** ✅ | 12 | **4** ✅ (warnings silk) |

**2 runs sur 3 sont DRC-clean.** Le run restant est un mauvais tirage GA. Le
levier existe déjà côté orchestrateur (`MAX_PLACEMENT_ATTEMPTS`, re-tirage
déterministe) mais n'est câblé que sur `routed_percent < 100`, pas sur le DRC —
c'est le prochain chantier pour rendre le résultat systématique.

## Deux bugs bloquants trouvés et corrigés pendant cette validation

### 1. VCC classé « power » → jamais routé, jamais coulé

`kct route` classe les nets power par leur nom
(`router.net_class` : `^(VCC|VDD|VBUS|VIN|VOUT|…)`) et les **exclut du
pathfinding**, en supposant qu'ils seront coulés en plan. Or le flux Cirqix ne
coule que GND (`_ensure_gnd_both_planes`). Un rail nommé `VCC` ressortait donc
**sans un seul segment ni la moindre zone** — non connecté — pendant que
`kct route` annonçait 100 % (il ne compte pas les nets power). kicad-cli, lui,
voyait les 4 pads VCC orphelins : DRC jamais clean.

Le contournement existait déjà (`_VCC_RENAME` : renommer le rail en nom
non-power le temps du routage) mais sa table était **codée en dur sur
`+5V`/`+3.3V`**. `_power_rename_map` la dérive désormais du board.

Piège rencontré : `explain.mistakes.is_power_net` n'est **pas** le bon oracle —
il travaille par sous-chaîne et diverge dans les deux sens (rate `VBUS`, que le
routeur exclut ; classe `P5V0` comme power, alors que le routeur le voit comme
un signal — c'est précisément ce qui fait marcher le renommage historique). Le
bon oracle est `router.net_class.classify_from_name`, celui qu'utilise le
routeur. Un test écrit contre le mauvais oracle passait sans rien prouver.

### 2. Valeurs de propriété numériques non quotées → board illisible par KiCad

`kicad_tools/sexp/parser.py` ne quote un atome chaîne que s'il a été *lu* depuis
un token quoté (`_originally_quoted`) ou s'il ne ressemble pas à un nombre. Ce
drapeau vaut **False pour les atomes construits programmatiquement** — donc pour
toute valeur de composant injectée depuis notre JSON. Avec `R3 = 330` :

```
(property "Value" 330          ← atome nu, S-expression invalide
```

KiCad 10.0.4 refuse alors le **fichier entier** : `kicad-cli` affiche
`Failed to load board` et `pcbnew.LoadBoard` renvoie `None`. Le parseur de
kicad-tools étant plus permissif, le board se **place et se route normalement**,
puis DRC et export échouent — sur un board pourtant routé à 100 %.

Les valeurs sans unité (330, 100, 4700, 10…) sont la norme : tout schéma
contenant une résistance ainsi notée était affecté.

**Garde livré** : `tools/pcb.py::_quote_bare_property_values`, appliqué aux deux
niveaux de `generate_pcb`. Board-agnostique, idempotent, et ne touche qu'aux
valeurs de `(property …)` — les atomes numériques légitimes (`(at …)`,
`(size …)`, `(version …)`) sont préservés. Tests :
`services/kicad/tests/test_pcb_property_quoting.py` (7 tests).
Le fix de fond appartient à `kicad_tools` (défaut d'`_originally_quoted`
inadapté à la construction programmatique) → procédure fork/rebase de
`DEPENDENCIES.md`.

### 3. Marge de courtyard sous-évaluée par l'Inspecteur

`PlacementAnalyzer` **approxime** le courtyard par « pads + marge » (0.25 mm par
défaut), alors que kicad-cli utilise la géométrie réelle `F.CrtYd`. Sur un
boîtier traversant (DIP-8), le corps déborde largement des pads : l'analyseur
annonçait « 0 conflit » là où kicad-cli rapportait un `courtyards_overlap`
**ERROR**, que l'Inspecteur ne corrigeait donc jamais. Marge portée à 0.5 mm
(`_COURTYARD_MARGIN_MM`) — c'est ce réglage qui fait passer les runs à 0.

## Bug trouvé pendant cette validation

### Valeurs de propriété numériques non quotées → board illisible par KiCad

`kicad_tools/sexp/parser.py` ne quote un atome chaîne que s'il a été *lu* depuis
un token quoté (`_originally_quoted`) ou s'il ne ressemble pas à un nombre. Ce
drapeau vaut **False pour les atomes construits programmatiquement** — donc pour
toute valeur de composant injectée depuis notre JSON. Avec `R3 = 330` :

```
(property "Value" 330          ← atome nu, S-expression invalide
```

KiCad 10.0.4 refuse alors le **fichier entier** : `kicad-cli` affiche
`Failed to load board` et `pcbnew.LoadBoard` renvoie `None`. Le parseur de
kicad-tools étant plus permissif, le board se **place et se route normalement**,
puis DRC et export échouent — sur un board pourtant routé à 100 %.

Les valeurs sans unité (330, 100, 4700, 10…) sont la norme : tout schéma
contenant une résistance ainsi notée était affecté.

**Garde livré** : `tools/pcb.py::_quote_bare_property_values`, appliqué aux deux
niveaux de `generate_pcb`. Board-agnostique, idempotent, et ne touche qu'aux
valeurs de `(property …)` — les atomes numériques légitimes (`(at …)`,
`(size …)`, `(version …)`) sont préservés. Tests :
`services/kicad/tests/test_pcb_property_quoting.py` (7 tests).
Le fix de fond appartient à `kicad_tools` (défaut d'`_originally_quoted`
inadapté à la construction programmatique) → procédure fork/rebase de
`DEPENDENCIES.md`.

## Deux autres constats

- **Token trop court = service muet.** `docker-compose.yml` impose que
  `KICAD_SERVICE_TOKEN` soit *défini* (`:?`) mais pas qu'il fasse ≥32 caractères,
  seuil exigé par `security.py`. Un token plus court fait démarrer le conteneur,
  le rend **`healthy`** (car `/health` est public) et renvoie 503 sur tout le
  reste. Le healthcheck ne peut pas le détecter.
- **CMA-ES mort sous uvicorn.** `auto_place` journalise
  `ValueError: signal only works in main thread of the main interpreter` :
  `run_optimize_placement` installe un handler de signal, impossible hors thread
  principal. Le filet de sécurité fait son travail (board pré-CMA-ES conservé),
  donc le placement aboutit — mais l'étape « Géomètre » longuement documentée
  dans `CLAUDE.md` **ne s'exécute jamais** dans le conteneur.

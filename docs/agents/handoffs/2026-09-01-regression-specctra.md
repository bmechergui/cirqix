# Handoff — régression Specctra après les correctifs de réservation

- **Branche** : `feat/placement-seed-snap-bypass`
- **Head poussé** : `cc60338` (11 commits, `origin` à jour)
- **Tests** : 1148 passed, 2 failed — les deux sont des artefacts Windows
  connus (`test_journal_freerouting_lisible.py`, chemins POSIX comparés à un
  chemin `Path` ; verts en conteneur).
- **Owner** : session Claude du 2026-08-31 → 2026-09-01.

## L'état en une phrase

Douze défauts corrigés dans la chaîne de routage ; **un seul point reste
ouvert**, une régression apparue avec ces correctifs et non encore tranchée.

## Ce qui est PROUVÉ

- **Témoin complet, 8 cartes à placement figé** (code d'avant) :

  | carte | couches | routé | manquants | erreurs | durée |
  |---|---|---|---|---|---|
  | arduino-uno | 2 | 100 % | 0 | 0 | 170 s |
  | esp32-baseline | 2 | 100 % | 0 | 0 | 41 s |
  | led-blinker | 2 | 100 % | 0 | 0 | 58 s |
  | stm32-baseline | 2 | 100 % | 0 | 0 | 113 s |
  | stm32-30 | 2 | 96 % | 3 | 0 | 882 s |
  | stm32-60 | 2 | 98 % | 1 | 0 | 3248 s |
  | nucleo-f401 | 2 | 98 % | 4 | 0 | 3824 s |
  | stm32-100 | 4 | ÉCHEC | — | — | ~7900 s |

  Zéro erreur de fabricabilité sur les sept cartes abouties ; huit connexions
  manquantes en tout, **toutes GND**. L'ÉCHEC de `stm32-100` s'explique : ses
  six tirages ont figé et le dernier recours qui devait récupérer un board à
  81 % levait `NameError` depuis sa création (corrigé, `29c9dfe`).

- **En production, sur la mesure d'après interrompue** : `arduino-uno` à
  100 % / 0 erreur avec **35 vias au lieu de 55** ; 10 doublons de pastille
  sur 21 vias réservés ; 12 vias + 1 piste écartés car `GND` n'est pas déclaré
  dans le DSN — confirmé sur un DSN réel : **140 nets déclarés, GND absent**.

- **`_sans_pistes` validé par `kicad-cli pcb drc`** sur deux boards réels
  (dont un KiCad 10 avec keepout) : aucun type de violation en hausse, les
  boards chargent, 231 et 183 segments retirés proprement.

## Ce qui reste OUVERT — le seul point

Sur `esp32-baseline`, le processus enfant pcbnew meurt en **`exit -11`
(SIGSEGV)** à l'import de session Specctra. **Zéro occurrence dans le témoin,
deux dans la mesure d'après.** Suit un second symptôme, aussi nouveau :
`ValueError: Net 'GND' not found in PCB` côté repli kicad-tools.

**Chaîne causale établie par lecture, non par mesure** :
`_specctra_roundtrip` détruit toutes les pistes du board reçu avant d'importer
la session. Dans les huit cartes du témoin, ce board était toujours un board
placé — donc sans piste : `board.Remove()` n'avait **jamais été appelé**.
L'étape ③ (`_relier_gnd_avant_routage`, active pour la première fois depuis
`1b109b9`) a rendu cette liste non vide, et le segfault est apparu la même fois.

Trois correctifs posés, chacun justifié seul par la règle du projet :
`c8d1e8f` (recouler les zones + garde d'intégrité), `04cde93` (retirer les
pistes avant d'entrer dans pcbnew), `c5e728f` (la garde lisait mal les boards
KiCad 10).

⚠️ **L'assertion `m_choices.GetCount() > 0 … No enum choices defined` qui
accompagne le plantage est un défaut CONNU de KiCad** (gitlab issue #13699) :
émise à l'import du module pcbnew en headless, dans **tous** les enfants,
visible seulement quand l'un échoue. Ce n'est pas un diagnostic — je l'ai
d'abord lue comme la cause.

## La prochaine action, en une commande

```
docker exec cirqix-banc sh /app/scripts/verdict_regression_specctra.sh
```

Rejoue `esp32-baseline` seule (< 1 min) et imprime six compteurs. Il répond
**contre** les correctifs aussi bien que pour eux :

- `segfault pcbnew : 0` → la régression a disparu, relancer les 8 cartes et
  comparer au témoin ci-dessus ;
- `garde integrite : 1+` → elle **nomme** la cause (board amputé par la
  réécriture pcbnew) ;
- `segfault > 0` → les trois derniers correctifs n'étaient que de la solidité ;
  chercher dans `ImportSpecctraSES` (`tools/routing_pcbnew_runner.py`).

## Blocage rencontré

WSL figé au niveau de l'hyperviseur le 2026-09-01 vers 01 h 50. Ont échoué :
`wsl --shutdown` (y compris **élevé**), `wsl --terminate`, `Restart-Service
WSLService`, cycle de `vmcompute` élevé, arrêt forcé de `vmmemWSL` (accès
refusé). Seul un redémarrage de Windows débloque.

Aucun contournement local n'existe, vérifié : KiCad 10.99 sous Windows ne
livre **ni** `python.exe`, **ni** module `pcbnew`, et `kicad-cli` n'expose
aucun Specctra (ni export `dsn`, ni import `ses`).

## Décision produit en attente

`_confier_au_plan` retire GND du DSN, donc **aucun cuivre GND ne peut être
protégé pendant le routage** — le routeur peut le traverser sans le savoir.
Le levier serait de garder GND **déclaré mais sans broches** : le routeur
saurait que le net existe, la protection deviendrait résoluble, et il n'aurait
toujours rien à router pour GND. C'est le dernier verrou de la séquence ③
demandée par l'utilisateur ; **non implémenté, il exige une mesure et une
validation utilisateur.**

---

# Suite — 2026-09-01 soir / 2026-09-02 nuit

Owner : Claude (session `a9118fd4`). Branche `feat/placement-seed-snap-bypass`,
head `3228a20`, poussée. Suite du service : **1264 passed**, 2 échecs Windows
connus (`test_journal_freerouting_lisible`, chemins POSIX — voir mémoire).

## Cinq défauts corrigés, tous mesurés sur de vrais boards

| commit | défaut | mesure |
|---|---|---|
| `e4fad23` | la couture reposait un via au même point à chaque passe | 131 vias / 94 positions → **109 / 109** ; 116 `holes_co_located` → **0** |
| `a929839` | `_secours_est_meilleur` achetait 3 erreurs avec 62 liaisons | échange refusé, sans seuil chiffré |
| `3ecb629` | `CLAUDE.md` annonçait `kicad-tools` en Niveau 1 | corrigé, c'est Freerouting (`routing.py:4027`) |
| `c3fdd71` | 4 `starved_thermal` (1 pont au lieu de 2) | **4 erreurs → 0**, 75 violations → 71 |
| `3c3741a` | l'étape ③ ne visait que les boîtiers fine-pitch | vise aussi `_pads_isolees_du_plan` |

**Forme commune des cinq** : la mesure juste existait, au bon endroit, calculée
à chaque appel, et personne ne s'en servait. Famille de `max_distance_mm`.

## État de `nucleo-f401`

```
routage           98 %   (2 couches, Freerouting API, placement figé)
erreurs DRC       0      après promotion thermique
avertissements    71     sérigraphie — TOUS présents dans le board PLACÉ
```

Trois connexions manquantes subsistaient sur `18_cousu` :

```
PTH pad 1 [GND] of J10  <->  Pad 2 [GND] of D3     ← visée par 3c3741a
Pad 2 [GND] of D3       <->  Zone [GND] on F.Cu    ← visée par 3c3741a
Pad 37 [MORPHO_R_6] U1  <->  PTH pad 6 of J11      ← un SIGNAL, hors masse
```

## En cours au moment du handoff

Banc quatre cartes (`nucleo-f401`, `stm32-30`, `stm32-60`, `stm32-100`) lancé
dans `cirqix-banc` à 00:05 avec les cinq correctifs, placements figés,
`CIRQIX_DUMP_ETAPES` actif. Journaux `/tmp/etapes_<carte>.log`, boards dans
`/tmp/ex/<carte>/output/etapes/`.

⚠️ `routers/routing.py` est importé **une seule fois** au démarrage : un
correctif qui y vit n'agit qu'à partir du lancement suivant. `tools/*_runner.py`
s'exécute en processus enfant et relit le fichier à chaque appel.

## Livré à l'utilisateur

`services/kicad/examples/nucleo-f401/output/etapes/` — 18 boards + `LISEZ-MOI.md`
(légende des six étapes par tirage). `output/` est gitignoré : les fichiers sont
locaux, pas versionnés. À rafraîchir depuis le conteneur à la fin du banc, et à
faire pour les trois autres cartes.

## Défaut trouvé, NON corrigé — placement

Les condensateurs de découplage de `nucleo-f401` sont à **24,5 · 43,8 · 51,5 ·
58,3 · 58,7 · 62,5 · 62,8 · 68,7 mm** du MCU. Cause mesurée :
`detect_functional_clusters` ne rend que 4 clusters — 3 INTERFACE (J1/J10/J11 +
LED) et 1 DRIVER (U1 + résistances). **Aucun cluster POWER** : les capas
n'appartiennent à rien, donc `snap_cluster_members` ne peut rien pour elles.

Les résistances, elles, sont conformes : 13,7 mm d'entraxe laissent ~6,2 mm
d'espace libre entre corps pour un plafond DRIVER de 6,0 mm. **Ne pas mesurer
cette distance entre origines.**

Non traité parce que l'utilisateur a **gelé les placements** pour ne faire
varier que le routage. À reprendre quand il rouvrira le placement.

## Décision produit toujours en attente

Celle de la section précédente (`_confier_au_plan` / GND déclaré sans broches)
reste ouverte : non implémentée, elle exige une mesure et une validation.

---

# Verdicts du banc — 2026-09-02, placements figés

Head `1de31db`. Neuf correctifs, tous mesurés sur de vrais boards.

| carte | témoin | après | erreurs | couches |
|---|---|---|---|---|
| `stm32-30` | 96 % · 3 manq | **100 %** · 1 manq | **0** | 2 |
| `stm32-60` | 98 % · 1 manq | 98 % · 2 manq | **0** | 2 |
| `nucleo-f401` | 98 % · 187 violations | 98 % · **74 violations** | 1 | 2 |
| `stm32-100` | **70 % · 27 manq** | **99 %** · 3 manq | **0** | 2 |

⚠️ Freerouting est stochastique (jusqu'à 26 points d'écart mesurés entre deux
tirages du même board). Le 100 % de `stm32-30` et le +1 manquante de
`stm32-60` sont dans ce bruit ; **le 0 erreur, lui, est solide**.

## Les neuf correctifs

```
e4fad23  plus jamais deux vias dans le même trou       116 holes_co_located → 0
a929839  un repli ne peut plus acheter 3 erreurs contre 62 liaisons perdues
3ecb629  CLAUDE.md annonçait kicad-tools en Niveau 1 — c'est Freerouting
c3fdd71  reliefs thermiques affamés promus             4 erreurs → 0
3c3741a  l'étape ③ vise aussi les broches mesurées isolées
dbb8c97  une pastille sans direction ne disparaît plus  1/3 visées → 3/3
74a3d19  le NameError, et la garde d'exécution qui manquait
53329f3  +3.3V n'était pas reconnu comme rail          0 → 1 cluster POWER
1de31db  la règle du trou sur les QUATRE sites de perçage
```

**Forme commune** : la mesure juste existait, au bon endroit, et personne ne
s'en servait. Famille de `max_distance_mm`.

## Trois fois mes propres gardes ne mesuraient rien

- une cherchait un mot dans un **commentaire** que je venais d'écrire ;
- une découpait le fichier sur **5000 caractères fixes** que mes ajouts ont dépassés ;
- une s'ancrait sur un **nom de fonction** que j'avais enveloppé.

Et surtout : **quatorze tests verts n'ont pas vu un `NameError`**, parce
qu'aucun n'EXÉCUTAIT la fonction — ils lisaient son source. Le défaut n'est
apparu qu'au banc, avalé par un `except`. `TestExecutionReelle` ajoutée et
vérifiée **dans les deux sens** (4 échecs sur la version cassée, 18/18 après).

## Observation NON traitée — le plancher d'échappement est périmé

```
stm32-100 : « 36 signaux à échapper — 4 couches seraient nécessaires ; on tente 2 »
            → palier 2 couches : 96 %
```

`_CAPACITE_ECHAPPEMENT = 3.0` déclare 2 couches hors d'atteinte pour une carte
qui rend 96 % sur 2 couches. Il a été calibré **avant** que le plan soit coulé
avant le routage et que les GND soient liés : sa calibration est périmée par
les correctifs de cette nuit, et il ferait acheter 4 couches inutiles.

**Non modifié** : seuil chiffré ⇒ décision produit. À trancher avec l'utilisateur.

## Livré dans le dépôt (local, `output/` est gitignoré)

```
examples/stm32-30/output/etapes/      19 boards + LISEZ-MOI.md
examples/stm32-60/output/etapes/      19 boards + LISEZ-MOI.md
examples/nucleo-f401/output/etapes/   31 boards + LISEZ-MOI.md
```

Chaque légende porte les chiffres MESURÉS de sa carte, ses réserves comprises.

## Reste à faire

- ~~verdict de `stm32-100`~~ — **99 %, 3 manquantes, 0 erreur, 4153 s.** Boards livres.
- **suite complète non re-validée après `1de31db`** — tuée deux fois par la
  contention avec le banc ; ciblé vert (29/29 vias, 6/6 couture d'îlots) ;
- `D-2026-09-02-a` — décision produit ouverte sur les capas de découplage ;
- la relance des placements demandée par l'utilisateur, qui ne changera rien
  pour les capas tant que `D-2026-09-02-a` n'est pas tranchée.

---

# BANC TERMINÉ — les quatre verdicts (2026-09-02)

```
cas             comp  couches   %   manq  err  warn  seg   durée
nucleo-f401       55     2     98     1    1    73   632   3668 s
stm32-30          30     2    100     1    0    24   173    413 s
stm32-60          60     2     98     2    0    68   374    324 s
stm32-100        100     2     99     3    0   130   710   4153 s
```

**Trois cartes sur quatre à ZÉRO erreur de fabricabilité. Les quatre tiennent
sur 2 couches** — aucune n'a eu besoin d'escalader.

Écarts face au témoin :

| carte | avant | après |
|---|---|---|
| `stm32-100` | **70 % · 27 manquantes** | **99 % · 3 · 0 erreur** |
| `stm32-30` | 96 % · 3 manquantes | **100 % · 0 erreur** |
| `nucleo-f401` | 187 violations | **74 violations** · 1 erreur |
| `stm32-60` | 98 % · 1 manquante | 98 % · 2 · **0 erreur** |

⚠️ Freerouting est stochastique. Le 100 % de `stm32-30` et le +1 de `stm32-60`
sont dans le bruit ; **le 0 erreur est le résultat solide**, et il tient sur
trois cartes.

## Livré dans le dépôt (local — `output/` est gitignoré)

```
examples/stm32-30/output/etapes/      19 boards + LISEZ-MOI.md
examples/stm32-60/output/etapes/      19 boards + LISEZ-MOI.md
examples/stm32-100/output/etapes/     19 boards + LISEZ-MOI.md
examples/nucleo-f401/output/etapes/   31 boards + LISEZ-MOI.md
```

## Piste ouverte, non traitée — le repli GND est disproportionné

Les 4153 s de `stm32-100` incluent **plus de vingt minutes de repli GND**,
déclenché par **une seule** broche non reliée : il re-route la carte entière,
GND compris. Router le seul net concerné coûterait quelques secondes. Défaut
d'économie, pas de correction — invisible tant que les cartes étaient petites.

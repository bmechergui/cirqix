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

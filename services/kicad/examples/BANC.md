# Registre du banc — quel résultat, par quelle version

> Ce fichier existe parce qu'une ligne de résultat sans sa version n'est **ni
> rejouable, ni réfutable**. Le 2026-09-02, quatre correctifs de placement se
> sont succédé en quelques heures : sans registre, aucun écart n'était
> imputable à aucun d'eux.
>
> Le banc imprime désormais son SHA avant chaque tableau
> (`scripts/banc_exemples.py::_version_du_code`), et signale `arbre MODIFIÉ`
> quand `tools/` ou `routers/` diffèrent du commit — un SHA seul mentirait par
> omission pendant une session de travail.

## Comment lire les colonnes

```
cas        comp  couches   %   manq  err  warn  seg  GND  durée
```

- `%` — pourcentage routé, **mesuré** sur la connectivité, jamais déclaré
- `manq` — connexions manquantes au DRC `kicad-cli`
- `err` — **erreurs** de fabricabilité : c'est le seul critère qui fait refuser
  une carte. `warn` ne la fait pas refuser
- `GND` — broches GND restées orphelines du plan

---

## Banc du 2026-09-02 — placements VALIDÉS par le code corrigé

Version : **`437a8b4`** (les quatre correctifs de placement de la nuit)
Placements gelés, produits par `scripts/valider_placements.py` — trois tirages
par carte, on garde le meilleur : zéro erreur d'abord, puis le découplage le
plus serré.

```
cas             comp  couches   %   manq  err  warn  seg   durée
nucleo-f401       55     2     98     2    0    54   567   3313 s
stm32-30          30     2     96     3    0    19   167    495 s
stm32-60          60     2     98     3    0    50   415   2795 s
stm32-100        100     2     99     8    0   122   734   3907 s
```

Placements correspondants, distance des condensateurs de découplage au circuit
intégré le plus proche :

```
carte           médiane   maximum   erreurs
nucleo-f401     14,9 mm   17,5 mm      0
stm32-30        12,5 mm   14,0 mm      0
stm32-60        13,3 mm   16,3 mm      0
stm32-100       13,1 mm   18,9 mm      0
```

---

## Banc du 2026-09-02 (nuit) — placements ANCIENS

Version : **`1de31db`** (correctifs de routage seuls ; placements figés hérités)

```
cas             comp  couches   %   manq  err  warn  seg   durée
nucleo-f401       55     2     98     1    1    73   632   3668 s
stm32-30          30     2    100     1    0    24   173    413 s
stm32-60          60     2     98     2    0    68   374    324 s
stm32-100        100     2     99     3    0   130   710   4153 s
```

⚠️ Les placements de ce banc **n'étaient pas versionnés** : ils dataient du
2026-08-19 pour `stm32-validation`, d'origines diverses pour les autres, et
`output/` est gitignoré. Ils sont désormais protégés dans
`examples/<carte>/expected/2_placement_valide.kicad_pcb`.

---

## Comparaison — aucune version ne domine

```
carte           ancien              nouveau             qui gagne
nucleo-f401     98 % · 1 erreur     98 % · 0 erreur     LE NEUF
stm32-30       100 % · 0 erreur     96 % · 0 erreur     L'ANCIEN
stm32-60        98 % · 0 erreur     98 % · 0 erreur     égalité
stm32-100       99 % · 0 erreur     99 % · 0 erreur     égalité
```

**Le fait marquant : les QUATRE cartes sortent à ZÉRO erreur de
fabricabilité, toutes sur DEUX couches.** C'est une première — au banc
précédent, `nucleo-f401` en portait une.

Bilan du changement de placement : **une carte améliorée** (`nucleo-f401`,
1 erreur → 0), **une dégradée** (`stm32-30`, 100 % → 96 %), **deux
inchangées**. Et sur les quatre, un découplage reproductible de 12 à 19 mm là
où l'ancien dépendait du tirage.

⚠️ Les connexions manquantes montent partout (2→3, 1→3, 2→3, 3→8). Aucune
n'est une erreur de fabricabilité — ce sont des liaisons de plan de masse et
des îlots non cousus. Mais la tendance est constante sur les quatre cartes,
donc ce n'est PAS du bruit : le placement resserré rend le plan plus difficile
à raccorder. C'est le prix mesuré du gain sur le découplage.

**Critère de départage retenu : zéro erreur DRC d'abord, puis le taux de
routage.** Les deux versions sont conservées dans Git, le choix est donc
réversible carte par carte.

## Ce que le nouveau code apporte, et ce qu'il coûte

**Apporte** — le découplage devient *reproductible*. L'ancien dépendait du
tirage : 68,7 mm sur `nucleo-f401`, 10,1 mm sur `stm32-validation`, avec le
**même** code. Le nouveau rend 12-19 mm sur les quatre cartes, et supprime
l'erreur DRC qui restait sur `nucleo-f401`.

**Coûte** — du temps de routage. `stm32-60` passe de 324 s à 2795 s, et son
journal montre **trois replis GND**, chacun re-routant la carte entière. Le
placement resserré laisse plus de broches GND hors d'atteinte du plan, donc
plus de replis.

⚠️ Comparaison indirecte : le journal du banc précédent a été supprimé pendant
la session, pour éviter que ses chiffres soient pris pour des neufs. La cause
ci-dessus est cohérente, ce n'est pas une mesure appariée.

## Défaut connu, non corrigé — le repli GND est disproportionné

Il re-route la **carte entière**, GND compris, pour rattraper parfois **une
seule** broche : plus de vingt minutes sur `stm32-100`. Router le seul net
concerné coûterait quelques secondes. C'est un défaut d'économie, pas de
correction, invisible tant que les cartes étaient petites.

## Défaut connu, non corrigé — la carte est trop grande

Les rendus le montrent : `stm32-30` tient dans un tiers de sa surface,
`stm32-60` dans la moitié. Le générateur dimensionne au **nombre** de
composants sans lire leur encombrement. Conséquences en chaîne : pistes
longues, faisceaux parallèles qui **tranchent le plan de masse** en îlots, et
temps de routage gonflé par le vide à explorer.

C'est le levier suivant, et il est en amont du placement comme du routage.
**Non traité** : c'est un changement de comportement livré, donc une décision.

---

## ⚠️ Dimensionnement de carte — hypothèse RÉFUTÉE par la mesure (2026-09-02)

**Ne pas retenter sans lire ceci.**

Le constat de départ était juste : les cartes sont occupées à **2 % à 10 %** par
leurs composants, là où un layout professionnel tourne autour de 30-60 %.

```
carte            carte      surface  nombre   critère qui gagne   occupation
stm32-30          75x56       35,1    75,0    nombre                 7,3 %
stm32-60         132x99       42,5   132,0    nombre                 3,5 %
stm32-100       208x156       50,8   208,0    nombre                 2,0 %
nucleo-f401      122x92       66,4   122,5    nombre                 9,8 %
arduino-uno       84x63       47,2    84,5    nombre                10,4 %
esp32-baseline    93x70       93,1    56,0    SURFACE               33,3 %
```

Le critère « nombre » (`18 + 1,9 × n`, dans `scripts/generer_exemples.py`)
l'emporte sur cinq cartes sur six. Il fait croître le CÔTÉ linéairement avec le
nombre de composants, alors que la géométrie voudrait √n — d'où l'aggravation
avec la taille : 7,3 % à trente composants, 2,0 % à cent.

**L'argument géométrique est juste. La mesure le réfute quand même.**
`stm32-100`, placée deux fois, même code, même circuit :

```
                carte        capas méd / max    DRC
ACTUELLE      208 x 156       13,2 / 20,3 mm    0 erreur · 125 violations · 320 s
SURFACE        51 x 38        20,4 / 30,5 mm    7 ERREURS · 148 violations · 316 s
```

La carte serrée est **pire sur tous les critères** : sept erreurs de
fabricabilité, et un découplage DÉGRADÉ. Elle n'est pas livrable.

**Ce que le plancher protège réellement.** Pas une contrainte physique — à 25 %
d'occupation, il reste de la place. Il compense un OPTIMISEUR DE PLACEMENT qui
a besoin de mou pour résoudre ses conflits. C'est une béquille, mais elle porte
quelque chose.

**Conséquence :** le levier n'est pas la taille de la carte, c'est la capacité
du placeur à travailler dense. Les deux sont liés **dans cet ordre**. Resserrer
la carte d'abord ne fait que produire des boards non fabricables.

Reproduction : `scripts/reference_sans_snap.py` pour le protocole, ou le script
d'expérience décrit ici — générer le même circuit à deux tailles, placer les
deux, comparer erreurs DRC et distance des condensateurs.

## 2026-09-02 · `3554ff4` — le dogbone GND sur toute pastille CMS

**Le banc entier, huit cartes, placements gelés, une seule variable :** le
dogbone de masse est désormais posé sur **toute pastille CMS d'un net de plan**,
avant le routage, au lieu des seuls boîtiers denses.

```
cas                comp couches    %  manq  err  warn   seg  GND   duree
arduino-uno          35       2  100     0    0    35   125   18   182.8s
esp32-baseline       20       2  100     0    0     1   138   12    76.3s
led-blinker           8       2  100     0    0     2    45    3    51.7s
nucleo-f401          55       2  100     0    0    72   690   90  1761.1s
stm32-30             30       2  100     0    0    23   179   17    81.6s
stm32-60             60       2  100     0    0    68   499  105   444.1s
stm32-baseline       17       2  100     0    0    12   102   10    57.9s
stm32-100           100       2   99     1    0   131   779   57   901.3s
```

**Sept cartes sur huit : 100 % routées, zéro manquante, zéro erreur, sur DEUX
couches.** Face au témoin des quatre cartes déjà mesurées :

| carte | témoin | maintenant | durée |
|---|---|---|---|
| `nucleo-f401` | 98 % · 2 manq | **100 % · 0** | 3313 s → **1761 s** |
| `stm32-30` | 96 % · 3 manq | **100 % · 0** | 495 s → **82 s** |
| `stm32-60` | 98 % · 3 manq | **100 % · 0** | 2795 s → **444 s** |
| `stm32-100` | 99 % · 8 manq | 99 % · **1** | 3907 s → **901 s** |

⚠️ **Le gain de TEMPS n'est pas un effet de bord** : trois à six fois plus
rapide. Donner au routeur ses vias de masse d'avance lui épargne le travail
qu'il refaisait ensuite en pure perte, et les re-tirages qu'il déclenchait.

⚠️ **L'ESCALADE DE COUCHES N'A JAMAIS SERVI.** Tout tient sur deux couches. Le
blocage n'était pas un manque de place — c'étaient des pastilles de masse
qu'aucun chemin ne reliait au plan. Grok l'avait dit avant la mesure : « un
plan interne n'invente pas de place ».

⚠️ Les avertissements restants sont de la **sérigraphie** (`silk_overlap`,
`silk_over_copper`) — cosmétique, jamais bloquant en fabrication. Et les
`holes_co_located`, 20 à 40 par carte sur les anciens boards, sont tombés à
**zéro** : le correctif « un trou est un obstacle pour un autre trou » est
vérifié ici sur des boards produits par la chaîne réelle, pas par des
réparations après coup.

### Ce qui reste : l'îlot de `D21` sur `stm32-100`

Une seule connexion manquante, déclarée `Zone GND F.Cu ↔ Zone GND F.Cu`.
Mesure des neuf îlots — huit sont reliés, un ne l'est pas :

```
F.Cu  0,9 mm2   1 via   0 RELIANT   contient la pastille GND de D21
```

Son via traverse vers B.Cu mais **atterrit là où le routage a creusé le plan**.
Et la pastille de `D21` elle-même ne surplombe aucun cuivre de masse sur B.Cu :
un via en pastille n'y relierait rien, et serait de toute façon refusé pour
dégagement.

⚠️ **Deux remèdes sont ÉCARTÉS, chacun par une mesure :**

- *filtrer la couture sur « la face opposée porte du cuivre »* — essayé le
  2026-09-01, **réfuté** : 1 manquante devient 4. La préférence reste, le
  filtre non.
- *retirer le via borgne* (proposé par Grok le 2026-09-02) — il est à 0,847 mm
  de la pastille, donc au-delà de l'écart trou-à-trou : il ne bloque rien, et
  le retirer ne crée pas de cuivre.

Le levier restant se situe **au routage, pas à la réparation** : poser aussi
une courte piste de masse sur la face opposée du dogbone, protégée dans le DSN,
pour que le plan puisse toujours rejoindre le via. Non implémenté, non mesuré.

### Tentative RÉFUTÉE — le dogbone à deux faces (2026-09-02)

Pour fermer l'îlot de `D21`, j'ai posé avec chaque via de dogbone une courte
piste de masse **sur la face opposée**, protégée dans le DSN. GLM validait :
« sa fin ouverte fusionnera avec le plan puisqu'elle porte le même net, c'est
un pont forcé à travers la coupure » — en avertissant du **bouchon de
routage**. C'est le bouchon qui l'a emporté.

```
                   %   manq  err  seg  segments GND   duree
sans amorce       99     1     0  779       57         901 s
avec amorce       99     1     0  732        6        2798 s
```

Aucun gain sur la connexion manquante, **trois fois plus lent**, et les
segments GND survivant au round-trip Specctra s'effondrent de **57 à 6** : les
amorces protégées gênent le routeur au point de lui faire perdre les dogbones
eux-mêmes. Le remède coûtait plus que le mal.

Retiré. La réfutation est inscrite à son site exact dans
`tools/routing_pcbnew_runner.py::_escape_pads`, avec ses chiffres — un futur
lecteur y trouvera pourquoi ne pas la retenter telle quelle.

⚠️ C'est la CONDITION qui est réfutée, pas l'analyse : l'îlot de `D21` reste
causé par un via isolé après coup. Un remède devra agir **sans ajouter de
cuivre protégé sur la face que le routeur utilise**.

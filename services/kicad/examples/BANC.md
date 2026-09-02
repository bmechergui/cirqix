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

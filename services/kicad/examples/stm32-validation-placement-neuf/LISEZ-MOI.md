# `stm32-validation` avec le placement du code corrigé

Dossier **séparé**, créé le 2026-09-02 à la demande de l'utilisateur.
`examples/stm32-validation/` n'est **pas** modifié : c'est le cas d'étude de
référence du projet, sa fixture `expected/stm32_final.kicad_pcb` sert de témoin
pytest, et son placement porte les mesures publiées.

## Ce que contient ce dossier

```
expected/2_placement_ancien.kicad_pcb    le placement de référence, pour comparer
output/2_placement_neuf.kicad_pcb        le RETENU parmi trois tirages
output/2_placement_neuf_t1..t3.kicad_pcb les trois tirages, pour juger la dispersion
```

## Verdict — les deux se valent, l'ancien garde un léger avantage

Distance des dix condensateurs au circuit intégré le plus proche, et DRC :

| | médiane | maximum | erreurs | violations |
|---|---|---|---|---|
| **ancien** | **10,1 mm** | **12,6 mm** | **0** | **25** |
| neuf (retenu, tirage 2) | 10,0 mm | 12,9 mm | 0 | 31 |

Le découplage est **équivalent** — un dixième de millimètre d'écart sur la
médiane. L'ancien conserve un avantage de 0,3 mm sur le maximum et de six
violations (toutes de sérigraphie, aucune erreur des deux côtés).

**Recommandation : garder l'ancien.** Le neuf ne l'améliore pas, donc il n'y a
aucune raison de remplacer un placement sur lequel reposent des mesures
publiées.

## ⚠️ Le premier tirage a failli me faire dire l'inverse

```
tirage 1   médiane 21,1 mm   max 28,7 mm   3 ERREURS   34 violations   348 s
tirage 2   médiane 10,0 mm   max 12,9 mm   0 erreur    31 violations   983 s
tirage 3   médiane 10,1 mm   max 13,1 mm   0 erreur    35 violations   306 s
```

Sur le seul tirage 1, j'ai annoncé que le nouveau code **dégradait** cette
carte — deux fois plus lâche sur le découplage, et trois erreurs DRC. Les
tirages 2 et 3 l'ont démenti : ils égalent l'ancien.

Le tirage 1 était une aberration, pas une tendance. C'est exactement la faute
que ce dépôt documente à répétition — **conclure d'un tirage isolé quand le
mécanisme est stochastique**. Le placement l'est : le projet a mesuré 6, 8 puis
12 connexions manquantes sur une même carte selon le tirage.

Les trois tirages sont livrés pour que la dispersion soit vérifiable, et pas
seulement le meilleur.

## Ce que cette carte apprend sur le nouveau code

Le correctif du placement (`f037d29`, `437a8b4`) est franchement bénéfique
**quand le placement de départ est mauvais**, et neutre quand il est déjà bon :

```
nucleo-f401        68,7 mm  ->  17,5 mm      gain d'un facteur quatre
stm32-100          ~100 mm  ->  18,9 mm
stm32-30                    ->  14,0 mm
stm32-60                    ->  16,3 mm
stm32-validation   12,6 mm  ->  12,9 mm      équivalent, déjà bon
```

Il ne dégrade nulle part — mais il ne faut pas en attendre un miracle là où le
placement existant est déjà serré.

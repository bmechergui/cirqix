# Où sont les sorties d'une carte

Question posée le 2026-09-07 — « les dix cartes, leur sortie est où ? » — puis
de nouveau le 2026-09-23. Deux fois la même question veut dire que la réponse
n'était trouvable nulle part : elle vivait dans le commentaire d'un script.

## La règle en une phrase

**Ce qui est VERSIONNÉ tient dans `expected/` ; ce qui est REGÉNÉRABLE vit dans
`output/`, qui est gitignoré.**

```
examples/<carte>/
├── input/           ← VERSIONNÉ   la description du circuit
│   └── schema.json        (ou circuit.json sur les cartes historiques)
├── expected/        ← VERSIONNÉ   le résultat, et de quoi le juger
│   ├── placement.kicad_pcb     le board PLACÉ, sans une piste — le TÉMOIN
│   ├── final.kicad_pcb         le board ROUTÉ, livré
│   ├── mesures.json            % routé, erreurs, violations, segments, vias
│   ├── journal.txt             ce que la chaîne a dit en le produisant
│   └── rendu-3d.png            à quoi la carte ressemble
└── output/          ← GITIGNORÉ  refait à la demande
    ├── placement.kicad_pcb · placement-dessus.svg · vue-placement.png
    ├── routage.kicad_pcb · routage-dessus.svg · routage-dessous.svg
    │   routage-3d.png · vue-final.png
    ├── 19 Gerbers (.gtl .gbl .gts .gbs .gto .gbo .gm1 …)
    ├── cirqix-pcb.drl          perçages
    ├── pos.csv                 placement des composants pour la machine
    ├── fabrication.zip         le dossier complet, prêt à envoyer
    └── mesures-export.json
```

## Pourquoi les Gerbers ne sont pas dans Git

Parce qu'ils se **dérivent** du board livré : `expected/final.kicad_pcb` est la
source, les vingt fichiers de fabrication en sont la conséquence. Les versionner
reviendrait à versionner un résultat de compilation — et à devoir les
re-committer à chaque tirage.

La contrepartie, c'est qu'il faut pouvoir les refaire à tout moment :

```
python scripts/exporter_les_cartes.py                  # toutes les cartes
python scripts/exporter_les_cartes.py carte-07-multi-io
```

Ce script passe par `POST /export/all`, **la route de la production** — pas un
chemin de test. Ce qu'il produit est ce qu'un client recevrait.

⚠️ Ces fichiers n'existent que sur le disque de la machine qui les a produits.
Ce dépôt a déjà perdu un banc entier pour l'avoir oublié : les boards routés des
huit cartes historiques étaient restés dans le conteneur et sont partis au
premier redémarrage, alors que la documentation les annonçait à 100 %.
**ALWAYS** sortir du conteneur ce qu'on veut garder.

## Pourquoi le placement est livré à côté du routage

Le board placé non routé est le **témoin**. Sans lui, on impute au routage des
défauts qui préexistaient — ce dépôt a déjà attribué au routeur 204 erreurs DRC
présentes sur un board sans la moindre piste.

Un témoin qui ne correspond pas au board routé ment plus qu'un témoin absent :
`livrer_placements.py` refuse de livrer un placement qui ne correspond pas au
routage livré, avec une tolérance de formatage (`134.043534` et `134.0435` sont
la même position, pas deux).

## Ce que `mesures.json` dit, et ce qu'il ne dit pas

Il porte `routed_percent`, les erreurs, les violations par type, la taille du
board et son compte de cuivre.

⚠️ **`drc_clean: true` ne veut pas dire « fabricable ».** Le drapeau ne compte
que les violations de sévérité `error`. Or `hole_to_hole` — deux perçages trop
proches, voire qui se recoupent — sort en **warning**. Mesuré le 2026-09-23 sur
`carte-11-croisements` : `drc_clean: true` sur une carte portant deux vias à
0,340 mm bord à bord (0,50 exigé) et deux vias recoupant le perçage d'une
pastille de connecteur à **−0,050 mm**. Aucun fabricant ne perce cela.

Lire `types_violations`, toujours, avant de conclure qu'une carte part en
fabrication.

⚠️ **`board_mm` et `board_mm_demande` sont deux choses différentes.** Le premier
est mesuré sur `Edge.Cuts`, le second est ce que la description réclamait. Ils
diffèrent d'un facteur cinq en surface sur les cartes compactes, et pendant un
temps seul le second était rapporté — donc faux.

## Refaire une carte

```
# une carte du banc driver (input/schema.json) — garde le MEILLEUR board,
# ne remplace jamais par un moins bon
python scripts/regenerer_le_banc.py carte-07-multi-io

# les cartes historiques (input/circuit.json) — écrit dans output/, jamais
# dans expected/ ; la livraison se fait après coup, à froid
bash scripts/campagne_banc.sh 1 <cartes…>      # schema.json
```

⚠️ **Supprimer `/tmp/cirqix-reglages.json` avant toute mesure.** Ce fichier
active des leviers de banc — la graine en étoile, le plan GND interne — et le
service avertit à chaque tirage : « ce tirage n'est pas la production ».
Mesuré le 2026-09-23 : le fichier traînait depuis le matin et a piloté une
campagne de huit cartes sans que je m'en aperçoive avant le journal final.

⚠️ **Ne jamais écrire `pkill -f <motif>` dans un `sh -c` qui contient ce
motif** : la commande se vise elle-même et meurt avant la suite. C'est ainsi que
mon nettoyage n'a rien nettoyé, deux fois de suite. Tuer par PID, ou couper le
motif (`"banc_exem""ples"`).

⚠️ **`/app/examples` est CUIT dans l'image du conteneur, pas monté.** Un banc
lancé sans racine explicite mesure les cas de l'image, pas ceux du disque —
et `scripts/` non plus n'est pas monté, donc y lancer un script sans l'avoir
poussé mesure une version datant du build.

## Le rejeu ne remplace jamais un bon board par un moins bon

Le placement et le routage sont **stochastiques** : 23 points d'écart mesurés
entre deux tirages d'une même carte au même placement, et `carte-10` rejouée le
2026-09-23 au soir est sortie à 98 % / 1 manquante quand son board versionné
est à 100 % / 0.

`regenerer_le_banc.py` classe sur `(composants perdus, erreurs, −% routé)` et
ne garde le nouveau board que s'il n'est pas moins bon. Un board **complet**
l'emporte toujours sur un board amputé, quel que soit son DRC : un composant
absent n'a aucune connexion manquante à signaler, et classer sur le DRC seul
préférerait indéfiniment la carte incomplète.

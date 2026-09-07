# Banc « driver LLM » — dix cartes, du schéma aux Gerbers

Dix cartes de complexité croissante, **toutes passées par la chaîne complète**,
et dont le schéma est écrit par le driver : Claude Code joue l'agent Schéma, et
aucun appel au modèle n'a lieu.

## Pourquoi ce banc existe

⚠️ **Le banc historique ne teste pas ce que le produit promet.** Ses huit cartes
partent toutes de `circuit.json` **figés** — seul `led-blinker-full-pipeline`
part d'un `schema.json`. Aucune ne part d'une description en langage naturel, qui
est pourtant la promesse : *« conception PCB par langage naturel »*.

    stm32-validation   generate_design.py, project.kct
    nucleo-f401        circuit.json
    stm32-100          circuit.json
    arduino-uno        circuit.json

Le banc historique valide donc le **routage**. Il ne valide ni la génération du
schéma, ni la chaîne entière. Relevé par Grok le 2026-09-05, confirmé fichier
par fichier.

⚠️ Second motif : **le solde de l'API du modèle est épuisé** depuis le
2026-09-06. Un run enfilé dans la file échoue en 5 s. L'orchestrateur étant la
première étape, plus aucun pipeline ne peut aboutir par la voie normale. Ce banc
la contourne sans rien simuler : le schéma est réellement raisonné, simplement
par un assistant plutôt que par une requête facturée.

## Les cartes

Chaque dossier porte son `README.md` **généré depuis ses mesures**, avec sa
version git. Voir `scripts/readme_banc_driver.py`.

| carte | ce qu'elle ajoute |
|---|---|
| `carte-01-diviseur` | le minimum : un diviseur, une LED |
| `carte-02-alimentation` | deux régulateurs, découplage complet |
| `carte-03-oscillateur` | un SOIC-8, trois sorties |
| `carte-04-mcu-minimal` | **premier LQFP-48 fine-pitch**, SWD |
| `carte-05-capteur-i2c` | bus I2C, capteur LGA-8, tirages |
| `carte-06-io-etendu` | huit sorties, deux connecteurs |
| `carte-07-multi-io` | douze sorties **sur les quatre côtés**, cinq connecteurs |
| `carte-08-dense` | seize sorties, cinq connecteurs |
| `carte-09-tres-dense` | huit connecteurs, **plafond 4 couches** |
| `carte-10-maximale` | toutes les broches libres du LQFP-48 |

⚠️ Cette colonne dit une INTENTION de conception. Les comptes de composants et
les verdicts sont mesurés, et vivent dans le tableau généré en fin de page —
ils n'ont pas leur place ici, où ils dérivent. Celui-ci annonçait encore
« carte-07 : 47 composants » quand la carte en porte 48.

## Une règle de conception appliquée partout

⚠️ **Les broches d'entrée-sortie sont prises sur les QUATRE côtés du boîtier**,
jamais groupées d'un seul. Ce n'est pas un détail de style : `generer_exemples.py`
documente la mesure du 2026-08-28 sur la Nucleo — seize liaisons aboutissant dans
la même bande de 8 mm du LQFP-64, par des fils de 44 à 62 mm, et la carte
plafonnait à 68 %. Aucun routeur ne démêle cela, ni en ajoutant des couches, ni
en re-tirant.

## Ce qui a été trouvé en montant en complexité

Chacun de ces défauts n'apparaît qu'au-delà d'un certain nombre de composants,
ce qui est exactement l'intérêt d'un banc progressif.

**1. Le client coupait à 600 s** (`run_pipeline.py`). Le placement de la
`carte-07` le dépassait : `TimeoutError` côté client pendant que le service
travaillait encore. Porté à 3600 s, aligné sur le service.

**2. Les couches étaient codées en dur à 2.** Le service ne pouvait donc jamais
escalader, quelle que soit la densité — `carte-09` sortait à « 0 %, tous les
tirages ont stagné ». Le plafond se pilote désormais par `max_layers` dans le
schéma, et il ne PRESCRIT rien : le service part toujours de 2 et n'escalade que
sur preuve d'échec.

**3. Aucun budget de routage n'était transmis**, donc le service retombait sur
son défaut de 300 s alors qu'il en accepte 3600. Pilotable par `route_budget_s`.

⚠️ Ces trois défauts sont **la même famille**, déjà nommée dans `CLAUDE.md` :
« le plafond n'était pas UN endroit, mais QUATRE ». Un budget plus serré chez
l'appelant rend inatteignable tout ce qui est plus lent que lui, et rien dans la
réponse ne trahit la substitution.

**4. La surface, pas le DRC.** Ce qui a fait passer la `carte-08` de 216
connexions manquantes à ZÉRO est de l'avoir AGRANDIE — 110 × 80 mm puis
125 × 95. Rien d'autre n'a changé.

⚠️ **J'ai d'abord attribué ce gain à un correctif du DRC**, que j'avais écrit et
documenté ici : `/drc/auto` aurait mesuré avant de couler les plans. **C'est
faux, et la mesure directe l'a réfuté** — le même board, plans re-remplis ou
non, rend 5 connexions manquantes dans les deux cas. Le correctif et sa garde
ont été retirés.

C'est la faute que ce dépôt s'interdit explicitement : *« NEVER relayer le
message d'une garde comme un diagnostic »*, et sa jumelle — ne jamais garder
dans la documentation une explication qu'une mesure a démentie. Elle est
conservée ici en toutes lettres parce qu'un lecteur aurait construit dessus.

**5. La divergence du placement** (`carte-07`, 2026-09-07). Le placement de
cette carte dure **1560 s**, contre 104 s pour la `carte-08` (56 composants) et
130 s pour la `carte-10` (70). Douze fois plus long pour MOINS de composants.

Vérifié : son schéma est sain — aucune broche pointant vers un composant absent,
aucun composant isolé, la même structure que la `carte-08` dont elle dérive. La
cause est le placement lui-même, qui n'a **pas de graine fixe**
(`OptimizationWorkflow` en stratégie `hybrid`). Ce dépôt documentait déjà sa
dispersion en QUALITÉ — 6, 8 et 12 connexions manquantes selon le tirage ; on
mesure ici qu'elle porte aussi sur la DURÉE, et dans un rapport de douze.

Conséquence pratique : le temps d'un pipeline n'est pas prévisible à partir du
nombre de composants, et un budget client calibré sur une moyenne coupera
certaines cartes en plein travail.

**6. Freerouting tourne mille passes pour rien** (2026-09-07). Comptage sur le
journal du service, cinq travaux distincts :

    996 passes  score 815.45  (40 non routes)
    996 passes  score 701.71  (50 non routes)
    996 passes  score 685.09  (42 non routes)
    996 passes  score 650.03  (43 non routes)
    992 passes  score 770.97  (34 non routes)

Le score et le nombre de connexions manquantes sont **identiques d'un bout a
l'autre** : ces travaux n'ont rien ameliore apres leur premiere passe, et ont
consomme ~1,2 s chacune jusqu'au plafond de mille. Environ vingt minutes par
travail, entierement perdues — multipliees par les trois tirages de chaque
palier.

Le levier evident serait d'arreter sur absence de progression plutot que sur un
compte de passes. ⚠️ C'est un **seuil chiffre qui change le comportement
livre** : decision produit, donc proposee et non appliquee. Consignee dans
`docs/DECISIONS.md`.

⚠️ Ce que ce comptage ne dit PAS : que la machine etait saturee. Je l'ai cru en
voyant une JVM a 211 %% de processeur depuis sept heures. Mesure : **12
processeurs, charge moyenne 4,00**, et la liste des sessions du serveur est
vide. La lenteur de la `carte-07` n'est donc pas une contention — c'est bien son
placement, comme le disent les 1560 s.

## Ce qui compte comme « fabricable »

⚠️ **Le verdict se lit dans la SÉVÉRITÉ rendue par KiCad**, et il est mesuré sur
le **board livré**, pas sur le résumé du pipeline.

Deux règles, chacune payée par une mesure :

**La sévérité ne se devine pas.** `via_dangling`, `track_dangling`,
`silk_overlap` et `silk_over_copper` sont classés **warning** par KiCad — un via
orphelin est percé et plaqué, la carte se fabrique. Seul « Missing connection »
est classé **error**. Je les classais sur ma propre liste, plus sévère que KiCad
lui-même, ce qui déclarait non fabricables des cartes qui le sont.

**Le pipeline surestime.** Sur le MÊME fichier, `carte-09` :

    kicad-cli direct   :   9 non connectés,  70 violations
    service /drc/auto  :  18 non connectés, 154 violations

et jusqu'à 280 quand la boucle de correction itère. La cause de l'écart n'est
pas établie ; ce qui l'est, c'est lequel des deux juge le board qu'on livre.

## Les dix cartes tiennent sur DEUX couches

Compte des couches cuivre dans les boards livrés : `F.Cu` et `B.Cu`, rien
d'autre, y compris pour les 70 composants de la `carte-10`.

La `carte-09` est la seule à porter un plafond à quatre couches
(`max_layers: 4` dans son schéma), et **elle ne s'en est pas servie** : elle a
réussi au premier palier. C'est le comportement attendu — le plafond ne
PRESCRIT rien, le service part toujours de 2 et n'escalade que sur preuve
d'échec, en gardant toujours le meilleur tirage et jamais le dernier.

Deux couches coûtent moins cher à fabriquer que quatre. Une escalade qui ne se
déclenche pas est donc un succès, pas une capacité inemployée. Le banc des huit
cartes historiques avait fait le même constat le 2026-09-03 : *« aucune escalade
de couches n'a servi »*.

⚠️ Avant le 2026-09-07, **aucun schéma ne déclarait `max_layers`** : les dix
cartes tournaient toutes à deux couches, et la description de la `carte-09`
annonçait pourtant « plafond 4 couches ». La documentation promettait une
capacité que le fichier ne déclarait pas. C'est la faute déjà inscrite dans
`CLAUDE.md` à propos d'une section d'ordre d'exécution laissée périmée, et qui
avait fait conclure à une cascade mal ordonnée.

## Deux tirages ne prouvent rien

Les deux cartes qui ont résisté le montrent, chacune à sa manière.

La `carte-07` a rendu 5, puis 2, puis 3 erreurs, puis 0 % routé, avant
d'atteindre zéro. La `carte-09` a rendu 1 erreur, puis 2 au tirage suivant, puis
zéro — **sur le même schéma**, à ceci près qu'on lui avait ouvert un plafond
qu'elle n'a finalement pas utilisé.

Le placement et le routage sont tous deux stochastiques. Ce dépôt mesure déjà
23 points d'écart entre deux tirages d'une même carte au même placement. Un
résultat isolé ne dit donc rien, ni en bien ni en mal — et c'est exactement sur
deux tirages concordants que j'avais conclu, à tort, à un défaut structurel.

## Rejouer

```
python scripts/banc_driver_llm.py examples/carte-01-diviseur
python scripts/readme_banc_driver.py --tous
```

⚠️ `examples/` n'est **pas monté** dans le conteneur : il est cuit dans l'image.
Le banc extrait donc chaque board aussitôt — sans quoi l'artefact part au premier
redémarrage, la leçon des worktrees vides transposée.

⚠️ **Un seul routage à la fois.** Deux routages concurrents font tuer le
processus par le noyau (décision `D-2026-09-03-b`), et le verrou du service les
sérialise. Le banc ne lance donc jamais deux cartes en parallèle.

## Resultats mesures

<!-- TABLEAU GENERE -->
| carte | comp. | nets | routage | erreurs | fabricable |
|---|---|---|---|---|---|
| `carte-01-diviseur` | 5 | 4 | 100 % | 0 | **oui** |
| `carte-02-alimentation` | 12 | 5 | 100 % | 0 | **oui** |
| `carte-03-oscillateur` | 15 | 9 | 100 % | 0 | **oui** |
| `carte-04-mcu-minimal` | 15 | 7 | 100 % | 0 | **oui** |
| `carte-05-capteur-i2c` | 26 | 13 | 100 % | 0 | **oui** |
| `carte-06-io-etendu` | 35 | 27 | 100 % | 0 | **oui** |
| `carte-07-multi-io` | 44 | 37 | 100 % | 0 | **oui** |
| `carte-08-dense` | 56 | 49 | 100 % | 0 | **oui** |
| `carte-09-tres-dense` | 62 | 49 | 100 % | 0 | **oui** |
| `carte-10-maximale` | 70 | 49 | 100 % | 0 | **oui** |
<!-- FIN TABLEAU GENERE -->

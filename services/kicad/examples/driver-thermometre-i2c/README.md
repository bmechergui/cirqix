# driver-thermometre-i2c — le schéma écrit par `claude -p`, sans main humaine

**Question posée :** avec `CIRQIX_SCHEMA_PROVIDER=claude-code` (D-2026-09-13-a),
une simple phrase déposée dans la file suffit-elle pour qu'un PCB sorte, le
schéma étant écrit par Claude Code en ligne de commande — ni par Haiku (solde
API à zéro), ni à la main ?

**Réponse (2026-09-13) : oui pour la chaîne, non pour la qualité du schéma.**
Run `25a6853c`, projet `2be02059`, provenance `driver`, 279 s, 0 crédit.

## La description (le seul texte fourni)

> Un thermomètre I2C : capteur de température TMP102 sur un bus I2C avec ses
> deux résistances de pull-up 4,7k, alimenté en 3,3 V par un régulateur
> AMS1117-3.3 depuis 5 V avec 10 µF de part et d'autre, 100 nF de découplage
> sur le capteur, un connecteur 4 broches (5V, GND, SDA, SCL) et une LED
> d'alimentation verte avec sa résistance 1k.

## Ce que la chaîne a produit

| étape | résultat |
|---|---|
| SCHEMA (`engine: claude-code`) | 10 composants, 6 nets, écrits par `claude -p` en ~20 s |
| ERC, PLACEMENT, ROUTING | 100 % sur 2 couches, 14 vias, 68 mm de piste |
| DRC, EXPORT | `drc_clean`, 20 Gerbers, `PCB_LIVRÉ` |

Vérifié en local (`kicad-cli pcb drc`) : **0 erreur, 0 connexion manquante**,
2 `silk_overlap` et 1 `silk_edge_clearance`.

## Ce que le schéma vaut — lu honnêtement

`input/schema.json` est **exactement** ce que le modèle a rendu, extrait de
l'événement `SCHEMA_DONE`. Il est fabricable, il n'est pas fidèle :

- le TMP102 est modélisé en **connecteur 6 broches** (`Conn_01x06`), pas en
  capteur SOT-563 ;
- la net **SDA ne porte qu'une broche** : le bus I2C n'atteint pas le
  connecteur, et un net à une broche n'est pas « manquant » pour le DRC ;
- la LED est un boîtier traversant 5 mm (`LED` nu, résolu par le repli), le
  connecteur 4 broches portait une empreinte 1x02 corrigée par la validation.

Le DRC ne juge pas l'intention électrique. Ce run prouve le **pont** (CLI, stdin,
enveloppe JSON, provenance, file, worker), pas que le prompt système hérité de
Haiku suffit à un modèle de ligne de commande sans relecture. Prochain levier :
enrichir le contrat de schéma (comptes de broches par empreinte, nets à ≥ 2
broches exigés, symboles de capteurs), commun aux deux fournisseurs.

## Ce que ce run a aussi révélé (corrigé)

- `claude -p` héritait de `ANTHROPIC_API_KEY` du worker et la préférait à la
  session claude.ai → échec sur le solde à zéro. Le CLI est lancé sans les
  variables d'authentification API.
- Un pipeline arrêté sur une erreur sans `done` était marqué `succeeded`.
- Un job échoué par BullMQ hors de `runJob` (worker tué en plein placement)
  laissait le run `running` pour toujours.

## Fichiers

- `input/schema.json` — le schéma rendu par Claude Code, tel quel
- `expected/schema.kicad_sch`, `expected/final.kicad_pcb`, `expected/rendu-3d.png`, `expected/mesures.json`

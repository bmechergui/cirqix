# driver-thermometre-i2c — le schéma écrit par `claude -p`, sans main humaine

**Question posée :** avec `CIRQIX_SCHEMA_PROVIDER=claude-code` (D-2026-09-13-a),
une simple phrase déposée dans la file suffit-elle pour qu'un PCB sorte, le
schéma étant écrit par Claude Code en ligne de commande — ni par Haiku (solde
API à zéro), ni à la main ?

**Réponse (2026-09-13) : oui — et le premier essai a révélé que « 100 % routé,
0 erreur » ne disait rien de la fidélité du schéma.** Deux runs, même phrase :

| run | contrat de schéma | SDA | SCL | routage | DRC | durée |
|---|---|---|---|---|---|---|
| `25a6853c` | d'origine | **1 broche** | 2 | 100 % | 0 erreur | 279 s |
| `537dc8a5` | durci | **3 broches** (capteur, pull-up, connecteur) | 3 | 100 % | 0 erreur | 198 s |

Le premier board était fabricable et **sans bus I2C** : le filtre de broches
comptait 2 pastilles pour tout footprint qu'il ne connaissait pas
(`PinHeader_1x04` compris) et effaçait en silence les broches 3 et 4 du
connecteur. Une net à une broche n'est pas « manquante » pour le DRC.

## La description (le seul texte fourni)

> Un thermomètre I2C : capteur de température TMP102 sur un bus I2C avec ses
> deux résistances de pull-up 4,7k, alimenté en 3,3 V par un régulateur
> AMS1117-3.3 depuis 5 V avec 10 µF de part et d'autre, 100 nF de découplage
> sur le capteur, un connecteur 4 broches (5V, GND, SDA, SCL) et une LED
> d'alimentation verte avec sa résistance 1k.

## Le contrat durci (commun à Haiku et à Claude Code)

- le compte de pastilles se **lit dans le nom** du footprint (`1x04`, `2x15`,
  `LQFP-48`, `SOIC-8`, `SOT-223-3`…) ; un nom muet ne filtre plus rien ;
- `problemesDuSchema` nomme ce que le DRC ne voit pas : net à moins de deux
  broches, connecteur dont le footprint ne suit pas le symbole ;
- `call_agent_schema` rejoue **une** fois avec les problèmes, puis refuse ;
- l'enrichissement ne réécrit plus un footprint déjà qualifié (`quickLookup`
  rendait un 1x02 pour tout `J…`, quel que soit l'indice).

## Ce que le schéma vaut encore

`input/schema.json` est ce que le modèle a rendu au second run. Le TMP102 y est
un **connecteur 6 broches** : c'est la stratégie du prompt (« module →
connecteur »), pas une erreur du modèle. La LED est un boîtier traversant 5 mm
(`LED` nu, résolu par le repli). Fidèle à la description, pas à un vrai TMP102
en SOT-563 — prochain levier, s'il est voulu : des symboles de capteurs réels.

## Fichiers

- `input/schema.json` — le schéma rendu par Claude Code (run `537dc8a5`)
- `expected/schema.kicad_sch`, `expected/final.kicad_pcb`, `expected/rendu-3d.png`, `expected/mesures.json`

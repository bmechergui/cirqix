# Parcours complet sans appel au modèle — Claude Code joue l'agent Schéma

**1 dossier = 1 cas = 1 question.** Celle-ci : *la chaîne entière peut-elle
aboutir quand le schéma vient d'un humain (ou d'un assistant) au lieu de
l'agent Haiku ?*

Réponse mesurée le 2026-09-06 : **oui, de bout en bout**.

```
VERDICT : routage 100% · DRC clean=True (skipped=False) · 20 fichiers exportés
PIPELINE COMPLET OK
```

## Pourquoi ce cas existe

⚠️ **Le solde de l'API du modèle est épuisé** depuis le 2026-09-06 : un run
enfilé dans la file échoue en 5 secondes sur `400 invalid_request_error —
Your credit balance is too low`. L'orchestrateur étant la toute première étape,
plus aucun pipeline ne peut aboutir par la voie normale.

⚠️ Et c'est un angle mort plus ancien, relevé par Grok le 2026-09-05 : les huit
cartes du banc partent toutes de `circuit.json` **figés**. Aucune ne part d'une
description en langage naturel, qui est pourtant la promesse du produit. Le banc
valide le routage ; il ne valide pas la génération du schéma.

Ce cas répond aux deux : le schéma est produit **par un raisonnement**, pas
copié d'un fichier existant, et la chaîne tourne **sans le moindre appel
payant**.

## Le circuit

Description de départ : « un régulateur 5 V vers 3,3 V avec ses condensateurs de
découplage, une LED témoin d'alimentation, et un connecteur d'entrée ».

9 composants, 4 nets, 40 × 30 mm. Un AMS1117 en SOT-223, deux paires de
découplage (10 µF + 100 nF de chaque côté du régulateur), une LED avec sa
résistance de limitation, deux connecteurs.

## Ce qui a été mesuré

| étape | résultat |
|---|---|
| schéma → `.kicad_sch` | 40 779 octets |
| ERC | passé |
| génération du PCB | 9 empreintes |
| placement | appliqué |
| **routage** | **100 %**, 31 segments, 12 vias, 2 plans |
| reasoner | **non déclenché** — déjà à 100 %, comportement attendu |
| DRC | `clean=True`, 9 violations, **toutes cosmétiques** |
| export | 20 fichiers (Gerbers, perçage, position) |

⚠️ Les 9 violations sont 6 `silk_overlap`, 2 `silk_over_copper` et 1
`track_dangling` : de la sérigraphie qui se chevauche, jamais un défaut de
fabricabilité. `clean=True` est donc un verdict, pas une indulgence.

## Rejouer

Le script `run_pipeline.py` de `led-blinker-full-pipeline/` lit `input/schema.json`
**à côté de lui**. Pour rejouer ce cas, copier les deux dans un même dossier du
conteneur :

```
docker cp <dossier> cirqix-kicad:/tmp/parcours
docker exec -u root cirqix-kicad chmod -R 777 /tmp/parcours
docker exec cirqix-kicad python3 /tmp/parcours/run_pipeline.py /tmp/parcours/output
```

⚠️ `examples/` n'est **pas monté** dans le conteneur : il est cuit dans l'image.
Un board produit n'existe donc QUE dans le conteneur et part au premier
redémarrage — d'où `expected/final.kicad_pcb`, extrait aussitôt.

⚠️ Les droits : le conteneur tourne en `cirqix` (uid 10001), un dossier copié
appartient à `root`. Sans le `chmod`, le script échoue sur `PermissionError` en
créant `output/`.

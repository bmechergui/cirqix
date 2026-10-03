# Temps de routage — diagnostic et correctifs (2026-09-29 → 2026-10-01)

Question de l'utilisateur : « Freerouting route une carte en quelques secondes,
pourquoi un routage prend-il une heure ? » Page de synthèse :
https://claude.ai/artifact/RNSgD4NTcp5E3MbfTLWYQv (privée). PR #238.

## Diagnostic

Freerouting, par l'API, route carte-09 à 100 % en 4 s. Le temps venait du code
autour de lui, et du placement. Chaque cause a été mesurée, puis corrigée.

| cause | mesure | correctif | commit |
|---|---|---|---|
| sonde de l'API à 2 s, repli silencieux sur un CLI sans coupure | 18 min pour 83 % | sonde qui attend la JVM ; CLI surveillé comme l'API | 02a6a7aa |
| replis GND sur un tirage où un signal manque | 686 s pour « 4 manquantes → 4 » | replis sautés sous le plafond quand un signal manque | 02a6a7aa |
| préparation refaite à chaque tirage | 25–105 s par tirage | mémorisée par board pour l'appel | e34fa88c |
| réparations GND locales après les replis | finitions 135–1167 s | réparations locales avant les replis | e34fa88c |
| moteur C++ du placement non installé | carte-07 : 2144 s de placement | `placement_cpp` construit dans l'image | d15f9865 |
| broche GND orpheline seule, visée par aucune réparation | ~5 min de replis par tirage | courte piste vers le plan principal (`relier_pastilles`) | 593ff2c9 |
| familles LED + R rangées dans le halo d'échappement de U1 | carte-09 : tirages figés à 67–83 % | familles hors du halo des boîtiers denses | ce commit |

Le moteur C++ du placement calcule exactement les mêmes forces que le Python
(écart 0 sur la répulsion, 10⁻¹⁶ sur les forces totales, 0 mm de position après
40 itérations, sur carte-02, 05 et 07), 70 à 220 fois plus vite.

## Pistes écartées par la mesure

- **Recul du contour de 0,6 mm** (travail d'une autre session) : A/B, 1 tirage
  par bras, avec 100 % / 6 couches, sans 95 % / 6 couches. Pas la cause.
- **Liaison GND avant routage** : 3 tirages par bras sur carte-09, actuel
  4/4/6 couches, sans liaison 6/4/8. Pas la cause.
- **GND routé comme un signal** : plan coulé avant, 97 % ×3 ; plan seulement à la
  fin, 63 % à 8 couches et deux tirages sans résultat après une heure. Rejeté.
- **Escalade qui garde le routage** : un tirage figé ne rend aucun board, il n'y
  a rien à garder.

## Banc des dix cartes, 1 tirage, placement + routage

| carte | 30/09 matin | 30/09 soir (C++, raccord GND) | 01/10 (+ halo) |
|---|---|---|---|
| carte-01 à 05 | 2 couches | 2 couches | 2 couches, 3–4 min |
| carte-06 | 4 couches, 26 min | 4 couches, 10 min | **2 couches**, 7,5 min |
| carte-07 | 4 couches, 60 min | 4 couches, 26 min | **2 couches**, 15 min |
| carte-08 | 4 couches, 16 min | 4 couches, 9 min | 4 couches, 6 min |
| carte-09 | 6 couches, 23 min | 6 couches, 50 min | **4 couches**, 45 min |
| carte-10 | 4 couches, 43 min | non fini à 65 min | 4 couches, 30 min |

01/10 : 10 cartes sur 10 à 100 %, 0 violation DRC, banc complet en 2 h.

## Ce qui reste ouvert

- carte-09 et carte-10 sont re-placées à 97–98 % quand il reste des erreurs DRC :
  la règle « à partir de 95 %, on ne refait pas le placement » (D-2026-09-29-a)
  ne s'applique aujourd'hui que sans erreur. Décision à prendre.
- Un tirage figé coûte encore 2 à 7 min avant sa coupure.

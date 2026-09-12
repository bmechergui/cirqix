# Référence externe — `astra_piNas`

**Une carte dessinée par un humain, pour ne plus juger nos sorties contre
elles-mêmes.**

Source : <https://github.com/jlcjak/astra_piNas> — porteuse CM5 Lite double NVMe,
commutateur PCIe, Ethernet PoE, USB-C PD. **Six couches**, 176 empreintes.

⚠️ **LA CARTE N'EST PAS VERSIONNÉE ICI.** Le dépôt source ne porte **aucune
licence** : en droit d'auteur, cela signifie « tous droits réservés », pas
« libre d'usage ». On ne verse pas le travail d'autrui dans le nôtre sur la
seule foi qu'il est public. `recuperer.sh` la télécharge à la demande, dans
`input/`, qui est gitignoré.

## Pourquoi cette référence existe

Demande de l'utilisateur le 2026-09-08, après avoir jugé nos placements :
« les cartes ne sont pas pro d'un ingénieur senior ». Un banc qui ne compare que
nos cartes entre elles ne peut pas répondre à ce reproche — il mesure une
dérive, pas un écart à l'état de l'art.

## L'écart, mesuré le 2026-09-08

|  | grille 0,5 mm | paires en série | au dos | couches |
|---|---|---|---|---|
| **référence humaine** | **114 / 176** | **9,8 mm** (max 19) | **12** | **6** |
| carte-09 | 2 / 62 | 55,3 mm (max 101) | 0 | 2 |
| carte-10 | 2 / 70 | 49,5 mm (max 87) | 0 | 2 |
| carte-07 | 2 / 44 | 23,8 mm (max 41) | 0 | 2 |

Une « paire en série » est un net qui ne touche que deux boîtiers de moins de
cinq pastilles — typiquement une LED et sa résistance. C'est la paire la plus
serrable qui existe sur une carte, donc le meilleur révélateur d'un placement.

## Ce que la comparaison établit

1. **La grille.** L'ingénieur en aligne 65 %, nous 3 %. C'est ce qui saute aux
   yeux sur une capture, avant tout raisonnement.
2. **L'adjacence.** 9,8 mm contre 55 — cinq fois pire, et jusqu'à 101 mm.
3. **La face arrière.** Il y pose 12 composants ; nous **zéro sur nos dix-huit
   cartes**. ⚠️ Ce n'est pas un défaut de placement, c'est une CAPACITÉ QUI NOUS
   MANQUE — le distinguo compte, parce qu'aucun réglage du placeur ne le
   corrigera.
4. **Les couches.** La référence en a six. Nos cartes sont toutes à deux, et
   l'escalade `2→4→6→8` n'a jamais servi : nos schémas ne produisent rien qui
   l'exige. Ce n'est donc pas l'escalade qui est en cause, c'est la difficulté
   des cas que nous nous donnons.

⚠️ **Ce que la comparaison N'établit PAS.** La référence est routée à la main
par un concepteur qui connaît son circuit ; nous produisons en quelques minutes
sans intervention. Les deux ne jouent pas au même jeu, et un écart n'est pas un
verdict. Elle sert de CAP, pas de barème.

## Usage

    bash recuperer.sh              # télécharge la carte dans input/
    python ../../scripts/comparer_a_la_reference.py

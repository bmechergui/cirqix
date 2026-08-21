"""Escalade de couches : on commence à 2, on monte tant que le routage échoue.

Le générateur (`tools/pcb.py`) écrit TOUJOURS deux couches cuivre. Freerouting,
lui, route sur autant de couches que le DSN en déclare — vérifié le 2026-08-21 :

    board 2 couches -> DSN ['F.Cu', 'B.Cu']
    board 4 couches -> DSN ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu']

Il n'a donc aucune limite propre : l'empilage est une DONNÉE D'ENTRÉE, décidée
en amont. Jusqu'ici personne ne la décidait — `req.layers` arrivait au service
et n'était que recopié dans la réponse.

Nouveau contrat : `req.layers` est un PLAFOND (celui du plan), pas une consigne.
Le service part de 2 et escalade 4 → 6 → 8 tant que le routage n'est pas
complet, sans jamais dépasser ce plafond.

⚠️ Une carte 4 couches coûte sensiblement plus cher à fabriquer qu'une 2
couches. On monte parce que le routage a ÉCHOUÉ, jamais parce que le plan
l'autorise — le plan plafonne le besoin, il ne le prescrit pas.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _board(couches: list[tuple[int, str]]) -> bytes:
    lignes = ["(kicad_pcb", '\t(version 20260206)', '\t(generator "test")', "\t(layers"]
    for num, nom in couches:
        lignes.append(f'\t\t({num} "{nom}" signal)')
    lignes += [
        '\t\t(36 "B.SilkS" user "B.Silkscreen")',
        '\t\t(44 "Edge.Cuts" user)',
        "\t)",
        '\t(segment (start 0 0) (end 1 1) (width 0.25) (layer "F.Cu") (net 1))',
        ")",
    ]
    return "\n".join(lignes).encode("utf-8")


DEUX = _board([(0, "F.Cu"), (31, "B.Cu")])


class TestEchelle:
    def test_part_de_deux_et_monte_par_paliers(self):
        assert routing_router._layer_ladder(8) == [2, 4, 6, 8]

    def test_ne_depasse_jamais_le_plafond_du_plan(self):
        assert routing_router._layer_ladder(4) == [2, 4]
        assert routing_router._layer_ladder(2) == [2]

    def test_un_plafond_inattendu_ne_fait_pas_exploser(self):
        # Un plafond hors grille (plan corrompu, valeur inconnue) ne doit ni
        # lever ni ouvrir de droits : on retombe sur le minimum.
        assert routing_router._layer_ladder(0) == [2]
        assert routing_router._layer_ladder(3) == [2]


class TestReecritureDeLEmpilage:
    def test_passe_de_deux_a_quatre_couches(self):
        out = routing_router._expand_stackup(DEUX, 4)
        bloc = routing_router._layers_block(out.decode("utf-8"))
        cuivre = re.findall(r'\((\d+) "([A-Za-z0-9.]+\.Cu)"', bloc)
        assert [nom for _, nom in cuivre] == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        # Numérotation KiCad : F.Cu = 0, internes 1..n, B.Cu = 31.
        assert [int(num) for num, _ in cuivre] == [0, 1, 2, 31]

    def test_passe_a_six_couches(self):
        out = routing_router._expand_stackup(DEUX, 6)
        assert routing_router._count_copper_layers(out) == 6

    def test_preserve_les_couches_non_cuivre(self):
        out = routing_router._expand_stackup(DEUX, 4).decode("utf-8")
        assert '"B.SilkS"' in out
        assert '"Edge.Cuts"' in out

    def test_preserve_le_reste_du_fichier(self):
        # Réécrire l'empilage ne doit toucher à rien d'autre : ni les pistes,
        # ni les empreintes, ni les nets.
        out = routing_router._expand_stackup(DEUX, 4).decode("utf-8")
        assert '(segment (start 0 0) (end 1 1)' in out

    def test_ne_retire_jamais_de_couche(self):
        # Descendre casserait les pistes déjà posées sur les couches internes.
        quatre = routing_router._expand_stackup(DEUX, 4)
        assert routing_router._count_copper_layers(
            routing_router._expand_stackup(quatre, 2)
        ) == 4

    def test_un_board_sans_bloc_layers_est_rendu_tel_quel(self):
        brut = b"(kicad_pcb)"
        assert routing_router._expand_stackup(brut, 4) == brut

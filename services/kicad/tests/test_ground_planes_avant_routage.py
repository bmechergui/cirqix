"""Plans de masse coulés AVANT le routage, sur les deux faces extérieures.

Deux défauts corrigés d'un coup.

**1. Le plan arrivait APRÈS le routage.** `handleRouting` appelait
`addGroundPlane` sur le board déjà routé : le routeur n'avait jamais su que le
plan existait, et tirait donc des pistes GND à travers toute la carte au lieu de
relier chaque pad par un moignon. Vérifié le 2026-08-21 : l'export DSN rend bien
la zone sous forme de `(plane GND (polygon B.Cu …))`, donc Freerouting SAIT s'y
raccorder — encore faut-il la lui donner.

**2. Le polygone était dessiné à l'ORIGINE.** La version TypeScript trace
`(xy 0 0) … (xy largeur hauteur)`. Or le contour du board STM32 réel est à
`(gr_rect (start 100 100) (end 160 140))` : le plan tombait **entièrement hors
de la carte**. Un plan hors contour ne relie rien et ne se voit pas.

⚠️ Décision produit (2026-08-21) : les plans vont sur les deux faces
EXTÉRIEURES — `F.Cu` et `B.Cu` — quel que soit le nombre de couches. Sur un
board 4 couches cela donne `GND / SIG / SIG / GND`, un empilage blindé ; les
couches internes restent aux signaux. Le coût assumé est un via par broche de
signal, puisque les composants sont montés sur les faces.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _board(contour: str, gnd: str = '\t(net 3 "GND")') -> bytes:
    return (
        "(kicad_pcb\n"
        '\t(version 20260206)\n'
        "\t(layers\n"
        '\t\t(0 "F.Cu" signal)\n'
        '\t\t(31 "B.Cu" signal)\n'
        '\t\t(44 "Edge.Cuts" user)\n'
        "\t)\n"
        f"{gnd}\n"
        f"{contour}\n"
        ")"
    ).encode("utf-8")


RECT = (
    "\t(gr_rect\n"
    "\t\t(start 100.0 100.0)\n"
    "\t\t(end 160.0 140.0)\n"
    '\t\t(layer "Edge.Cuts")\n'
    "\t)"
)

LIGNES = "\n".join(
    f'\t(gr_line (start {x1} {y1}) (end {x2} {y2}) (layer "Edge.Cuts"))'
    for x1, y1, x2, y2 in [
        (10, 20, 70, 20), (70, 20, 70, 60), (70, 60, 10, 60), (10, 60, 10, 20)
    ]
)


class TestContourDuBoard:
    def test_lit_un_contour_rectangulaire(self):
        assert routing_router._board_outline(_board(RECT)) == (100.0, 100.0, 160.0, 140.0)

    def test_lit_un_contour_en_segments(self):
        assert routing_router._board_outline(_board(LIGNES)) == (10.0, 20.0, 70.0, 60.0)

    def test_sans_contour_ne_devine_pas(self):
        # Un plan place au hasard ne relierait rien. Mieux vaut ne rien couler.
        assert routing_router._board_outline(_board("")) is None


class TestPlansDeMasse:
    def test_coule_sur_les_deux_faces_exterieures(self):
        out = routing_router._add_ground_planes(_board(RECT)).decode("utf-8")
        zones = re.findall(r'\(zone[^\n]*\(layer "([^"]+)"', out)
        assert sorted(zones) == ["B.Cu", "F.Cu"]

    def test_le_polygone_epouse_le_contour_reel(self):
        # LE défaut : un polygone à l'origine tomberait hors de la carte.
        out = routing_router._add_ground_planes(_board(RECT)).decode("utf-8")
        assert "(xy 100" in out and "(xy 160" in out
        assert "(xy 0 0)" not in out

    def test_reste_sur_les_faces_meme_en_quatre_couches(self):
        quatre = routing_router._expand_stackup(_board(RECT), 4)
        out = routing_router._add_ground_planes(quatre).decode("utf-8")
        zones = re.findall(r'\(zone[^\n]*\(layer "([^"]+)"', out)
        assert sorted(zones) == ["B.Cu", "F.Cu"]
        assert "In1.Cu" not in re.findall(r'\(zone[^\n]*\(layer "([^"]+)"', out)

    def test_ne_touche_pas_un_board_sans_gnd(self):
        sans = _board(RECT, gnd='\t(net 1 "VCC")')
        assert routing_router._add_ground_planes(sans) == sans

    def test_n_empile_pas_un_second_plan(self):
        # `kct route` coule lui-même ses zones power : deux remplissages
        # concurrents sur la même couche seraient un conflit, pas une sécurité.
        une_fois = routing_router._add_ground_planes(_board(RECT))
        deux_fois = routing_router._add_ground_planes(une_fois)
        assert deux_fois == une_fois

    def test_reconnait_le_gnd_ecrit_par_kicad_10(self):
        # `(net "GND")` sans numéro — la forme que produit pcbnew 10.
        nomme = _board(RECT, gnd='\t\t(pad "1" smd rect (net "GND"))')
        out = routing_router._add_ground_planes(nomme).decode("utf-8")
        assert '(net_name "GND")' in out


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_les_plans_sont_coules_avant_le_routage(self):
        code = self.SOURCE
        pose = code.index("_add_ground_planes(")
        route = code.index("_route_auto_once(tentative)")
        assert pose < route, (
            "les plans doivent exister AVANT que le routeur reçoive le board — "
            "sinon il route GND en pistes, faute de savoir qu'un plan existe"
        )

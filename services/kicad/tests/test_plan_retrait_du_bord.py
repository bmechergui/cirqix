"""Le plan de masse ne doit pas toucher le bord de la carte.

Mesure du 2026-08-26, banc des cinq cartes. `stm32-baseline` portait trois
erreurs de fabricabilite, toutes de la meme famille :

    Board edge clearance violation
    (board setup constraints edge clearance 0.5000 mm; actual ...)

Le plan etait coule sur la BOITE ENGLOBANTE d Edge.Cuts, sans retrait : son
cuivre arrivait donc au ras du bord. Un fabricant fraise le contour avec une
tolerance, et du cuivre affleurant se retrouve expose ou arrache.

⚠️ Le retrait n est pas cosmetique : `copper_edge_clearance` est une ERREUR, pas
un avertissement. Elle fait refuser la carte.

⚠️ On retire, on ne SUPPRIME pas : un plan absent laisserait GND sans porteur,
et la sequence « le plan prend GND en charge » s effondrerait.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


BOARD = (
    "(kicad_pcb\n\t(version 20240108)\n"
    '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)\n'
    '\t\t(44 "Edge.Cuts" user)\n\t)\n'
    '\t(net 3 "GND")\n'
    '\t(gr_rect (start 100 100) (end 160 140) (layer "Edge.Cuts"))\n'
    '\t(footprint "R" (layer "F.Cu") (at 120 120)\n'
    '\t\t(property "Reference" "R1")\n'
    '\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 3 "GND"))\n'
    "\t)\n)"
).encode("utf-8")


def _polygone(texte: str) -> list[tuple[float, float]]:
    bloc = texte[texte.index("(zone"):]
    return [(float(x), float(y))
            for x, y in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", bloc)]


class TestRetrait:
    def test_le_plan_ne_touche_pas_le_bord(self):
        out = routing_router._add_ground_planes(BOARD).decode("utf-8")
        pts = _polygone(out)
        assert pts, "aucun polygone de plan"
        # Contour : 100..160 en X, 100..140 en Y.
        assert min(x for x, _ in pts) > 100.0
        assert max(x for x, _ in pts) < 160.0
        assert min(y for _, y in pts) > 100.0
        assert max(y for _, y in pts) < 140.0

    def test_le_retrait_vaut_au_moins_la_clearance_exigee(self):
        # `copper_edge_clearance` vaut 0,5 mm par defaut chez KiCad.
        out = routing_router._add_ground_planes(BOARD).decode("utf-8")
        pts = _polygone(out)
        assert min(x for x, _ in pts) >= 100.0 + 0.5
        assert max(x for x, _ in pts) <= 160.0 - 0.5

    def test_le_plan_reste_utile(self):
        # Un retrait excessif viderait la carte de son cuivre : le plan doit
        # couvrir l essentiel de la surface.
        out = routing_router._add_ground_planes(BOARD).decode("utf-8")
        pts = _polygone(out)
        largeur = max(x for x, _ in pts) - min(x for x, _ in pts)
        assert largeur > 55.0, f"plan trop retracte : {largeur} mm pour 60"

    def test_le_plan_existe_toujours(self):
        # On retire, on ne supprime pas : sans plan, GND n a plus de porteur.
        out = routing_router._add_ground_planes(BOARD).decode("utf-8")
        assert "(zone" in out and "GND" in out

"""Recoudre les ILOTS d un meme plan, pas seulement les pastilles orphelines.

Banc du 2026-08-26, carte a 100 composants : les 3 « connexions manquantes »
n etaient pas des pastilles mais trois paires

    Zone [GND] on F.Cu  <->  Zone [GND] on F.Cu

Verifie par l API pcbnew sur ce board :

    zone GND couche F.Cu -> 5 ilots
    zone GND couche B.Cu -> 1 ilot

Les pistes de signal decoupent le plan de la face composants en morceaux que
rien ne relie. Un via pose DANS chaque ilot, vers la face opposee ou le plan est
d un seul tenant, les raccorde tous.

⚠️ La couture existante (`stitch_islands`) ne traite que des PASTILLES isolees.
Elle ne pouvait rien ici : il n y a pas de pastille en cause, seulement du
cuivre coupe.

⚠️ On ne DEVINE pas le point de pose : le centre d une boite englobante tombe
hors d un ilot concave. On echantillonne et on demande au polygone s il contient
le point.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as runner  # noqa: E402

MM = 1_000_000


class TestPointsCandidats:
    def test_les_candidats_couvrent_la_boite(self):
        pts = list(runner._points_dans_boite(0, 0, 10 * MM, 8 * MM, pas=2 * MM))
        assert pts, "aucun candidat"
        assert all(0 <= x <= 10 * MM and 0 <= y <= 8 * MM for x, y in pts)

    def test_le_centre_vient_en_premier(self):
        # Le centre est le meilleur pari sur un ilot convexe — et la plupart le
        # sont. On ne balaie que s il est refuse.
        x, y = next(iter(runner._points_dans_boite(0, 0, 10 * MM, 8 * MM, pas=2 * MM)))
        assert abs(x - 5 * MM) < MM and abs(y - 4 * MM) < MM

    def test_une_boite_minuscule_rend_au_moins_un_point(self):
        assert list(runner._points_dans_boite(0, 0, MM // 10, MM // 10, pas=MM))


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8"
    )

    def test_le_runner_expose_la_couture_de_zones(self):
        assert hasattr(runner, "_stitch_zones")
        assert '"stitch_zones"' in self.SOURCE

    def test_le_point_est_VERIFIE_dans_le_polygone(self):
        # `Contains` est la seule autorite : une boite englobante deborde d un
        # ilot concave, et un via pose dehors ne relierait rien.
        corps = self.SOURCE[self.SOURCE.index("def _stitch_zones(") :]
        corps = corps[: corps.index(chr(10) + "def ")]
        assert "Contains(" in corps

    def test_les_vias_poses_sont_comptes(self):
        corps = self.SOURCE[self.SOURCE.index("def _stitch_zones(") :]
        corps = corps[: corps.index(chr(10) + "def ")]
        assert '"stitched"' in corps

"""La sortie de broche suit l AXE de la pastille, pas le centre du boitier.

Mesure du 2026-08-23, LQFP-48 du board STM32. Ecart entre la direction utilisee
(a l oppose du centre du boitier) et l axe long de la pastille :

    pad 35 : 28,4 deg      pad 47 : 28,4 deg      pad 8 : 10,2 deg

Les DEUX qui echouaient sont les deux a 28 degres hors axe. A ce biais la sortie
entre immediatement dans les pastilles voisines — obstacle mesure a 0,000 mm des
0,8 mm — et aucune distance ni rotation ne la sauve, puisque le blocage est au
MILIEU du trajet, pas a son extremite.

Sur un QFP, le centre du boitier n est une bonne direction que pour la pastille
situee au milieu d un cote. Une patte s echappe perpendiculairement au bord,
c est-a-dire dans le prolongement de sa propre pastille. Le centre ne sert plus
qu a choisir le SENS : vers l exterieur, jamais vers le silicium.

⚠️ L enjeu depasse ces deux pastilles. Sans elles, le repli « re-router en
incluant GND » se declenche et rend leurs pistes aux DIX-HUIT broches GND : on
sacrifie le benefice sur 16 broches parfaitement couvertes par le plan pour
regler 2 cas.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as runner  # noqa: E402

MM = 1_000_000


class _Boite:
    def __init__(self, l, t, r, b):
        self._v = (l, t, r, b)

    def GetLeft(self):
        return self._v[0]

    def GetTop(self):
        return self._v[1]

    def GetRight(self):
        return self._v[2]

    def GetBottom(self):
        return self._v[3]


class _Point:
    def __init__(self, x, y):
        self.x, self.y = x, y


class _Pad:
    def __init__(self, x, y, w, h):
        self._p = _Point(x, y)
        self._b = _Boite(x - w // 2, y - h // 2, x + w // 2, y + h // 2)

    def GetPosition(self):
        return self._p

    def GetBoundingBox(self):
        return self._b


CENTRE = _Point(0, 0)


class TestDirection:
    def test_une_pastille_allongee_en_X_sort_selon_X(self):
        # Pastille a droite du centre, longue en X : sortie vers +X, sans la
        # composante Y qui la ferait entrer dans ses voisines.
        pad = _Pad(5 * MM, 2 * MM, int(1.48 * MM), int(0.30 * MM))
        dx, dy = runner._direction_d_echappement(pad, CENTRE)
        assert dx > 0 and dy == 0.0

    def test_une_pastille_allongee_en_Y_sort_selon_Y(self):
        pad = _Pad(2 * MM, -5 * MM, int(0.30 * MM), int(1.48 * MM))
        dx, dy = runner._direction_d_echappement(pad, CENTRE)
        assert dy < 0 and dx == 0.0

    def test_le_sens_pointe_vers_l_exterieur(self):
        # Jamais vers le silicium : une sortie qui rentre dans le boitier
        # traverserait toutes les autres pattes.
        gauche = _Pad(-5 * MM, 0, int(1.48 * MM), int(0.30 * MM))
        dx, _ = runner._direction_d_echappement(gauche, CENTRE)
        assert dx < 0

    def test_une_pastille_carree_retombe_sur_le_centre(self):
        # Via, THT rond : pas d axe long a suivre. On ne fabrique pas une
        # direction que la geometrie ne donne pas.
        pad = _Pad(3 * MM, 4 * MM, MM, MM)
        dx, dy = runner._direction_d_echappement(pad, CENTRE)
        assert dx == 3 * MM and dy == 4 * MM

    def test_une_pastille_a_peine_allongee_retombe_sur_le_centre(self):
        # 10 % d ecart ne designe pas un axe : sous le seuil, la direction du
        # centre reste le meilleur indice disponible.
        pad = _Pad(3 * MM, 4 * MM, int(1.1 * MM), MM)
        dx, dy = runner._direction_d_echappement(pad, CENTRE)
        assert (dx, dy) == (3 * MM, 4 * MM)


class TestCablage:
    def test_la_pose_utilise_la_direction_du_pad(self):
        source = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
            encoding="utf-8"
        )
        corps = source[source.index("def _escape_pads(") :]
        corps = corps[: corps.index(chr(10) + "def ")]
        assert "_direction_d_echappement(" in corps
        assert "float(pos.x - centre.x)" not in corps, "l ancienne direction subsiste"

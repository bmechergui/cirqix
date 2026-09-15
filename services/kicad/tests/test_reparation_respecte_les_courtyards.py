"""Un composant ramené du bord ne doit jamais atterrir DANS la courtyard d'un voisin.

Mesure du 2026-09-15, run `7980aee1` (prompt « diviseur de tension », après la
marge de 2 mm de D-2026-09-15-a) : arrêté à ROUTING_DONE, DRC

    courtyards_overlap   Footprint R1 <-> Footprint J1

pcbnew : R1 courtyard y 100,92..102,47, J1 courtyard y ..101,86 — 0,94 mm de
recouvrement. Leurs CENTRES sont pourtant à 4,34 mm : `_nearest_free_cell`
jugeait une case libre à plus de 2,5 mm des CENTRES occupés, sans regarder la
taille des boîtiers. Un connecteur 2,54 mm porte sa courtyard à 6 mm de son
centre. Et comme la réparation ANCRE ce qu'elle rentre (sinon l'Inspecteur le
ressort) et que J1 est ancré aussi, plus rien ne pouvait les séparer : quatre
tirages, quatre échecs.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

from tools import placement as P  # noqa: E402

BORNES = (0.0, 10.66, 0.0, 23.44)
# Géométrie du run 7980aee1, dans le repère du board (contour à gauche/haut = 0).
J1 = (3.24, 3.01, 6.86, 9.18)          # courtyard du connecteur 1x02
BOITE_0603 = (-1.52, -0.78, 1.52, 0.77)  # courtyard locale de R1


def _chevauchent(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _boite_en(centre, locale):
    return (centre[0] + locale[0], centre[1] + locale[1], centre[0] + locale[2], centre[1] + locale[3])


class TestCaseLibreParCourtyard:
    def test_une_case_dont_la_courtyard_recouvre_un_voisin_n_est_pas_libre(self):
        # La cible du run : juste sous J1, centre à 4,3 mm du sien — « libre »
        # pour l'ancienne règle des centres.
        cible = (6.1, 9.0)
        case = P._nearest_free_cell(cible, [], (2.0, 8.6, 2.0, 21.4),
                                    boite_locale=BOITE_0603, boites_occupees=[J1])
        assert case is not None
        assert not _chevauchent(_boite_en(case, BOITE_0603), J1)

    def test_une_case_deja_libre_est_gardee(self):
        cible = (5.0, 15.0)
        assert P._nearest_free_cell(cible, [], (2.0, 8.6, 2.0, 21.4),
                                    boite_locale=BOITE_0603, boites_occupees=[J1]) == cible

    def test_sans_boites_l_ancienne_regle_des_centres_reste(self):
        # Compatibilité : les appelants qui ne donnent pas de boîtes gardent
        # la distance entre centres.
        assert P._nearest_free_cell((5.0, 5.0), [(5.0, 5.0)], (0.0, 20.0, 0.0, 20.0)) != (5.0, 5.0)

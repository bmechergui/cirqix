"""Un secours GND perdu d'avance ne reçoit pas les réparations locales.

Mesure du 2026-10-01, carte-07 : le repli global rendait un secours à
57 connexions manquantes contre 1 pour le board gardé ; il recevait quand même
~5 min de réparations locales (qui ne relient que des broches GND) avant
d'être refusé.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402


def test_secours_perdu_n_est_pas_repare():
    assert not R._secours_peut_gagner((0, 1), (0, 57), orphelines=1)


def test_secours_proche_est_repare():
    assert R._secours_peut_gagner((0, 1), (0, 2), orphelines=1)
    assert R._secours_peut_gagner((0, 3), (0, 1), orphelines=2)


def test_sans_verdict_on_ne_paie_rien():
    assert not R._secours_peut_gagner(None, (0, 1), 1)
    assert not R._secours_peut_gagner((0, 1), None, 1)


def test_route_auto_consulte_la_regle_avant_de_reparer_le_secours():
    src = inspect.getsource(R.route_auto)
    regle = src.index("_secours_peut_gagner(avant, brut")
    assert regle < src.index("secours = _reparations_locales_gnd(secours)")

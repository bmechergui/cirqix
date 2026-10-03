"""Les finitions sont réservées aux tirages qui peuvent gagner (validé le 2026-10-01).

Banc des dix cartes du jour : les finitions font 50 % du temps de routage, y
compris sur des tirages ensuite écartés (carte-10 : un 66 % à 6 couches a reçu
139 s de finitions après un 83 %).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402


def _res(pct, board="B", skipped=False):
    return R.RouteAutoResponse(kicad_pcb_b64=board, routed_percent=pct, layers=4,
                               skipped=skipped)


def test_le_premier_tirage_est_toujours_fini():
    assert not R._finitions_inutiles(_res(40), None)


def test_un_tirage_battu_et_loin_n_est_pas_fini():
    assert R._finitions_inutiles(_res(66), _res(83))
    assert not R._finitions_inutiles(_res(83), _res(83)), "marge d un point"
    assert R._finitions_inutiles(_res(81), _res(83))


def test_un_tirage_a_portee_ou_meilleur_est_fini():
    assert not R._finitions_inutiles(_res(97), _res(99))
    assert not R._finitions_inutiles(_res(90), _res(83))


def test_route_auto_consulte_la_regle_avant_les_finitions():
    src = inspect.getsource(R.route_auto)
    regle = src.index("if _finitions_inutiles(res, meilleur):")
    assert src.index("t_finitions = time.time()") < regle
    assert regle < src.index("_reposer_vias_reserves(")

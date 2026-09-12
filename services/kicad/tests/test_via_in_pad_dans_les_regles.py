"""Un via-in-pad qui tient dans la pastille mais pas dans les REGLES du board
n est pas un via. carte-08, 2026-09-12 : chaque via retreci a 0,3-0,5 mm
recevait un percage plancher de 0,3 mm -> anneau nul, `annular_width` a chaque
repose et chaque fanout, tous refuses par la garde."""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import routing_pcbnew_runner as RUN  # noqa: E402


class _DS:
    m_MinThroughDrill = 300_000
    m_ViasMinAnnularWidth = 150_000
    m_ViasMinSize = 400_000


class _Board:
    def GetDesignSettings(self):
        return _DS()


def test_le_via_minimal_vient_des_regles_du_board():
    assert RUN._via_min_fabricable(_Board()) == 600_000  # 0,3 + 2 x 0,15


def test_sans_regles_lisibles_le_plancher_historique_subsiste():
    assert RUN._via_min_fabricable(object()) == RUN._VIA_MIN_MM


def test_un_via_sous_le_minimum_fabricable_est_refuse():
    # pastille de 0,45 mm : un via de 0,45 y tiendrait, mais 0,45 < 0,60.
    assert RUN._via_in_pad_possible(450_000, 600_000, 0, via_min=600_000) == 0.0
    assert RUN._via_in_pad_possible(900_000, 600_000, 0, via_min=600_000) == 600_000


def test_les_deux_sites_passent_le_minimum_du_board():
    src = (_SERVICE / "tools" / "routing_pcbnew_runner.py").read_text(encoding="utf-8")
    assert src.count("_via_in_pad_possible(larg, via_d, perce, _via_min_fabricable(board))") == 2

"""Chaque palier garde ses trois tirages (D-2026-10-03-b, validee).

Remplace la regle du 2026-08-29 qui abandonnait les tirages restants d un palier
des que le meilleur etait sous 80 % (`_tirages_epuises_au_palier`). Mesure du
2026-10-03, stm32-30 : un seul tirage a 4 couches, 74 %, a suffi a sauter le
palier — alors que l ecart mesure entre deux tirages Freerouting sur le meme
board atteint 26 points (65, 77 et 91 % sur la Nucleo). La carte est sortie a
96 %. Le budget de stm32-100, que l ancienne regle protegeait, l est desormais
par la coupure de stagnation et par les replis bornes (60 s).
"""
from __future__ import annotations

import inspect

from routers import routing as R


def test_la_regle_d_abandon_n_existe_plus():
    assert not hasattr(R, "_tirages_epuises_au_palier")
    src = inspect.getsource(R.route_auto)
    assert "tirages restants a %d couches abandonnes" not in src


def test_trois_tirages_par_palier():
    assert R._TIRAGES_ROUTAGE_PAR_PALIER == 3

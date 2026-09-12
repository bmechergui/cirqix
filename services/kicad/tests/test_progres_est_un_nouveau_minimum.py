"""L horloge « sans progres » ne repart que sur un NOUVEAU MINIMUM de nets
non routes, jamais sur un simple changement.

Mesure du 2026-09-12 (stm32-100, palier 4 couches) : le routeur oscillait
entre 1 et 2 non routes — 200 changements en 35 minutes, jamais mieux que 1.
Chaque changement remettait l horloge a zero ; le plafond de 300 s n a
jamais tire et le tirage a consomme tout le budget.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


def test_la_premiere_mesure_compte():
    assert R._nouveau_minimum(2, 0)


def test_descendre_sous_le_meilleur_compte():
    assert R._nouveau_minimum(1, 2)


def test_remonter_puis_redescendre_ne_compte_pas():
    assert not R._nouveau_minimum(2, 1)
    assert not R._nouveau_minimum(1, 1)


def test_un_compte_inconnu_ne_compte_pas():
    assert not R._nouveau_minimum(0, 3)


def test_la_boucle_de_sondage_s_en_sert():
    src = (_SERVICE / "routers" / "routing.py").read_text(encoding="utf-8")
    assert "if _nouveau_minimum(unrouted, dernier_unrouted):" in src
    assert "unrouted != dernier_unrouted" not in src


def test_l_oscillation_1_2_finit_par_couper():
    # Rejoue la regle sur une serie 2,1,2,1,... : apres la premiere descente
    # a 1, aucune remise a zero ; le temps sans progres depasse le plafond.
    dernier, horloge = 0, 0.0
    for i, u in enumerate([2, 1, 2, 1, 2, 1] * 60):
        if R._nouveau_minimum(u, dernier):
            dernier, horloge = u, 0.0
        else:
            horloge += 5.0
    assert dernier == 1
    assert R._faut_couper(0, 0, False, sans_progres_s=R._temps_sans_progres(dernier > 0, horloge))

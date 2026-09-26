"""Un connecteur ancre est TOUJOURS pose contre un bord.

⚠️ Rejeu du 2026-09-21, carte-09 compacte (58,7 x 45,1) : six connecteurs a
2-3 mm d un bord, et J2 a 15,7 mm — en plein milieu. Le generateur l avait pose
a (35, 20), DANS la carte : `_clamp_fixed_refs_to_outline` ne ramene que ce qui
DEBORDE, et un ancrage n est plus jamais deplace ensuite. Rien ne faisait donc
respecter la regle de l utilisateur : « toujours les connecteurs a l extremite ».

REGLE (aucune carte nommee, aucun seuil) : chaque ancrage glisse vers le bord
LE PLUS PROCHE de son corps, jusqu a la marge du clamp ; s il y heurte un autre
ancrage, il glisse LE LONG de ce bord. Un boitier dominant (module centre) en
est exempt. ⚠️ Ce n est PAS D-2026-09-13-c (B), refutee : on ne CENTRE rien.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools import placement as P  # noqa: E402

BORNES = (2.0, 56.7, 2.0, 43.1)            # contour 58,7 x 45,1 moins la marge
EN_TETE = (-1.8, -1.8, 1.8, 9.4)           # 1x04, origine sur la pastille 1


class TestPositionAuBord:
    def test_le_cas_mesure_part_vers_le_bord_le_plus_proche(self):
        x, y = P._position_au_bord((35.0, 20.0), EN_TETE, BORNES, [])
        assert (x, y) == pytest.approx((35.0, 33.7))     # bas : 13,7 mm, le plus court
        assert y + EN_TETE[3] == pytest.approx(BORNES[3])

    def test_deja_au_bord_ne_bouge_pas(self):
        assert P._position_au_bord((3.8, 20.0), EN_TETE, BORNES, []) == pytest.approx((3.8, 20.0))

    def test_glisse_le_long_du_bord_si_un_ancrage_l_occupe(self):
        occupant = (33.0, 31.0, 37.0, 43.5)
        x, y = P._position_au_bord((35.0, 20.0), EN_TETE, BORNES, [occupant])
        assert y == pytest.approx(33.7), "reste contre le meme bord"
        assert not P._boites_se_recouvrent(
            (x + EN_TETE[0], y + EN_TETE[1], x + EN_TETE[2], y + EN_TETE[3]), occupant)

    def test_piece_plus_grande_que_la_carte_inchangee(self):
        assert P._position_au_bord((5.0, 5.0), (-40, -40, 40, 40), BORNES, []) == (5.0, 5.0)


class TestCablage:
    SOURCE = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_appele_juste_apres_le_clamp_avant_l_optimisation(self):
        clamp = self.SOURCE.index("_clamp_fixed_refs_to_outline(pcb, conn, exempts=dominants)")
        colle = self.SOURCE.index("_coller_les_ancrages_au_bord(pcb, conn, exempts=dominants")
        optim = self.SOURCE.index("OptimizationWorkflow(", colle)
        assert clamp < colle < optim

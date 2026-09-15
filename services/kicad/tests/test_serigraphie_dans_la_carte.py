"""Une référence de sérigraphie ne doit jamais être posée au-delà du bord de la carte.

Mesure du 2026-09-15 : 5 runs du prompt « diviseur de tension » par la file,
5 livrés — mais 2 portent `silk_edge_clearance` (« Silkscreen clipped by board
edge »). Sur les deux boards, c'est la MÊME cause, lue au DRC :

    Reference field of R2      texte y 92,22..93,92 · bord de la carte à y 92,45

La courtyard de R2 commence à 93,72 : le composant est dans la carte. C'est
`degager_references` qui a posé son TEXTE au-dessus, parce que ses obstacles
sont les pastilles, les contours de sérigraphie et les autres références —
jamais le contour de la carte. Une place hors carte était « libre ».
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import serigraphie as S  # noqa: E402


class _Texte:
    def __init__(self, position, hauteur=1.0):
        self.position, self.font_height = position, hauteur
        self.text_type, self.layer, self.hidden = "reference", "F.SilkS", False


class _Pad:
    def __init__(self, position, size):
        self.position, self.size = position, size


class _Fp:
    def __init__(self, reference, position, texte, pads=()):
        self.reference, self.position = reference, position
        self.texts, self.pads, self.rotation, self.graphics = [texte], list(pads), 0.0, []


class _Trait:
    def __init__(self, start, end):
        self.layer, self.start, self.end = "Edge.Cuts", start, end


class _Pcb:
    """Carte de 20 x 20 mm, origine en (100, 100) comme les boards du service."""

    def __init__(self, footprints):
        self.footprints = footprints
        self.board_origin = (100.0, 100.0)
        self.graphic_items = [
            _Trait((100.0, 100.0), (120.0, 100.0)), _Trait((120.0, 100.0), (120.0, 120.0)),
            _Trait((120.0, 120.0), (100.0, 120.0)), _Trait((100.0, 120.0), (100.0, 100.0)),
        ]

    def move_reference(self, reference, absolute=None, **_):
        for fp in self.footprints:
            if fp.reference == reference:
                fp.texts[0].position = absolute
                return True
        return False


def _dans_la_carte(boite, marge=0.0):
    return boite[0] >= marge and boite[1] >= marge and boite[2] <= 20 - marge and boite[3] <= 20 - marge


class TestReferenceAuBord:
    def test_une_reference_qui_deborde_est_ramenee_dans_la_carte(self):
        # R2 comme sur les boards mesurés : composant dans la carte, pastilles
        # à 1,5 mm du bord haut, texte posé au-dessus — donc dehors.
        r2 = _Fp("R2", (10.0, 1.2), _Texte((0.0, -1.43)),
                 pads=[_Pad((-0.8, 0.0), (0.8, 0.9)), _Pad((0.8, 0.0), (0.8, 0.9))])
        pcb = _Pcb([r2])
        assert not _dans_la_carte(S.boites_des_references(pcb)["R2"])

        assert S.degager_references(pcb) == 1
        assert _dans_la_carte(S.boites_des_references(pcb)["R2"], marge=S._MARGE_BORD_MM)

    def test_aucune_reference_n_est_DEPLACEE_hors_de_la_carte(self):
        # Deux références empilées dans le coin : chacune doit bouger, mais la
        # plupart des places « libres » des anneaux proches sont dehors. Toute
        # référence DÉPLACÉE doit finir dans la carte ; celle qui ne trouve
        # aucune place reste où elle est (règle d'origine : on ne déplace pas
        # au hasard).
        r1 = _Fp("R1", (0.6, 0.6), _Texte((0.0, 0.0)))
        voisin = _Fp("R9", (0.6, 0.6), _Texte((0.0, 0.0)))
        pcb = _Pcb([r1, voisin])
        assert S.degager_references(pcb) >= 1
        for fp in pcb.footprints:
            if fp.texts[0].position != (0.0, 0.0):
                assert _dans_la_carte(S.boites_des_references(pcb)[fp.reference], marge=S._MARGE_BORD_MM)

    def test_une_reference_bien_placee_ne_bouge_pas(self):
        r3 = _Fp("R3", (10.0, 10.0), _Texte((0.0, -1.43)))
        pcb = _Pcb([r3])
        assert S.degager_references(pcb) == 0
        assert r3.texts[0].position == (0.0, -1.43)


class TestSansContour:
    def test_un_board_sans_contour_lisible_garde_l_ancien_comportement(self):
        class _PcbNu:
            def __init__(self, fps):
                self.footprints = fps

            def move_reference(self, *a, **k):
                return False

        pcb = _PcbNu([_Fp("R1", (0.1, 0.1), _Texte((0.0, 0.0)))])
        # Pas de contour : aucune contrainte de bord, et surtout pas d'exception.
        assert S.degager_references(pcb) == 0

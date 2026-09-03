"""Quand un boitier domine la carte, on PLACE au lieu d optimiser.

Mesure du 2026-08-27, ESP32 du banc : les QUATRE tirages de
`OptimizationWorkflow` produisent des conflits de courtyard. Ce n est pas de la
malchance — c est structurel. Un algorithme genetique optimise une longueur de
fil totale qu un boitier de 2000 mm2 domine entierement ; les 19 passifs
deviennent du bruit dans sa fonction de cout, et il les tasse contre lui.

Un concepteur ne procede pas ainsi. Il pose le module, puis dispose les passifs
autour, en couronne. C est ce que fait ce placement : deterministe, sans tirage,
donc reproductible.

⚠️ Il ne remplace PAS l optimiseur : sur une carte sans boitier dominant, le
genetique fait mieux — il groupe les decouplages avec leur IC, ce qu une grille
ignore. On ne bascule que sur le cas ou il echoue.

⚠️ Les composants restent DANS le contour. Un passif pousse dehors serait
inroutable — on aurait echange un chevauchement contre un defaut pire.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import placement as P  # noqa: E402


class _Pad:
    def __init__(self, x, y):
        self.position = (x, y)


class _Fp:
    def __init__(self, ref, x, y, demi_l, demi_h):
        self.reference = ref
        self.position = (x, y)
        self.pads = [_Pad(x - demi_l, y - demi_h), _Pad(x + demi_l, y + demi_h)]
        self.graphics = []


class _Pcb:
    def __init__(self, fps, taille=(100.0, 80.0)):
        self.footprints = fps
        self.board_size = taille
        self.board_origin = (0.0, 0.0)


def _module_et_passifs(n=12):
    u1 = _Fp("U1", 0, 0, 20, 22.5)          # 40 x 45 mm
    passifs = [_Fp(f"R{i}", 0, 0, 0.8, 1.5) for i in range(1, n + 1)]
    return _Pcb([u1, *passifs])


class TestCouronne:
    def test_le_module_est_au_centre(self):
        pcb = _module_et_passifs()
        P._placer_en_couronne(pcb, ["U1"])
        u1 = next(f for f in pcb.footprints if f.reference == "U1")
        assert abs(u1.position[0] - 50.0) < 1.0
        assert abs(u1.position[1] - 40.0) < 1.0

    def test_aucun_passif_ne_chevauche_le_module(self):
        pcb = _module_et_passifs()
        P._placer_en_couronne(pcb, ["U1"])
        u1 = next(f for f in pcb.footprints if f.reference == "U1")
        dl, dh = (v / 2 for v in P._encombrement_fp(u1))
        for fp in pcb.footprints:
            if fp.reference == "U1":
                continue
            x, y = fp.position
            assert abs(x - u1.position[0]) > dl or abs(y - u1.position[1]) > dh, (
                f"{fp.reference} sur le module")

    def test_les_passifs_ne_se_superposent_pas_entre_eux(self):
        pcb = _module_et_passifs()
        P._placer_en_couronne(pcb, ["U1"])
        pos = [f.position for f in pcb.footprints if f.reference != "U1"]
        assert len(set(pos)) == len(pos), "deux passifs au meme point"

    def test_tout_reste_dans_le_contour(self):
        pcb = _module_et_passifs(20)
        P._placer_en_couronne(pcb, ["U1"])
        for fp in pcb.footprints:
            x, y = fp.position
            assert 0.0 <= x <= 100.0 and 0.0 <= y <= 80.0, f"{fp.reference} hors carte"

    def test_le_placement_est_REPRODUCTIBLE(self):
        # C est tout l interet face au genetique : deux appels, meme resultat.
        a, b = _module_et_passifs(), _module_et_passifs()
        P._placer_en_couronne(a, ["U1"])
        P._placer_en_couronne(b, ["U1"])
        assert [f.position for f in a.footprints] == [f.position for f in b.footprints]

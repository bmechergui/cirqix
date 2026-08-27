"""Rien ne se pose SUR un boitier dominant ancre.

Mesure du 2026-08-27, ESP32 du banc. Apres avoir centre et ancre le module, il
restait trois erreurs, toutes de la meme forme :

    Courtyards overlap : D1 / U1
    Courtyards overlap : R1 / U1
    Courtyards overlap : R6 / U1

Trois passifs poses PAR-DESSUS le module. `PlacementFixer` ne les ecarte pas :
sa reparation locale deplace de proche en proche, et un boitier de 2000 mm2 ne
lui laisse aucun voisinage libre ou glisser.

Un composant ancre occupe une surface INTERDITE aux autres. On pousse donc les
mobiles hors de son emprise, dans la direction qui les en sort le plus vite.

⚠️ On ne deplace QUE les mobiles. Pousser un ancre annulerait l ancrage — et
deux ancres qui se chevauchent relevent de `_position_libre_pour_ancrage`, pas
d ici.
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


class _Pcb:
    def __init__(self, fps, taille=(100.0, 80.0)):
        self.footprints = fps
        self.board_size = taille
        self.board_origin = (0.0, 0.0)


def _dans(fp, dominant) -> bool:
    dl, dh = P._encombrement_fp(dominant)
    dx = abs(fp.position[0] - dominant.position[0])
    dy = abs(fp.position[1] - dominant.position[1])
    return dx < dl / 2 and dy < dh / 2


class TestEcartement:
    def test_un_passif_pose_sur_le_module_est_ecarte(self):
        u1 = _Fp("U1", 50, 40, 20, 22.5)
        r1 = _Fp("R1", 52, 41, 0.8, 1.5)   # en plein dedans
        pcb = _Pcb([u1, r1])
        P._ecarter_des_dominants(pcb, ["U1"])
        assert not _dans(r1, u1), f"R1 toujours sur U1 : {r1.position}"

    def test_un_passif_deja_dehors_ne_bouge_pas(self):
        u1 = _Fp("U1", 50, 40, 20, 22.5)
        r1 = _Fp("R1", 90, 10, 0.8, 1.5)
        avant = r1.position
        P._ecarter_des_dominants(_Pcb([u1, r1]), ["U1"])
        assert r1.position == avant

    def test_le_dominant_lui_meme_ne_bouge_pas(self):
        # Le pousser annulerait l ancrage qu on vient de poser.
        u1 = _Fp("U1", 50, 40, 20, 22.5)
        avant = u1.position
        P._ecarter_des_dominants(_Pcb([u1]), ["U1"])
        assert u1.position == avant

    def test_les_ecartes_restent_dans_la_carte(self):
        # Un composant pousse hors du contour serait inroutable — on aurait
        # echange un chevauchement contre un defaut pire.
        u1 = _Fp("U1", 50, 40, 20, 22.5)
        passifs = [_Fp(f"R{i}", 50 + i * 0.5, 40, 0.8, 1.5) for i in range(1, 6)]
        pcb = _Pcb([u1, *passifs])
        P._ecarter_des_dominants(pcb, ["U1"])
        for fp in passifs:
            x, y = fp.position
            assert 0.0 <= x <= 100.0 and 0.0 <= y <= 80.0, f"{fp.reference} hors carte"

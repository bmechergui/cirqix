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
    """⚠️ Pastilles en coordonnees LOCALES, comme le vrai `PCB` les donne.

    La fixture les posait en ABSOLU (`x ± demi`). Tant qu on ne lisait que la
    TAILLE (`max - min`), le decalage s annulait et le mensonge ne coutait
    rien. Des qu on a lu la BOITE — pour corriger les courtyards decales — la
    fixture a fait echouer un code juste : elle reproduisait l hypothese de
    l appelant, pas la realite du modele.
    """

    def __init__(self, ref, x, y, demi_l, demi_h):
        self.reference = ref
        self.position = (x, y)
        self.pads = [_Pad(-demi_l, -demi_h), _Pad(demi_l, demi_h)]


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


class TestEncombrementReel:
    """L encombrement se mesure sur le COURTYARD, pas sur les pastilles.

    Mesure du 2026-08-27, ESP32-WROOM :

        etendue des pastilles : 17,5 x 17,8 mm
        courtyard reel        : 41,3 x 48,1 mm

    Le corps du module deborde largement ses pastilles. En prenant l etendue des
    pastilles, `_ecarter_des_dominants` poussait les passifs hors d une boite
    DEUX FOIS trop petite — ils retombaient sur le module, et les
    `courtyards_overlap` subsistaient jusque dans le meilleur de trois tirages
    (5 erreurs residuelles).

    Le courtyard est la surface que le fabricant reserve : c est la bonne
    mesure, et c est celle que le DRC compare.
    """

    class _G:
        def __init__(self, layer, start, end):
            self.layer, self.start, self.end = layer, start, end

    def test_le_courtyard_prime_sur_les_pastilles(self):
        fp = _Fp("U1", 0, 0, 5, 5)  # pastilles : 10 x 10
        fp.graphics = [self._G("F.CrtYd", (-20, -24), (20, 24))]
        l, h = P._encombrement_fp(fp)
        assert l > 30 and h > 40, f"courtyard ignore : {l} x {h}"

    def test_sans_courtyard_on_retombe_sur_les_pastilles(self):
        # Une empreinte sans courtyard declare ne doit pas rendre 0 : on
        # perdrait toute protection.
        fp = _Fp("R1", 0, 0, 0.8, 1.5)
        fp.graphics = [self._G("F.SilkS", (-1, -1), (1, 1))]
        l, h = P._encombrement_fp(fp)
        assert l > 0 and h > 0

    def test_les_couches_non_courtyard_sont_ignorees(self):
        # La serigraphie deborde souvent : la prendre gonflerait l emprise sans
        # raison et ecarterait des composants qui tiennent.
        fp = _Fp("R1", 0, 0, 0.8, 1.5)
        fp.graphics = [self._G("F.SilkS", (-50, -50), (50, 50))]
        l, h = P._encombrement_fp(fp)
        assert l < 10 and h < 10, f"serigraphie prise pour un courtyard : {l} x {h}"

"""Un boitier qui occupe une part notable de la carte se POSE, il ne se tire pas.

Mesure du 2026-08-26, ESP32 du banc. Meme sur une carte de 93 x 70 mm — ou son
courtyard de 41 x 48 tient largement — le placement rendait :

    courtyards_overlap    9
    shorting_items        8
    pth_inside_courtyard  2

`OptimizationWorkflow` place le module puis empile les passifs par-dessus, et
`PlacementFixer` n y parvient pas : deplacer un boitier de 2000 mm2 demande de
deplacer tout le reste, ce que la reparation locale ne fait pas.

Un module dominant n a pas a etre deplace par un algorithme genetique. On le
CENTRE puis on l ANCRE, comme les connecteurs — et les passifs s organisent
autour. C est aussi ce que fait un concepteur.

⚠️ Le seuil porte sur la SURFACE relative, pas sur le nombre de broches : un
LQFP-48 de 9 x 9 mm sur une carte de 100 mm n a rien de dominant, et l ancrer
priverait l optimiseur d un degre de liberte utile. `_dense_part_refs` (>= 16
pads) repond a une autre question — le canal d escape — et ne convient pas ici.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import placement as P  # noqa: E402

NL = chr(10)


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


class TestDetection:
    def test_un_module_qui_mange_la_carte_est_dominant(self):
        # 40 x 45 mm sur 100 x 80 = 22 % de la surface.
        pcb = _Pcb([_Fp("U1", 50, 40, 20, 22.5), _Fp("R1", 10, 10, 0.8, 1.5)])
        assert P._boitiers_dominants(pcb) == ["U1"]

    def test_un_LQFP_sur_une_grande_carte_ne_l_est_pas(self):
        # 9 x 9 mm sur 100 x 80 = 1 %. L ancrer priverait l optimiseur d un
        # degre de liberte utile.
        pcb = _Pcb([_Fp("U1", 50, 40, 4.5, 4.5), _Fp("R1", 10, 10, 0.8, 1.5)])
        assert P._boitiers_dominants(pcb) == []

    def test_une_carte_sans_taille_ne_rend_rien(self):
        # Sans surface de reference, « dominant » n a pas de sens : on ne
        # devine pas.
        pcb = _Pcb([_Fp("U1", 50, 40, 20, 22.5)], taille=(0.0, 0.0))
        assert P._boitiers_dominants(pcb) == []


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_les_dominants_rejoignent_les_ancrages(self):
        corps = self.SOURCE[self.SOURCE.index("def auto_place(") :]
        i = corps.index("_boitiers_dominants(")
        j = corps.index("fixed_refs=")
        assert i < j, "les dominants doivent etre ancres AVANT l optimisation"

    def test_le_dominant_est_centre_avant_d_etre_ancre(self):
        # L ancrer la ou `gen_pcb` l a laisse figerait un mauvais placement.
        corps = self.SOURCE[self.SOURCE.index("def auto_place(") :]
        assert "_centrer(" in corps


class TestExemptionAntiCollision:
    """Un boitier dominant n est pas pousse par la garde anti-superposition.

    Mesure du 2026-08-27 : le module ESP32, centre a 46,5 mm sur une carte de
    93 mm, se retrouvait a **82** — soit un debordement de 9,6 mm hors du bord
    droit. Les passifs le chevauchaient parce qu il n etait pas ou on croyait
    l avoir mis.

    La cause : deux correctifs qui se combattent. `_centrer` le pose au milieu,
    puis `_position_libre_pour_ancrage` — ecrite pour empecher DEUX CONNECTEURS
    de se superposer — constate qu un boitier de 41 x 48 mm chevauche a peu pres
    tout, et le pousse au bord.

    Un dominant chevauche FORCEMENT ses voisins au moment ou on le pose. C est
    aux voisins de s ecarter.
    """

    def _pcb_reel(self):
        from kicad_tools.schema.pcb import PCB

        def fp(ref, x, y, demi):
            pads = NL.join(
                '\t\t(pad "%d" smd rect (at %s %s) (size 1 1) '
                '(layers "F.Cu") (net 3 "GND"))' % (i, s * demi, s * demi)
                for i, s in enumerate((-1, 1), start=1)
            )
            return NL.join([
                '\t(footprint "F" (layer "F.Cu")',
                "\t\t(at %s %s)" % (x, y),
                '\t\t(fp_text reference "%s" (at 0 0) (layer "F.SilkS"))' % ref,
                pads,
                "\t)",
            ])

        texte = NL.join([
            "(kicad_pcb",
            "\t(version 20240108)",
            "\t(layers",
            '\t\t(0 "F.Cu" signal)',
            '\t\t(44 "Edge.Cuts" user)',
            "\t)",
            '\t(net 3 "GND")',
            '\t(gr_rect (start 100 100) (end 193 170) (layer "Edge.Cuts"))',
            fp("U1", 146, 135, 20),
            fp("R1", 145, 134, 1),
            ")",
        ])
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "b.kicad_pcb"
            f.write_text(texte, encoding="utf-8")
            return PCB.load(str(f))

    def test_un_dominant_reste_ou_on_l_a_centre(self):
        pcb = self._pcb_reel()
        u1 = next(f for f in pcb.footprints if f.reference == "U1")
        avant = u1.position
        P._clamp_fixed_refs_to_outline(pcb, ["U1", "R1"], exempts=["U1"])
        assert u1.position == avant, (
            "le dominant a ete pousse : %s -> %s" % (avant, u1.position))

"""Des pastilles de MEME NUMERO sont le meme noeud : elles portent le meme net.

Trouve le 2026-08-27 en cherchant l origine de huit `shorting_items` sur
l ESP32 du banc :

    Pad 39 [+3V3]     of U1 on F.Cu
    Pad 39 [<no net>] of U1 on F.Cu

Mesure sur le board rendu :

    U1 porte 60 pastilles
    le numero « 39 » apparait 22 fois
    21 de ces 22 n ont AUCUN net

C est le pave thermique du module et ses 21 vias. KiCad exprime un noeud reparti
par des pastilles de meme numero — c est la definition meme. Notre generation
n attribuait le net qu a UNE d entre elles ; les autres restaient du cuivre sans
nom, que le plan de masse vient toucher.

⚠️ Le defaut n a rien de propre a l ESP32 : tout boitier a pave thermique est
concerne — QFN, DFN, modules RF, regulateurs de puissance. C est pour cela que
la reparation vit au niveau du BOARD et pas dans un cas particulier.

⚠️ On PROPAGE, on n invente pas : une pastille sans net dont aucune homonyme
n en porte reste sans net. Une broche non connectee doit le rester.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import pcb as pcb_tools  # noqa: E402


def _board(pads: str) -> str:
    return (
        "(kicad_pcb\n"
        '\t(net 0 "")\n\t(net 3 "GND")\n'
        '\t(footprint "M" (layer "F.Cu")\n'
        '\t\t(property "Reference" "U1")\n'
        f"{pads}\n"
        "\t)\n)"
    )


AVEC = '\t\t(pad "39" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 3 "GND"))'
SANS = '\t\t(pad "39" thru_hole circle (at 1 1) (size 0.6 0.6) (layers "*.Cu"))'
AUTRE = '\t\t(pad "12" smd rect (at 5 5) (size 1 1) (layers "F.Cu"))'


class TestPropagation:
    def test_le_net_gagne_les_homonymes(self):
        out = pcb_tools.propager_nets_pastilles_homonymes(_board(AVEC + "\n" + SANS))
        # Les DEUX pastilles 39 portent desormais GND.
        assert out.count('"GND"') >= 3  # declaration + deux pastilles

    def test_une_pastille_sans_homonyme_reste_sans_net(self):
        # On propage, on n invente pas : une broche non connectee le reste.
        out = pcb_tools.propager_nets_pastilles_homonymes(_board(AVEC + "\n" + AUTRE))
        bloc12 = out[out.index('(pad "12"'):]
        assert "(net " not in bloc12[:bloc12.index(")\n")]

    def test_un_board_deja_complet_n_est_pas_touche(self):
        entree = _board(AVEC)
        assert pcb_tools.propager_nets_pastilles_homonymes(entree) == entree

    def test_les_footprints_ne_se_contaminent_pas(self):
        # Deux boitiers peuvent avoir chacun une pastille « 39 » sur des nets
        # differents : propager entre eux serait un court-circuit.
        deux = (
            "(kicad_pcb\n"
            '\t(net 3 "GND")\n\t(net 4 "VCC")\n'
            '\t(footprint "A" (property "Reference" "U1")\n'
            '\t\t(pad "39" smd rect (net 3 "GND"))\n'
            '\t\t(pad "39" smd rect)\n\t)\n'
            '\t(footprint "B" (property "Reference" "U2")\n'
            '\t\t(pad "39" smd rect (net 4 "VCC"))\n\t)\n)'
        )
        out = pcb_tools.propager_nets_pastilles_homonymes(deux)
        u2 = out[out.index('"U2"'):]
        assert '"GND"' not in u2, "le net de U1 a fuit vers U2"

"""Le palier de DEPART se deduit de l echappement, pas d une constante.

`stm32-100` a brule 45 minutes a 2 couches avant de monter a 4 — un palier
qu aucun tirage ne pouvait reussir. La cause est LOCALE, pas globale : sur
trois jobs Freerouting, UN SEUL composant porte 20 a 28 % des echecs de
connexion, les 85 autres 2 % chacun. C est le LQFP-48, et sa part correspond
exactement a sa part des connexions.

Calibration sur nos propres cartes — signaux a echapper, par cote, par couche :

    carte            boitier      signaux  /cote  couches  ok   C requis
    stm32-baseline   LQFP-48            7    1.8      2    oui    0.88
    arduino-uno      TQFP-32           31    7.8      2    oui    3.88
    nucleo-f401      LQFP-64           38    9.5      4    oui    2.38
    stm32-60         LQFP-48           25    6.2      4    oui    1.56
    stm32-100        LQFP-48           43   10.8      2    NON    5.38

Les six reussites tiennent sous 3,88 ; l echec en reclamait 5,38. La capacite
est donc ENCADREE par la mesure — elle n est pas choisie.
"""
from __future__ import annotations

import math

import pytest

from routers.routing import (_CAPACITE_ECHAPPEMENT, _couches_pour_echapper,
                             _layer_ladder)


class TestCapacite:
    def test_la_capacite_est_encadree_par_les_mesures(self):
        assert 2.31 <= _CAPACITE_ECHAPPEMENT < 4.50, (
            "capacite hors de l intervalle mesure : soit on refuse une carte "
            "qui routait, soit on laisse passer celle qui echouait")


class TestCouchesPourEchapper:
    @pytest.mark.parametrize("signaux,attendu", [
        (7, 2),    # stm32-baseline — routait a 2
        (13, 2),   # stm32-30       — routait a 2 au moins
        (26, 4),   # stm32-60       — a REELLEMENT besoin de 4
        (36, 4),   # stm32-100      — echouait a 2
        (37, 4),   # nucleo-f401    — routait a 4
    ])
    def test_le_plancher_reproduit_les_mesures(self, signaux, attendu):
        assert _couches_pour_echapper(signaux) == attendu

    def test_un_boitier_sans_signal_n_impose_rien(self):
        assert _couches_pour_echapper(0) == 2

    def test_le_plancher_reste_pair(self):
        """Un empilage a nombre impair de couches cuivre ne se fabrique pas."""
        for s in range(0, 200, 7):
            assert _couches_pour_echapper(s) % 2 == 0

    def test_le_plancher_croit_avec_les_signaux(self):
        precedent = 0
        for s in (0, 10, 30, 50, 100, 200):
            n = _couches_pour_echapper(s)
            assert n >= precedent
            precedent = n


class TestEchelle:
    def test_l_echelle_demarre_au_plancher(self):
        assert _layer_ladder(8, plancher=4) == [4, 6, 8]

    def test_le_plancher_ne_depasse_jamais_le_plafond_du_plan(self):
        """Un compte Free est limite a 2 couches : on ne lui en vend pas 4."""
        assert _layer_ladder(2, plancher=6) == [2]

    def test_sans_plancher_l_echelle_est_inchangee(self):
        assert _layer_ladder(8) == [2, 4, 6, 8]


# ---------------------------------------------------------------------------
# Lecture du board — le plancher doit venir du PCB, pas d un parametre.
# ---------------------------------------------------------------------------

import inspect

from routers.routing import _signaux_a_echapper, route_auto


def test_les_nets_confies_au_plan_ne_comptent_pas():
    """GND part par le plan, pas par un echappement lateral.

    Le compter gonflerait le plancher de 58 signaux sur stm32-100 et ferait
    demarrer toutes les cartes trop haut — on vendrait des couches inutiles.
    """
    board = b'''(kicad_pcb
  (footprint "Package_QFP:LQFP-48_7x7mm_P0.5mm" (at 10 10)
    (property "Reference" "U1" (at 0 0 0))
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG1"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net 2 "GND"))
    (pad "3" smd rect (at 2 0) (size 1 1) (layers "F.Cu") (net 3 "SIG2"))
  )
  (footprint "Resistor_SMD:R_0402_1005Metric" (at 20 20)
    (property "Reference" "R1" (at 0 0 0))
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG1"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net 2 "GND"))
  )
  (footprint "Resistor_SMD:R_0402_1005Metric" (at 30 30)
    (property "Reference" "R2" (at 0 0 0))
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 3 "SIG2"))
  )
)'''
    assert _signaux_a_echapper(board, {"GND"}) == 2


def test_un_net_repete_sur_plusieurs_pastilles_compte_une_fois():
    """Deux pastilles du meme net sortent par UNE piste, pas deux."""
    board = b'''(kicad_pcb
  (footprint "Package_QFP:LQFP-48_7x7mm_P0.5mm" (at 10 10)
    (property "Reference" "U1" (at 0 0 0))
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG1"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net 1 "SIG1"))
  )
  (footprint "Resistor_SMD:R_0402_1005Metric" (at 20 20)
    (property "Reference" "R1" (at 0 0 0))
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG1"))
  )
)'''
    assert _signaux_a_echapper(board, {"GND"}) == 1


def test_un_board_illisible_n_impose_aucun_plancher():
    """Fail-safe : on ne devine pas un plancher, on n en pose pas."""
    assert _signaux_a_echapper(b"pas un board", {"GND"}) == 0


def test_le_plancher_est_calcule_et_journalise_mais_ne_commande_plus():
    """⚠️ DECISION UTILISATEUR (2026-08-29) : on part TOUJOURS de 2 couches.

    Le plancher reste calcule — il dit ce qui est hors d atteinte — mais ne
    fixe plus le depart. Raison commerciale : on ne facture pas 4 couches sur
    une PREVISION, meme etayee. On escalade sur PREUVE.

    Prix mesure et assume : ~44 min de tirage perdu sur stm32-100 avant que
    `_tirages_epuises_au_palier` n abandonne le palier 2.
    """
    src = inspect.getsource(route_auto)
    assert "_signaux_a_echapper(" in src, "plancher plus calcule du tout"
    assert "_couches_pour_echapper(" in src, "verdict du plancher perdu"
    assert "_layer_ladder(req.layers)" in src, (
        "l echelle ne doit plus recevoir de plancher : depart toujours a 2")


# ---------------------------------------------------------------------------
# ⚠️ Une pastille n est pas une liaison.
#
# Premiere version de `_signaux_a_echapper` : elle comptait les nets DISTINCTS
# des pastilles d un boitier. Sur un board, chaque pastille porte un net — y
# compris celles qui ne vont nulle part, que le generateur nomme
# `Net-(U1-Pad3)`. Tout LQFP-48 rendait donc ~45 signaux, quel que soit le
# circuit, et `stm32-baseline` — qui route a 2 couches — se voyait imposer 4.
#
# Mesure sur boards reels, AVANT correction :
#
#     carte            signaux lus   plancher   couches reelles
#     stm32-baseline            45          4   2      <- faux
#     arduino-uno                9          2   2
#     stm32-100                 45          4   4
#
# Un net qui ne touche qu UN seul boitier n a personne a rejoindre : il n a
# rien a echapper. Les tests unitaires ne l ont pas vu — leurs fixtures
# n avaient pas de pastilles orphelines.
# ---------------------------------------------------------------------------

def test_un_net_qui_ne_touche_qu_un_boitier_n_est_pas_une_liaison():
    board = b'''(kicad_pcb
  (footprint "Package_QFP:LQFP-48_7x7mm_P0.5mm" (at 10 10)
    (property "Reference" "U1" (at 0 0 0))
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG1"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net 9 "Net-(U1-Pad2)"))
    (pad "3" smd rect (at 2 0) (size 1 1) (layers "F.Cu") (net 8 "Net-(U1-Pad3)"))
  )
  (footprint "Resistor_SMD:R_0402_1005Metric" (at 20 20)
    (property "Reference" "R1" (at 0 0 0))
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG1"))
  )
)'''
    assert _signaux_a_echapper(board, {"GND"}) == 1


def test_les_pastilles_orphelines_ne_gonflent_pas_le_plancher():
    """48 pastilles orphelines ne valent pas 4 couches."""
    pads = "\n".join(
        f'    (pad "{i}" smd rect (at {i} 0) (size 1 1) (layers "F.Cu") '
        f'(net {i} "Net-(U1-Pad{i})"))' for i in range(1, 49))
    board = (b'(kicad_pcb\n  (footprint "Package_QFP:LQFP-48_7x7mm_P0.5mm" (at 10 10)\n'
             b'    (property "Reference" "U1" (at 0 0 0))\n'
             + pads.encode() + b"\n  )\n)")
    assert _signaux_a_echapper(board, {"GND"}) == 0
    assert _couches_pour_echapper(_signaux_a_echapper(board, {"GND"})) == 2

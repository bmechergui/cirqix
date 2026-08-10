"""Réparation des transitions de couche laissées sans via par ``kct route``.

Défaut mesuré le 2026-08-03 sur `examples/stm32-validation` (issue fork #7) :
le routeur amène ses pistes jusqu'au point de transition entre deux couches
puis **omet le via**. Le net paraît routé, il est électriquement ouvert.

Six points trouvés sur le board de référence ; en y posant un via, les
connexions manquantes passent de 13 à 9 (`+5V` entièrement réparé).

La réparation ne doit JAMAIS créer de violation : un via qui mordrait le
cuivre d'un autre net est abandonné, pas posé.
"""
from tools.kct_route import repair_layer_transitions


def _board(corps: str) -> bytes:
    return ("(kicad_pcb\n\t(version 20260329)\n" + corps + "\n)\n").encode("utf-8")


def _segment(x1, y1, x2, y2, couche, net, code=None):
    net_sexp = '(net %d)' % code if code is not None else '(net "%s")' % net
    return (
        '\t(segment\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(width 0.2)\n'
        '\t\t(layer "%s")\n\t\t%s\n\t\t(uuid "u%s%s")\n\t)\n'
        % (x1, y1, x2, y2, couche, net_sexp, x1, y1))


def test_pose_un_via_a_la_transition_orpheline():
    """Deux pistes du même net se rejoignent en un point, sur deux couches."""
    board = _board(
        _segment(10, 10, 20, 20, "F.Cu", "+3.3V")
        + _segment(20, 20, 30, 30, "In1.Cu", "+3.3V"))

    repare, pose = repair_layer_transitions(board)

    assert pose == 1
    texte = repare.decode("utf-8")
    assert "(via" in texte
    assert "(at 20 20)" in texte
    assert '(net "+3.3V")' in texte


def test_ne_pose_rien_quand_un_via_existe_deja():
    board = _board(
        _segment(10, 10, 20, 20, "F.Cu", "GND")
        + _segment(20, 20, 30, 30, "In1.Cu", "GND")
        + '\t(via\n\t\t(at 20 20)\n\t\t(size 0.5)\n\t\t(drill 0.2)\n'
          '\t\t(layers "F.Cu" "B.Cu")\n\t\t(net "GND")\n\t)\n')

    _, pose = repair_layer_transitions(board)

    assert pose == 0


def test_ne_pose_rien_sur_une_seule_couche():
    board = _board(
        _segment(10, 10, 20, 20, "F.Cu", "SWD")
        + _segment(20, 20, 30, 30, "F.Cu", "SWD"))

    _, pose = repair_layer_transitions(board)

    assert pose == 0


def test_abandonne_le_via_qui_mordrait_un_autre_net():
    """Un via de 0,5 mm à 0,1 mm d'une piste étrangère viole la clearance."""
    board = _board(
        _segment(10, 10, 20, 20, "F.Cu", "NRST")
        + _segment(20, 20, 30, 30, "In1.Cu", "NRST")
        + _segment(20.1, 20.1, 21, 21, "B.Cu", "GND"))

    _, pose = repair_layer_transitions(board)

    assert pose == 0, "un via ne doit jamais être posé au prix d'un court"


def test_accepte_le_format_numerique_des_nets():
    """Les boards KiCad <= 10.0 référencent les nets par code, pas par nom."""
    board = _board(
        '\t(net 3 "+5V")\n'
        + _segment(10, 10, 20, 20, "F.Cu", "+5V", code=3)
        + _segment(20, 20, 30, 30, "In2.Cu", "+5V", code=3))

    repare, pose = repair_layer_transitions(board)

    assert pose == 1
    assert "(net 3)" in repare.decode("utf-8")


def test_abandonne_le_via_trop_pres_d_un_via_etranger():
    """Deux vias de 0,5 mm à 0,2 mm l'un de l'autre se recouvrent.

    Le contrôle de coïncidence (0,05 mm) ne voit pas ce cas : il répond « pas
    de via ici », et sans contrôle de dégagement contre les vias existants on
    en posait un par-dessus celui d'un autre net — court-circuit réel.
    """
    board = _board(
        _segment(10, 10, 20, 20, "F.Cu", "SWDIO")
        + _segment(20, 20, 30, 30, "In1.Cu", "SWDIO")
        + '\t(via\n\t\t(at 20.2 20)\n\t\t(size 0.5)\n\t\t(drill 0.2)\n'
          '\t\t(layers "F.Cu" "B.Cu")\n\t\t(net "GND")\n\t)\n')

    _, pose = repair_layer_transitions(board)

    assert pose == 0


def test_board_sans_segment_est_rendu_intact():
    board = _board("\t(zone\n\t\t(net 0)\n\t)")

    repare, pose = repair_layer_transitions(board)

    assert pose == 0
    assert repare == board

"""Reconnexion des fragments de cuivre orphelins laissés par ``kct route``.

Second défaut mesuré le 2026-08-03 (issue fork #7), distinct des transitions
de couche sans via : le routeur laisse, pour un même net, des morceaux de piste
à des endroits **différents**, sans point commun. Le net paraît routé, il est
électriquement ouvert.

Comme pour la réparation des vias, une reconnexion n'est jamais posée au prix
d'un court : si la ligne droite entre deux fragments frôle le cuivre d'un autre
net, on renonce.
"""
from tools.kct_route import reconnect_net_fragments


def _board(corps: str) -> bytes:
    return ("(kicad_pcb\n\t(version 20260329)\n" + corps + "\n)\n").encode("utf-8")


def _segment(x1, y1, x2, y2, couche, net):
    return (
        '\t(segment\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(width 0.2)\n'
        '\t\t(layer "%s")\n\t\t(net "%s")\n\t\t(uuid "u%s-%s")\n\t)\n'
        % (x1, y1, x2, y2, couche, net, x1, y1))


def test_relie_deux_fragments_du_meme_net():
    """Deux tronçons distincts de `+3.3V`, même couche, chemin libre."""
    board = _board(
        _segment(10, 10, 15, 10, "F.Cu", "+3.3V")
        + _segment(18, 10, 25, 10, "F.Cu", "+3.3V"))

    repare, ajouts = reconnect_net_fragments(board)

    assert ajouts == 1
    texte = repare.decode("utf-8")
    assert texte.count("(segment") == 3
    assert '(net "+3.3V")' in texte


def test_ne_touche_pas_un_net_deja_connexe():
    board = _board(
        _segment(10, 10, 15, 10, "F.Cu", "GND")
        + _segment(15, 10, 20, 10, "F.Cu", "GND"))

    _, ajouts = reconnect_net_fragments(board)

    assert ajouts == 0


def test_renonce_si_un_autre_net_barre_le_passage():
    board = _board(
        _segment(10, 10, 15, 10, "F.Cu", "NRST")
        + _segment(18, 10, 25, 10, "F.Cu", "NRST")
        + _segment(16.5, 8, 16.5, 12, "F.Cu", "GND"))

    _, ajouts = reconnect_net_fragments(board)

    assert ajouts == 0, "une reconnexion ne doit jamais croiser un autre net"


def test_ignore_les_fragments_sur_des_couches_differentes():
    """Relier deux couches demande un via — hors du périmètre de cette passe."""
    board = _board(
        _segment(10, 10, 15, 10, "F.Cu", "SWD")
        + _segment(18, 10, 25, 10, "In1.Cu", "SWD"))

    _, ajouts = reconnect_net_fragments(board)

    assert ajouts == 0


def test_renonce_au_dela_de_la_portee_maximale():
    """Un saut de plusieurs centimètres n'est pas une reconnexion, c'est un net à router."""
    board = _board(
        _segment(10, 10, 15, 10, "F.Cu", "+5V")
        + _segment(90, 10, 95, 10, "F.Cu", "+5V"))

    _, ajouts = reconnect_net_fragments(board)

    assert ajouts == 0


def test_renonce_si_un_pad_etranger_barre_le_passage():
    """Mesuré : ne tester que les pistes a produit 3 courts-circuits réels.

    Les pads sont du cuivre au même titre que les pistes ; une reconnexion qui
    les traverse court-circuite deux nets et détruit la carte.
    """
    board = _board(
        '\t(footprint "R_0402"\n\t\t(at 16.5 10)\n'
        '\t\t(pad "1" smd roundrect\n\t\t\t(at 0 0)\n\t\t\t(size 0.6 0.6)\n'
        '\t\t\t(net 4 "GND")\n\t\t)\n\t)\n'
        + _segment(10, 10, 15, 10, "F.Cu", "NRST")
        + _segment(18, 10, 25, 10, "F.Cu", "NRST"))

    _, ajouts = reconnect_net_fragments(board)

    assert ajouts == 0, "une reconnexion ne doit jamais traverser un pad étranger"


def test_un_pad_du_meme_net_ne_bloque_pas():
    board = _board(
        '\t(footprint "R_0402"\n\t\t(at 16.5 10)\n'
        '\t\t(pad "1" smd roundrect\n\t\t\t(at 0 0)\n\t\t\t(size 0.6 0.6)\n'
        '\t\t\t(net 7 "+3.3V")\n\t\t)\n\t)\n'
        + _segment(10, 10, 15, 10, "F.Cu", "+3.3V")
        + _segment(18, 10, 25, 10, "F.Cu", "+3.3V"))

    _, ajouts = reconnect_net_fragments(board)

    assert ajouts == 1


def test_renonce_a_un_croisement_en_biais():
    """Mesuré : l'échantillonnage par extrémités laissait passer 1 croisement.

    Deux segments peuvent se couper alors qu'aucun de leurs points remarquables
    n'est proche de l'autre — il faut un vrai test d'intersection.
    """
    board = _board(
        _segment(10, 10, 15, 10, "F.Cu", "SWO")
        + _segment(20, 10, 25, 10, "F.Cu", "SWO")
        + _segment(14, 4, 21, 16, "F.Cu", "GND"))

    _, ajouts = reconnect_net_fragments(board)

    assert ajouts == 0


def test_ecrit_le_net_au_format_du_board():
    """Un board au format numérique doit recevoir `(net 3)`, pas `(net "3")`.

    KiCad <= 10.0 référence les nets par CODE. Sérialiser `(net "3")` produit
    une référence par NOM vers un net appelé littéralement « 3 », qui n'existe
    dans aucune déclaration : le cuivre ajouté est orphelin et ne reconnecte
    rien — en silence, car le DRC ne signale que la connexion toujours
    manquante, jamais le segment inutile.
    """
    def seg_num(x1, y1, x2, y2, code):
        return ('\t(segment\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(width 0.2)\n'
                '\t\t(layer "F.Cu")\n\t\t(uuid "u%s")\n\t\t(net %d)\n\t)\n'
                % (x1, y1, x2, y2, x1, code))

    board = _board('\t(net 3 "+3.3V")\n'
                   + seg_num(10, 10, 15, 10, 3) + seg_num(18, 10, 25, 10, 3))

    repare, ajouts = reconnect_net_fragments(board)

    assert ajouts == 1
    texte = repare.decode("utf-8")
    assert "(net 3)" in texte
    assert '(net "3")' not in texte


def test_renonce_si_un_via_etranger_barre_le_passage():
    """Un via est du cuivre : le traverser court-circuite deux nets."""
    board = _board(
        _segment(10, 10, 15, 10, "F.Cu", "SWCLK")
        + _segment(18, 10, 25, 10, "F.Cu", "SWCLK")
        + '\t(via\n\t\t(at 16.5 10)\n\t\t(size 0.6)\n\t\t(drill 0.3)\n'
          '\t\t(layers "F.Cu" "B.Cu")\n\t\t(net "GND")\n\t)\n')

    _, ajouts = reconnect_net_fragments(board)

    assert ajouts == 0


def test_un_via_du_meme_net_ne_bloque_pas():
    board = _board(
        _segment(10, 10, 15, 10, "F.Cu", "GND")
        + _segment(18, 10, 25, 10, "F.Cu", "GND")
        + '\t(via\n\t\t(at 16.5 10)\n\t\t(size 0.6)\n\t\t(drill 0.3)\n'
          '\t\t(layers "F.Cu" "B.Cu")\n\t\t(net "GND")\n\t)\n')

    _, ajouts = reconnect_net_fragments(board)

    assert ajouts == 1


def test_board_sans_segment_est_rendu_intact():
    board = _board("\t(zone\n\t\t(net 0)\n\t)")

    repare, ajouts = reconnect_net_fragments(board)

    assert ajouts == 0
    assert repare == board

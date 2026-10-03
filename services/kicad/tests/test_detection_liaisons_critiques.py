"""La détection des liaisons critiques — D-2026-09-25-a.

Fonction pure : elle lit le board, sans pcbnew, et désigne ce qu'il faut router
AVANT le routage général : quartz -> broche du circuit, condensateur de charge
-> quartz, condensateur de découplage -> broche d'alimentation. Les paires
différentielles sont signalées, jamais routées.

Mesure du 2026-09-25 sur les placements versionnés, centre à centre :
carte-05 11 liaisons de 2,8 à 16,7 mm, carte-10 26 de 3,9 à 27 mm, quartz de
`stm32-validation` à 9,1 et 13,3 mm de U2. Une liaison longue est un défaut de
PLACEMENT : elle n'est jamais pré-routée.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import nets_critiques as N  # noqa: E402

_EX = _SERVICE / "examples"


def _fp(ref, x, y, pads, rot=0.0):
    """Une empreinte minimale ; `pads` = [(nom, type, dx, dy, net, couches)]."""
    lignes = ['  (footprint "X:Y" (layer "F.Cu") (at %s %s %s)' % (x, y, rot),
              '    (property "Reference" "%s")' % ref]
    for nom, typ, dx, dy, net, couches in pads:
        lignes.append('    (pad "%s" %s rect (at %s %s) (size 0.6 0.6) (layers %s) (net "%s"))'
                      % (nom, typ, dx, dy, couches, net))
    lignes.append("  )")
    return "\n".join(lignes)


_CMS = '"F.Cu" "F.Paste" "F.Mask"'


def _board(*fps):
    return "(kicad_pcb (version 20240108)\n" + "\n".join(fps) + "\n)\n"


def _mcu(x=0.0, y=0.0):
    pads = [(str(i), "smd", -3.0 + i * 0.5, 3.5, "SIG%d" % i, _CMS) for i in range(1, 9)]
    pads[0] = ("1", "smd", -2.5, 3.5, "+3V3", _CMS)
    pads[1] = ("2", "smd", -2.0, 3.5, "OSC_IN", _CMS)
    pads[2] = ("3", "smd", -1.5, 3.5, "GND", _CMS)
    return _fp("U1", x, y, pads)


class TestRegles:
    def test_un_decouplage_proche_est_detecte(self):
        c = _fp("C1", -2.5, 5.5, [("1", "smd", 0, -0.5, "+3V3", _CMS),
                                  ("2", "smd", 0, 0.5, "GND", _CMS)])
        l = N.liaisons_critiques(_board(_mcu(), c))
        assert [(x.type, x.a, x.b, x.net) for x in l] == [("decouplage", ("C1", "1"), ("U1", "1"), "+3V3")]
        assert l[0].largeur_mm == N.LARGEUR_ALIM_MM

    def test_un_decouplage_lointain_n_est_pas_pre_route(self):
        """C'est un défaut de placement, pas de routage."""
        c = _fp("C1", -2.5, 25.0, [("1", "smd", 0, -0.5, "+3V3", _CMS),
                                   ("2", "smd", 0, 0.5, "GND", _CMS)])
        assert N.liaisons_critiques(_board(_mcu(), c)) == []

    def test_un_net_nomme_alimentation_sans_condensateur_vers_la_masse_n_est_pas_un_rail(self):
        """`LED_PWR` n'est pas un rail parce qu'il s'appelle ainsi."""
        r = _fp("R1", -2.5, 5.5, [("1", "smd", 0, -0.5, "+3V3", _CMS),
                                  ("2", "smd", 0, 0.5, "LED_PWR", _CMS)])
        assert N.liaisons_critiques(_board(_mcu(), r)) == []

    def test_le_quartz_passe_avant_le_decouplage(self):
        y = _fp("Y1", -2.0, 5.5, [("1", "smd", 0, -0.5, "OSC_IN", _CMS),
                                  ("2", "smd", 0, 0.5, "OSC_OUT", _CMS)])
        c = _fp("C1", -2.5, 5.5, [("1", "smd", 0, -0.5, "+3V3", _CMS),
                                  ("2", "smd", 0, 0.5, "GND", _CMS)])
        types = [x.type for x in N.liaisons_critiques(_board(_mcu(), c, y))]
        assert types[0] == "quartz" and "decouplage" in types

    def test_une_charge_de_quartz_va_au_quartz_pas_au_circuit(self):
        y = _fp("Y1", 3.0, 8.0, [("1", "smd", 0, 0, "OSC_IN", _CMS),
                                 ("2", "smd", 1.0, 0, "OSC_OUT", _CMS)])
        c = _fp("C5", 3.0, 10.0, [("1", "smd", 0, -0.5, "OSC_IN", _CMS),
                                  ("2", "smd", 0, 0.5, "GND", _CMS)])
        l = [x for x in N.liaisons_critiques(_board(_mcu(), y, c)) if x.a[0] == "C5"]
        assert [(x.type, x.b) for x in l] == [("charge-quartz", ("Y1", "1"))]

    def test_une_liaison_ne_change_jamais_de_face(self):
        """Pré-routée sans via : une CMS sur l'AUTRE face est ignorée."""
        c = _fp("C1", -2.5, 5.5, [("1", "smd", 0, -0.5, "+3V3", '"B.Cu" "B.Paste" "B.Mask"'),
                                  ("2", "smd", 0, 0.5, "GND", '"B.Cu" "B.Paste" "B.Mask"')])
        assert N.liaisons_critiques(_board(_mcu(), c)) == []

    def test_une_pastille_traversante_rejoint_une_cms_sans_via(self):
        """Elle existe sur toutes les faces : la piste va sur la face de la CMS."""
        c = _fp("C1", -2.5, 5.5, [("1", "thru_hole", 0, -0.5, "+3V3", '"*.Cu" "*.Mask"'),
                                  ("2", "thru_hole", 0, 0.5, "GND", '"*.Cu" "*.Mask"')])
        l = N.liaisons_critiques(_board(_mcu(), c))
        assert [x.a for x in l] == [("C1", "1")]
        ps = {(p.ref, p.nom): p for p in N.pastilles_du_board(_board(_mcu(), c))}
        assert N.face_de_la_liaison(ps[("C1", "1")], ps[("U1", "1")]) == "F.Cu"

    def test_une_pastille_n_est_source_qu_une_fois(self):
        c = _fp("C1", -2.5, 5.5, [("1", "smd", 0, -0.5, "+3V3", _CMS),
                                  ("2", "smd", 0, 0.5, "GND", _CMS)])
        l = N.liaisons_critiques(_board(_mcu(), c, _mcu(0.2, 0.0).replace('"U1"', '"U2"')))
        assert len([x for x in l if x.a == ("C1", "1")]) == 1

    def test_la_rotation_suit_le_sens_de_kicad(self):
        """(x, y) -> (x cos a + y sin a, -x sin a + y cos a)."""
        p = N.pastilles_du_board(_board(_fp("C1", 10.0, 10.0, [("1", "smd", 1.0, 0.0, "N", _CMS)], rot=90)))[0]
        assert abs(p.x - 10.0) < 1e-6 and abs(p.y - 9.0) < 1e-6


class TestPairesDifferentielles:
    def test_une_paire_usb_est_signalee(self):
        u = _fp("U1", 0, 0, [("1", "smd", 0, 0, "USB_DP", _CMS), ("2", "smd", 1, 0, "USB_DM", _CMS)])
        j = _fp("J1", 5, 0, [("1", "smd", 0, 0, "USB_DP", _CMS), ("2", "smd", 1, 0, "USB_DM", _CMS)])
        assert N.paires_differentielles(_board(u, j)) == [("USB_DP", "USB_DM")]


class TestVraisBoards:
    """Sur les placements VERSIONNÉS : les deux écritures de net sont lues, et
    la détection trouve ce qu'on attend — rien de câblé en dur."""

    def test_les_deux_ecritures_de_net_sont_lues(self):
        texte = '(pad "1" smd rect (at 0 0) (layers "F.Cu") (net 3 "GND"))'
        assert N._net_de(texte) == "GND"
        assert N._net_de('(pad "1" smd rect (at 0 0) (layers "F.Cu") (net "GND"))') == "GND"

    def test_le_quartz_de_stm32_validation_est_trouve_hors_limite(self):
        board = (_EX / "stm32-validation" / "expected" / "2_placement_valide.kicad_pcb").read_text(encoding="utf-8")
        sans_limite = N.liaisons_critiques(board, liaison_max_mm=99.0)
        # La DÉTECTION voit le quartz ; c'est la LONGUEUR qui l'écarte.
        pastilles = [p for p in N.pastilles_du_board(board) if p.ref == "Y1"]
        assert {p.net for p in pastilles} >= {"OSC_IN", "OSC_OUT"}
        # À 9 mm et plus, le quartz est un défaut de PLACEMENT : rien de pré-routé.
        assert not [x for x in N.liaisons_critiques(board) if x.a[0].startswith("Y")]

    def test_chaque_liaison_retenue_respecte_la_limite(self):
        for carte in ("carte-05-capteur-i2c", "carte-10-maximale", "stm32-30"):
            board = (_EX / carte / "expected" / "placement.kicad_pcb").read_text(encoding="utf-8")
            for l in N.liaisons_critiques(board):
                assert l.distance_mm <= N.LONGUEUR_MAX_MM
                assert l.net and l.net != "GND"

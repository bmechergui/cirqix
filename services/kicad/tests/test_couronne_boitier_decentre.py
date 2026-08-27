"""La couronne doit contourner le CORPS du module, pas son origine.

⚠️ Mesure du 2026-08-27, ESP32 du banc. La couronne deterministe laissait
CINQ `courtyards_overlap`, tous contre le module dominant :

    Footprint R1 <-> Footprint U1      Footprint C4 <-> Footprint U1
    Footprint R2 <-> Footprint U1      Footprint D5 <-> Footprint U1
    Footprint R3 <-> Footprint U1

La geometrie semblait pourtant impossible : R1 etait a y = 3,98 et le module
mesure 41 mm de haut autour de y = 34,9. Le courtyard reel de l ESP32-WROOM,
lu dans le fichier, tranche :

    y local du courtyard : de -30,74 a +10,51      (41,25 mm de haut)

Il n est **pas centre sur l origine** du footprint — il deborde 30,7 mm d un
cote et 10,5 mm de l autre. `_placer_en_couronne` prenait la demi-hauteur
(20,6 mm) de part et d autre de la POSITION : du cote long, l anneau tombait
en plein dans le module.

Rien d exotique : un module a son origine sur la pastille 1, pas au milieu de
son corps. C est le cas de l ESP32, des en-tetes Arduino et des connecteurs
Nucleo — donc de toutes les cartes a boitier dominant que vise ce banc.

⚠️ La TAILLE ne suffit pas a placer : il faut la BOITE. `_encombrement_fp`
rendait `max - min` et jetait le decalage, qui est precisement l information
manquante.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import placement as P  # noqa: E402

NL = chr(10)


def _ligne_crtyd(x0, y0, x1, y1):
    return ('\t\t(fp_line (start %s %s) (end %s %s) '
            '(stroke (width 0.05) (type solid)) (layer "F.CrtYd"))'
            % (x0, y0, x1, y1))


def _module(ref, x, y, x0, y0, x1, y1):
    """Un boitier dont le courtyard va de (x0,y0) a (x1,y1) EN LOCAL."""
    return NL.join([
        '\t(footprint "M" (layer "F.Cu")',
        "\t\t(at %s %s)" % (x, y),
        '\t\t(fp_text reference "%s" (at 0 0) (layer "F.SilkS"))' % ref,
        _ligne_crtyd(x0, y0, x1, y0),
        _ligne_crtyd(x1, y0, x1, y1),
        _ligne_crtyd(x1, y1, x0, y1),
        _ligne_crtyd(x0, y1, x0, y0),
        '\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "N"))',
        "\t)",
    ])


def _carte():
    from kicad_tools.schema.pcb import PCB

    corps = [
        # Module dominant : 48 x 41, courtyard DECALE — comme l ESP32 reel.
        _module("U1", 46.5, 35.0, -24.0, -30.74, 24.0, 10.51),
    ]
    # Dix passifs minuscules, poses n importe ou : la couronne doit les ranger.
    for i in range(10):
        corps.append(_module("R%d" % (i + 1), 5.0 + i, 5.0,
                             -0.93, -0.47, 0.93, 0.47))
    texte = NL.join([
        "(kicad_pcb",
        "\t(version 20240108)",
        '\t(layers (0 "F.Cu" signal) (44 "Edge.Cuts" user) (47 "F.CrtYd" user))',
        '\t(net 1 "N")',
        '\t(gr_rect (start 0 0) (end 93 70) (layer "Edge.Cuts"))',
        *corps,
        ")",
    ])
    d = tempfile.mkdtemp()
    f = Path(d) / "b.kicad_pcb"
    f.write_text(texte, encoding="utf-8")
    return PCB.load(str(f))


def _boite_absolue(fp):
    x0, y0, x1, y1 = P._boite_locale_fp(fp)
    px, py = fp.position
    return px + x0, py + y0, px + x1, py + y1


def _se_chevauchent(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


class TestBoite:
    def test_la_boite_conserve_le_decalage(self):
        pcb = _carte()
        u1 = next(f for f in pcb.footprints if f.reference == "U1")
        x0, y0, x1, y1 = P._boite_locale_fp(u1)
        assert (round(y0, 2), round(y1, 2)) == (-30.74, 10.51), (
            "le decalage du courtyard est l information qui manquait")

    def test_la_taille_reste_coherente_avec_l_encombrement(self):
        pcb = _carte()
        u1 = next(f for f in pcb.footprints if f.reference == "U1")
        x0, y0, x1, y1 = P._boite_locale_fp(u1)
        l, h = P._encombrement_fp(u1)
        assert (round(x1 - x0, 2), round(y1 - y0, 2)) == (round(l, 2), round(h, 2))


class TestCouronne:
    def test_aucun_passif_ne_chevauche_le_corps_du_module(self):
        pcb = _carte()
        P._placer_en_couronne(pcb, ["U1"])
        u1 = next(f for f in pcb.footprints if f.reference == "U1")
        boite_u1 = _boite_absolue(u1)
        fautifs = [f.reference for f in pcb.footprints
                   if f.reference != "U1"
                   and _se_chevauchent(_boite_absolue(f), boite_u1)]
        assert not fautifs, (
            "%s chevauche(nt) le corps du module — la couronne a raisonne "
            "autour de l origine, pas du corps" % fautifs)

    def test_les_passifs_restent_dans_le_contour(self):
        pcb = _carte()
        P._placer_en_couronne(pcb, ["U1"])
        l, h = pcb.board_size
        dehors = []
        for f in pcb.footprints:
            if f.reference == "U1":
                continue
            x0, y0, x1, y1 = _boite_absolue(f)
            if x0 < 0 or y0 < 0 or x1 > l or y1 > h:
                dehors.append(f.reference)
        assert not dehors, "%s hors contour — un passif dehors est inroutable" % dehors


class TestEcartement:
    """`_ecarter_des_dominants` raisonnait aussi en demi-taille symetrique.

    ⚠️ Meme cause racine que la couronne, autre fonction. L emprise interdite
    etait `position ± demi-taille` : sur un courtyard decale de 10 mm, elle est
    trop PETITE du cote long et trop GRANDE du cote court. Un passif pose dans
    le module, mais hors de cette emprise fausse, n etait donc pas ecarte.

    ⚠️ Le contour etait verifie sur la POSITION du composant, pas sur sa boite :
    un composant pouvait etre pousse le corps hors de la carte, donc inroutable
    — exactement le defaut que l ecartement dit vouloir eviter.
    """

    def _carte_avec_intrus(self):
        pcb = _carte()
        u1 = next(f for f in pcb.footprints if f.reference == "U1")
        # Corps centre verticalement : (-30,74 + 10,51) / 2 = -10,115.
        u1.position = (46.5, 35.0 + 10.115)
        # Corps reel : y de 14,4 a 55,6. Ancienne emprise fausse : 24,5 a 65,7.
        # Un passif a y = 18 est DANS le module et HORS de l ancienne emprise.
        r1 = next(f for f in pcb.footprints if f.reference == "R1")
        r1.position = (46.5, 18.0)
        return pcb, u1, r1

    def test_un_passif_dans_le_corps_est_ecarte(self):
        pcb, u1, r1 = self._carte_avec_intrus()
        P._ecarter_des_dominants(pcb, ["U1"])
        assert not _se_chevauchent(_boite_absolue(r1), _boite_absolue(u1)), (
            "R1 etait dans le corps du module mais hors de l emprise "
            "symetrique : l ecartement ne l a pas vu")

    def test_le_passif_ecarte_reste_entierement_dans_la_carte(self):
        pcb, u1, r1 = self._carte_avec_intrus()
        P._ecarter_des_dominants(pcb, ["U1"])
        l, h = pcb.board_size
        x0, y0, x1, y1 = _boite_absolue(r1)
        assert 0 <= x0 and x1 <= l and 0 <= y0 and y1 <= h, (
            "pousse hors du contour : ses nets deviennent inroutables")

    def test_un_ancre_n_est_jamais_deplace(self):
        pcb, u1, _r1 = self._carte_avec_intrus()
        avant = u1.position
        P._ecarter_des_dominants(pcb, ["U1"])
        assert u1.position == avant

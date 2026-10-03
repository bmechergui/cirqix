"""La sonde de l'A/B du routage prioritaire mesure-t-elle ce qu'elle annonce ?

Leçon du 2026-09-03 : trois sondes fausses dans une session, toutes trouvées
par l'invraisemblance de leur résultat, jamais par leur code. Celle-ci est
confrontée à des chemins de longueur CONNUE, puis à un vrai board du banc.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "scripts"))

import ab_routage_prioritaire as AB  # noqa: E402
from tools import nets_critiques as N  # noqa: E402

_CMS = '"F.Cu" "F.Paste" "F.Mask"'


def _fp(ref, x, y, net, couches=_CMS):
    return ('  (footprint "X:Y" (layer "F.Cu") (at %s %s 0)\n'
            '    (property "Reference" "%s")\n'
            '    (pad "1" smd rect (at 0 0) (size 0.6 0.6) (layers %s) (net "%s"))\n  )'
            % (x, y, ref, couches, net))


def _seg(x1, y1, x2, y2, couche="F.Cu", net='(net "+3V3")'):
    return ('  (segment (start %s %s) (end %s %s) (width 0.25) (layer "%s") %s (uuid "u"))'
            % (x1, y1, x2, y2, couche, net))


def _via(x, y, net='(net "+3V3")'):
    return '  (via (at %s %s) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") %s (uuid "v"))' % (x, y, net)


def _board(*morceaux):
    return "(kicad_pcb (version 20240108)\n" + "\n".join(morceaux) + "\n)\n"


def _longueur(texte):
    pads = {p.ref: p for p in N.pastilles_du_board(texte)}
    return AB.longueur_de_liaison(texte, pads["C1"], pads["U1"])


def test_un_chemin_a_deux_vias_a_sa_vraie_longueur():
    b = _board(_fp("C1", 0, 0, "+3V3"), _fp("U1", 3, 0, "+3V3"),
               _seg(0, 0, 1, 0), _via(1, 0), _seg(1, 0, 2, 0, "B.Cu"),
               _via(2, 0), _seg(2, 0, 3, 0))
    assert math.isclose(_longueur(b), 3.0, abs_tol=1e-6)


def test_sans_piste_il_n_y_a_pas_de_chemin_et_pas_de_zero():
    b = _board(_fp("C1", 0, 0, "+3V3"), _fp("U1", 3, 0, "+3V3"), _seg(0, 0, 1, 0))
    assert _longueur(b) is None


def test_la_piste_d_un_autre_net_ne_compte_pas():
    b = _board(_fp("C1", 0, 0, "+3V3"), _fp("U1", 3, 0, "+3V3"),
               _seg(0, 0, 3, 0, net='(net "SDA")'))
    assert _longueur(b) is None


def test_une_piste_sur_l_autre_face_ne_touche_pas_une_cms():
    b = _board(_fp("C1", 0, 0, "+3V3"), _fp("U1", 3, 0, "+3V3"), _seg(0, 0, 3, 0, "B.Cu"))
    assert _longueur(b) is None


def test_l_ecriture_numerotee_des_nets_est_lue():
    b = _board('  (net 3 "+3V3")', _fp("C1", 0, 0, "+3V3"), _fp("U1", 3, 0, "+3V3"),
               _seg(0, 0, 3, 0, net="(net 3)"))
    assert math.isclose(_longueur(b), 3.0, abs_tol=1e-6)


def test_deux_pastilles_au_meme_numero_sont_une_seule_broche():
    """La languette d'un SOT-223 porte le numéro de la broche 2."""
    u1 = "\n".join([
        '  (footprint "X:Y" (layer "F.Cu") (at 3 0 0)',
        '    (property "Reference" "U1")',
        '    (pad "1" smd rect (at 0 0) (size 0.6 0.6) (layers %s) (net "+3V3"))' % _CMS,
        '    (pad "1" smd rect (at 6 0) (size 0.6 0.6) (layers %s) (net "+3V3"))' % _CMS,
        '  )'])
    b = _board(_fp("C1", 0, 0, "+3V3"), u1, _seg(0, 0, 3, 0))
    pads = {p.ref: p for p in N.pastilles_du_board(b)}   # garde la DERNIÈRE instance
    assert math.isclose(AB.longueur_de_liaison(b, pads["C1"], pads["U1"]), 3.0, abs_tol=1e-6)


def test_le_plus_court_chemin_est_rendu():
    b = _board(_fp("C1", 0, 0, "+3V3"), _fp("U1", 3, 0, "+3V3"),
               _seg(0, 0, 0, 5), _seg(0, 5, 3, 5), _seg(3, 5, 3, 0),   # détour de 13
               _seg(0, 0, 3, 0))                                        # direct, 3
    assert math.isclose(_longueur(b), 3.0, abs_tol=1e-6)


def test_sur_un_vrai_board_du_banc_les_longueurs_sont_plausibles():
    """Jamais plus courtes que la ligne droite entre centres (moins les deux
    demi-pastilles), et au moins une liaison reliée par des pistes."""
    carte = _SERVICE / "examples" / "carte-05-capteur-i2c" / "expected"
    place = (carte / "placement.kicad_pcb").read_text(encoding="utf-8")
    route = (carte / "final.kicad_pcb").read_text(encoding="utf-8")
    mesures = AB.mesurer_liaisons(place, route)
    assert mesures, "la détection ne voit aucune liaison sur carte-05"
    # Une broche peut porter plusieurs pastilles (languette d'un SOT-223) :
    # le plancher se prend sur la plus proche.
    instances = {}
    for p in N.pastilles_du_board(route):
        instances.setdefault((p.ref, p.nom), []).append(p)
    reliees = [m for m in mesures if m["cuivre_mm"] is not None]
    assert reliees, "aucune liaison reliée par des pistes : sonde aveugle ?"
    for m in reliees:
        plancher = min(math.hypot(a.x - b.x, a.y - b.y) - a.demi_taille - b.demi_taille
                       for a in instances[tuple(m["a"])] for b in instances[tuple(m["b"])])
        assert m["cuivre_mm"] >= plancher - 1e-6


def _seg_large(x1, y1, x2, y2, largeur):
    return ('  (segment (start %s %s) (end %s %s) (width %s) (layer "F.Cu") (net "+3V3") (uuid "u"))'
            % (x1, y1, x2, y2, largeur))


def _placement_et_route(largeur):
    """Un découplage C1 -> U1.1 détectable, et sa piste sur le board routé."""
    u1 = "\n".join([
        '  (footprint "X:Y" (layer "F.Cu") (at 0 0 0)',
        '    (property "Reference" "U1")',
        '    (pad "1" smd rect (at -2.5 3.5) (size 0.6 0.6) (layers %s) (net "+3V3"))' % _CMS,
        '    (pad "2" smd rect (at -2.0 3.5) (size 0.6 0.6) (layers %s) (net "GND"))' % _CMS,
        '    (pad "3" smd rect (at -1.5 3.5) (size 0.6 0.6) (layers %s) (net "SIG3"))' % _CMS,
        '  )'])
    c1 = "\n".join([
        '  (footprint "X:Y" (layer "F.Cu") (at -2.5 5.5 0)',
        '    (property "Reference" "C1")',
        '    (pad "1" smd rect (at 0 -0.5) (size 0.6 0.6) (layers %s) (net "+3V3"))' % _CMS,
        '    (pad "2" smd rect (at 0 0.5) (size 0.6 0.6) (layers %s) (net "GND"))' % _CMS,
        '  )'])
    place = _board(u1, c1)
    return place, _board(u1, c1, _seg_large(-2.5, 3.5, -2.5, 5.0, largeur))


def test_une_piste_a_la_largeur_de_la_liaison_porte_la_signature():
    place, route = _placement_et_route(N.LARGEUR_ALIM_MM)
    [m] = AB.mesurer_liaisons(place, route)
    assert m["statut"] == "mesuree" and m["signature_passe"] is True


def test_une_piste_de_freerouting_ne_porte_pas_la_signature():
    place, route = _placement_et_route(0.25)
    [m] = AB.mesurer_liaisons(place, route)
    assert m["statut"] == "mesuree" and m["signature_passe"] is False


def test_sans_piste_le_statut_est_aucun_chemin():
    place, _ = _placement_et_route(0.4)
    [m] = AB.mesurer_liaisons(place, place)
    assert m["statut"] == "aucun_chemin" and m["cuivre_mm"] is None


def test_une_pastille_absente_n_est_pas_un_echec_de_routage():
    place, route = _placement_et_route(0.4)
    [m] = AB.mesurer_liaisons(place, route.replace('"C1"', '"C9"'))
    assert m["statut"] == "pastille_absente"


def test_temoin_aucun_board_livre_sans_passe_ne_porte_la_signature():
    """Si le bras A pouvait porter la signature, elle ne prouverait rien."""
    for carte in ("carte-03-oscillateur", "carte-05-capteur-i2c",
                  "carte-08-dense", "carte-10-maximale"):
        d = _SERVICE / "examples" / carte / "expected"
        mesures = AB.mesurer_liaisons((d / "placement.kicad_pcb").read_text(encoding="utf-8"),
                                      (d / "final.kicad_pcb").read_text(encoding="utf-8"))
        assert not [m for m in mesures if m["signature_passe"]], carte
        assert all(m["statut"] in ("mesuree", "aucun_chemin") for m in mesures), carte


def test_un_rapport_drc_sans_ses_sections_n_est_pas_zero_erreur(monkeypatch):
    from routers import routing as R
    monkeypatch.setattr(R, "_rapport_drc", lambda _b: {})
    assert AB._juger(b"") == {"sans_verdict": True, "raison": "structure"}

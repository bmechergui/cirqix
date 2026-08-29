"""Compter les ilots de plan RESTANTS, pas seulement les vias poses.

⚠️ Trou signale par Grok le 2026-08-29, et verifie dans le code : la couture
rapporte le nombre de vias qu elle pose, JAMAIS le nombre d ilots qui
subsistent. Sa formulation :

    « Si la couture rend 0 orphelin MAIS 15 ilots, vous passez fabricable
      connecte avec une mauvaise reference. »

Nos deux filets — couture repetee et garde sur les broches GND orphelines —
voient les OPENS. Ils ne voient pas un plan en peigne dont chaque morceau est
assez gros pour satisfaire le DRC et trop petit pour servir de retour.

Un plan sain compte 1 ilot par face. Au-dela, le cuivre de masse est
fragmente par les pistes de signal.
"""
from __future__ import annotations

from routers.routing import _compte_ilots_de_plan, _PLAN_FRAGMENTE_AU_DELA


_ZONE = '''  (zone (net 1) (net_name "{net}") (layer "{couche}")
    (polygon (pts (xy 0 0) (xy 10 0) (xy 10 10) (xy 0 10)))
{polys}  )
'''
_POLY = '    (filled_polygon (layer "{couche}") (pts (xy 0 0) (xy 1 0) (xy 1 1)))\n'


def _board(zones: list) -> bytes:
    corps = "".join(
        _ZONE.format(net=n, couche=c, polys=_POLY.format(couche=c) * k)
        for n, c, k in zones)
    return f"(kicad_pcb (version 20240108)\n{corps})\n".encode()


def test_un_plan_dun_seul_tenant_compte_un_ilot():
    assert _compte_ilots_de_plan(_board([("GND", "F.Cu", 1)])) == {"GND@F.Cu": 1}


def test_un_plan_coupe_en_cinq_est_compte():
    assert _compte_ilots_de_plan(_board([("GND", "F.Cu", 5)])) == {"GND@F.Cu": 5}


def test_chaque_face_est_comptee_separement():
    """Mesure du 2026-08-26 : F.Cu en 5 morceaux, B.Cu d un seul tenant.

    Agreger les deux masquerait exactement le defaut qu on cherche.
    """
    n = _compte_ilots_de_plan(_board([("GND", "F.Cu", 5), ("GND", "B.Cu", 1)]))
    assert n == {"GND@F.Cu": 5, "GND@B.Cu": 1}


def test_une_zone_non_remplie_ne_compte_pas_zero_a_tort():
    """Une zone SANS remplissage n est pas un plan sain, c est un contour.

    Les boards de reference du depot sont sauves sans donnees de remplissage :
    les compter « 0 ilot » les declarerait parfaits. On rend 0 pour une zone
    vide, et l appelant sait qu il doit avoir coule AVANT de mesurer.
    """
    assert _compte_ilots_de_plan(_board([("GND", "F.Cu", 0)])) == {"GND@F.Cu": 0}


def test_un_board_sans_zone_ne_rend_rien():
    assert _compte_ilots_de_plan(b"(kicad_pcb)") == {}


def test_le_seuil_de_fragmentation_reste_exigeant():
    """Un plan sain fait 1 ilot par face ; 2 tolere une decoupe legitime."""
    assert 1 <= _PLAN_FRAGMENTE_AU_DELA <= 3

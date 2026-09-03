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


# ---------------------------------------------------------------------------
# ⚠️ TROIS ECRITURES du net d une zone — et n en accepter qu une rendait le
# compteur AVEUGLE sur tout board livre.
#
#     (net 3) (net_name "GND")   notre generateur
#     (net "GND")                pcbnew de KiCad 10
#     (net 3)                    forme ancienne, nom a resoudre
#
# Mesure du 2026-08-30 sur le board LIVRE de `stm32-100` : le compteur rendait
# `{}` alors que le fichier contenait 9 polygones remplis sur F.Cu. Le plan de
# masse etait en NEUF ilots — la cause exacte du « 1 net incomplet : GND » qui
# ramenait la carte de 100 % a 99 %.
#
# Le defaut etait VISIBLE dans le fichier depuis le debut ; c est le parseur
# qui le cachait. Et cette variation KiCad 10 est deja documentee dans
# CLAUDE.md pour le comptage des nets — je ne l avais pas appliquee ici.
# ---------------------------------------------------------------------------

_ZONE_KICAD10 = '''\t(zone
\t\t(net "GND")
\t\t(layer "%s")
\t\t(uuid "ad12570c-c4b7-43c8-8d87-d202319fc7ae")
\t\t(hatch edge 0.508)
%s\t)
'''
_POLY_REEL = '\t\t(filled_polygon\n\t\t\t(layer "%s")\n\t\t\t(pts (xy 0 0))\n\t\t)\n'


def test_la_forme_kicad10_est_reconnue():
    """`(net "GND")` sans numero — ce que pcbnew ecrit."""
    board = ("(kicad_pcb\n"
             + _ZONE_KICAD10 % ("F.Cu", _POLY_REEL % "F.Cu" * 9)
             + _ZONE_KICAD10 % ("B.Cu", _POLY_REEL % "B.Cu")
             + ")\n").encode()
    assert _compte_ilots_de_plan(board) == {"GND@F.Cu": 9, "GND@B.Cu": 1}


def test_une_zone_keepout_sans_net_est_ignoree():
    """Le board livre en porte une : elle n a ni net ni polygone rempli."""
    keepout = '\t(zone\n\t\t(layer "F.Cu")\n\t\t(keepout (tracks not_allowed))\n\t)\n'
    board = ("(kicad_pcb\n" + keepout
             + _ZONE_KICAD10 % ("B.Cu", _POLY_REEL % "B.Cu") + ")\n").encode()
    assert _compte_ilots_de_plan(board) == {"GND@B.Cu": 1}


def test_un_plan_en_neuf_ilots_est_signale_comme_fragmente():
    board = ("(kicad_pcb\n"
             + _ZONE_KICAD10 % ("F.Cu", _POLY_REEL % "F.Cu" * 9) + ")\n").encode()
    ilots = _compte_ilots_de_plan(board)
    assert ilots["GND@F.Cu"] > _PLAN_FRAGMENTE_AU_DELA

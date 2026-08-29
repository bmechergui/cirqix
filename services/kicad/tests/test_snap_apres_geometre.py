"""Le snap bypass tourne DANS auto_place, et apres le Geometre.

Un snap correct mais jamais appele est indistinguable d un snap absent —
c est exactement la condition qui a masque pendant des semaines le fait que
le Geometre ne tournait jamais en production. On verifie donc l ORDRE, pas
seulement l existence.
"""
from __future__ import annotations

import inspect

import tools.placement as placement


def _src() -> str:
    return inspect.getsource(placement._auto_place_une_fois)


def test_le_snap_est_appele_dans_auto_place():
    assert "snap_cluster_members(" in _src(), (
        "snap bypass jamais appele : la regle metier ne s applique pas")


def test_le_snap_vient_apres_le_geometre_et_le_halo():
    src = _src()
    i_cmaes = src.index("_refine_with_cmaes(")
    i_halo = src.index("_reserve_escape_halos(")
    i_snap = src.index("snap_cluster_members(")
    assert i_cmaes < i_snap, (
        "snap AVANT le CMA-ES : l optimiseur le defera, la capa repart au loin")
    assert i_halo < i_snap, (
        "snap AVANT le halo : le halo ecartera la capa qu on vient de coller")


def test_l_inspecteur_repasse_apres_le_snap():
    src = _src()
    i_snap = src.index("snap_cluster_members(")
    assert "_resolve_remaining_conflicts(" in src[i_snap:], (
        "aucun filet apres le snap : un saut peut poser la capa sur un pad")


def test_le_snap_recoit_les_ancrages_et_les_denses():
    src = _src()
    i = src.index("snap_cluster_members(")
    appel = src[i:i + 200]
    assert "figes=" in appel, "connecteurs non proteges du snap"
    assert "denses=" in appel, (
        "halo ignore : le snap reboucherait le canal d escape fine-pitch")


# ---------------------------------------------------------------------------
# Filet — le snap ne peut pas livrer un board pire qu il ne l a recu.
# ---------------------------------------------------------------------------

def test_le_board_pre_snap_est_conserve_et_restaurable():
    """Meme forme de filet que le Geometre.

    Le snap a ete livre SANS filet le 2026-08-29, sur l hypothese que
    « l Inspecteur nettoie » : 0 ERROR -> 1 sur le board STM32, 202 sur
    l Arduino, et un re-tirage complet du placement de seize minutes.
    """
    src = _src()
    i = src.index("snap_cluster_members(")
    apres = src[i:]
    assert "avant_snap = out.read_bytes()" in src[:i] or "avant_snap" in apres, (
        "aucun instantane du board pre-snap : rien a restaurer")
    assert "out.write_bytes(avant_snap)" in apres, (
        "instantane pris mais jamais restaure")


def test_la_restauration_est_conditionnee_a_une_DEGRADATION():
    src = _src()
    i = src.index("snap_cluster_members(")
    apres = src[i:]
    assert "n_err_apres > n_err_avant" in apres, (
        "le filet doit comparer AVANT et APRES, pas tester un seuil absolu : "
        "un board deja imparfait ne doit pas interdire une amelioration")

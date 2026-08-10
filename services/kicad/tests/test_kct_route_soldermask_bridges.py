"""Un boîtier fine-pitch ne peut pas avoir d'ouvertures de masque séparées.

Mesuré le 2026-08-01, Docker, sur le board STM32 (LQFP-48, 31 broches libres) :
**84 ``solder_mask_bridge``**, tous entre pads adjacents du MÊME boîtier, aucun
n'impliquant une piste. Verbatim du DRC officiel :

    "Front solder mask aperture bridges items with different nets"
      Pad 26 [<no net>] de U2 @ (125.776, 112.978)
      Pad 25 [USER_LED] de U2 @ (125.276, 112.978)

Géométrie : au pas de 0,5 mm avec des pads de 0,3 mm, la bande de masque entre
deux ouvertures fait 0,2 mm — sous la largeur minimale de masque. KiCad fusionne
les ouvertures, et comme il traite ``<no net>`` comme un net distinct de tous
les autres, **chaque broche inutilisée crée un pont avec ses deux voisines**.

La pratique industrielle est une ouverture commune par rangée de pads, déclarée
par l'attribut ``allow_soldermask_bridges`` que portent déjà les footprints
officiels KiCad pour les boîtiers denses. Le réglage board
``allow_soldermask_bridges_in_footprints no`` **annule** cet attribut : il
condamne d'avance tout fine-pitch, quelle que soit la qualité du routage.

On n'autorise donc rien de nouveau — on cesse d'ignorer ce que les footprints
déclarent eux-mêmes.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kicad-tools" / "src"))

from tools import kct_route  # noqa: E402


def test_le_reglage_bloquant_est_leve():
    texte = ('(kicad_pcb (setup (pad_to_mask_clearance 0)\n'
             '  (allow_soldermask_bridges_in_footprints no)))')

    obtenu, modifie = kct_route.allow_soldermask_bridges(texte)

    assert modifie is True
    assert "(allow_soldermask_bridges_in_footprints yes)" in obtenu
    assert "(allow_soldermask_bridges_in_footprints no)" not in obtenu


def test_no_op_si_deja_autorise():
    texte = "(kicad_pcb (setup (allow_soldermask_bridges_in_footprints yes)))"

    obtenu, modifie = kct_route.allow_soldermask_bridges(texte)

    assert modifie is False
    assert obtenu == texte


def test_on_ne_fabrique_pas_le_reglage_quand_il_est_absent():
    """Sans bloc exploitable, on ne bricole pas le board."""
    texte = "(kicad_pcb (setup (pad_to_mask_clearance 0)))"

    obtenu, modifie = kct_route.allow_soldermask_bridges(texte)

    assert modifie is False
    assert obtenu == texte


def test_le_reste_du_board_est_intact():
    texte = ('(kicad_pcb (setup (allow_soldermask_bridges_in_footprints no))\n'
             '  (footprint "U2" (pad "1" smd roundrect))\n'
             '  (segment (start 0 0) (end 1 1)))')

    obtenu, _ = kct_route.allow_soldermask_bridges(texte)

    assert '(footprint "U2"' in obtenu
    assert "(segment (start 0 0) (end 1 1))" in obtenu
    assert len(obtenu.splitlines()) == len(texte.splitlines())

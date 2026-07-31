"""Un composant livré hors du contour Edge.Cuts doit au moins être SIGNALÉ.

Défaut trouvé le 2026-07-30 en rejouant la chaîne complète en Docker sur
`examples/stm32-validation` : le placement a livré **U1 à X = 183,37 mm sur une
carte allant de 100 à 160 mm**, soit 23 mm au-delà du bord droit. Le routeur ne
pouvant atteindre un composant hors carte, le net `+5V` (C1 ↔ U1) était
inroutable et le board plafonnait à 64 % au lieu de 100 %.

Deux garde-fous existaient, aucun ne couvrait ce cas :

- le pré-filtre en tête de ``auto_place`` ne déclenche ``place_unplaced`` qu'à
  ``x < -100`` ou ``y < -100``, la sentinelle « jamais placé » ;
- ``_clamp_fixed_refs_to_outline`` ne clampe que les connecteurs ancrés, et
  seulement AVANT l'optimisation.

Rien ne vérifiait le RÉSULTAT. Le placement étant stochastique (GA sans seed),
le défaut est intermittent — ce qui explique une part de la variance de routage
45-89 % observée sur ce board depuis juillet.

Deux réparations ont d'abord été essayées et rejetées, toutes deux par la
mesure :

1. un clamp maison sur le rectangle du contour empile tous les fautifs sur le
   même coin — ``test_placement.py`` l'a attrapé via les conflits ERROR créés ;
2. déléguer à ``place_unplaced``, qui documente pourtant détecter les
   footprints « outside the board bounds », a signalé 15 composants sur 17, en a
   reposé 8 sur une grille locale en laissant les autres en coordonnées page, et
   a placé R2 à x = 61,1 mm sur une carte de 60 mm — le défaut même à corriger.

La réparation retenue (``_repair_off_board``) est ciblée : seuls les refs
réellement classées ``OFF_BOARD`` par ``PlacementAnalyzer`` bougent, chacune
vers la case libre la plus proche de sa position clampée. Elle existe parce que
``PlacementFixer`` n'a **aucun** traitement de ``OFF_BOARD`` (zéro occurrence
dans ``fixer.py``) : l'Inspecteur ne pouvait structurellement pas le résoudre.

Repère, source de l'échec de la voie 2 : ``fp.position`` est board-local,
``outline.vertices`` est en coordonnées page ; seule la soustraction de
``pcb.board_origin`` les réconcilie.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kicad-tools" / "src"))

from tools import placement  # noqa: E402


class _Footprint:
    def __init__(self, reference: str, position: tuple[float, float]) -> None:
        self.reference = reference
        self.position = position


class _Vertex:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


class _Outline:
    def __init__(self, vertices: list[_Vertex]) -> None:
        self.vertices = vertices


class _PCB:
    """Carte 60x40 dont l'origine page est (100, 100)."""

    board_origin = (100.0, 100.0)

    def __init__(self, footprints: list[_Footprint]) -> None:
        self.footprints = footprints


@pytest.fixture()
def carte_60x40(monkeypatch):
    def _installer(footprints: list[_Footprint]) -> None:
        pcb = _PCB(footprints)
        monkeypatch.setattr("kicad_tools.schema.pcb.PCB.load",
                            staticmethod(lambda path: pcb))
        monkeypatch.setattr(
            "kicad_tools.optim.board_outline.extract_board_outline",
            lambda _pcb: _Outline([_Vertex(100, 100), _Vertex(160, 100),
                                   _Vertex(160, 140), _Vertex(100, 140)]),
        )
    return _installer


def test_signale_le_composant_hors_contour(carte_60x40, caplog):
    """Le cas mesuré : U1 à 83,37 en local, sur une carte large de 60 mm."""
    carte_60x40([_Footprint("U1", (83.37, 13.83)),
                 _Footprint("U2", (31.98, 22.81))])

    with caplog.at_level("WARNING"):
        assert placement._outside_outline_refs(Path("b.kicad_pcb")) == 1

    assert "U1" in caplog.text
    assert "INROUTABLES" in caplog.text


def test_muet_quand_tout_est_dans_le_contour(carte_60x40, caplog):
    """Un placement sain ne doit produire aucun avertissement."""
    carte_60x40([_Footprint("U2", (31.98, 22.81)),
                 _Footprint("C1", (45.59, 17.11)),
                 _Footprint("J1", (55.0, 22.0))])

    with caplog.at_level("WARNING"):
        assert placement._outside_outline_refs(Path("b.kicad_pcb")) == 0

    assert caplog.text == ""


def test_ne_modifie_jamais_les_positions(carte_60x40):
    """Détection seulement : aucune réparation, donc aucune dégradation."""
    u1 = _Footprint("U1", (83.37, 13.83))
    carte_60x40([u1])

    placement._outside_outline_refs(Path("b.kicad_pcb"))

    assert u1.position == (83.37, 13.83)


def test_case_libre_evite_l_empilement():
    """Le défaut de la 1re tentative : tout empiler sur le même coin.

    ``_nearest_free_cell`` doit écarter un candidat trop proche d'un centre
    déjà occupé, sinon la réparation recrée les conflits ERROR qu'elle
    prétend éviter.
    """
    bornes = (2.0, 58.0, 2.0, 38.0)

    place = placement._nearest_free_cell((58.0, 38.0), [(58.0, 38.0)], bornes)

    assert place is not None
    assert place != (58.0, 38.0)
    assert 2.0 <= place[0] <= 58.0 and 2.0 <= place[1] <= 38.0
    assert math.dist(place, (58.0, 38.0)) >= placement._OFF_BOARD_SPACING_MM


def test_case_libre_conserve_la_cible_si_elle_est_deja_libre():
    """Ne jamais déplacer plus que nécessaire."""
    bornes = (2.0, 58.0, 2.0, 38.0)

    assert placement._nearest_free_cell((30.0, 20.0), [(5.0, 5.0)], bornes) == (30.0, 20.0)


def test_case_libre_rend_none_quand_tout_est_sature():
    """Aucune case libre : on renonce plutôt que de superposer."""
    bornes = (2.0, 6.0, 2.0, 6.0)
    sature = [(x / 2, y / 2) for x in range(4, 13) for y in range(4, 13)]

    assert placement._nearest_free_cell((4.0, 4.0), sature, bornes) is None


def test_contour_illisible_ne_fait_pas_echouer_le_placement(monkeypatch):
    """Sans contour exploitable, on renonce au contrôle, jamais au board."""
    monkeypatch.setattr("kicad_tools.schema.pcb.PCB.load",
                        staticmethod(lambda path: _PCB([])))
    monkeypatch.setattr(
        "kicad_tools.optim.board_outline.extract_board_outline",
        lambda _pcb: None)

    assert placement._outside_outline_refs(Path("b.kicad_pcb")) == 0

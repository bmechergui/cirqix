"""``write_to_pcb()`` applique ``board_origin`` en double — on le neutralise.

Contradiction interne d'upstream, mesurée le 2026-07-31 sur
`examples/stm32-validation`, en Docker avec le backend C++ :

- ``PlacementOptimizer.from_pcb`` construit ses ``Component`` avec
  ``x=fp.position[0]``, c'est-à-dire du **board-local** ;
- mais il retranslate le polygone de la carte en coordonnées **page**
  (``placement.py:244``), en affirmant en commentaire que « the optimizer adds
  components at their raw *absolute* positions » ;
- et ``update_footprint_position``, qu'appelle ``write_to_pcb()``, documente
  attendre du **relatif à l'origine** et appliquer l'offset elle-même.

Les trois ne peuvent pas être vrais ensemble. L'origine est comptée deux fois.

Effet mesuré, 3 tirages sur 3 : **15 à 16 composants sur 17 hors carte**,
positions livrées à 216-250 mm sur un contour 100-160 mm — soit exactement
``+board_origin``. Seul ``J1`` était épargné, parce qu'ancré et clampé AVANT
l'optimisation. ``kct route`` refusait alors le board (« placement invalid »),
et l'Inspecteur, le CMA-ES puis le halo travaillaient tous sur un board faux.

La correction est **auto-détectante** : elle ne soustrait que si le composant
est hors contour ET que la soustraction l'y ramène. Le jour où le sous-module
corrige sa contradiction, elle devient un no-op silencieux.
"""
from __future__ import annotations

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

    def __init__(self, footprints: list[_Footprint],
                 origine: tuple[float, float] = (100.0, 100.0)) -> None:
        self.footprints = footprints
        self.board_origin = origine


@pytest.fixture()
def contour(monkeypatch):
    monkeypatch.setattr(
        "kicad_tools.optim.board_outline.extract_board_outline",
        lambda _pcb: _Outline([_Vertex(100, 100), _Vertex(160, 100),
                               _Vertex(160, 140), _Vertex(100, 140)]),
    )


def test_retire_l_origine_comptee_en_double(contour):
    """Le cas mesuré : U2 livré à 116,21 en local sur un contour 0..60."""
    u2 = _Footprint("U2", (116.21, 111.76))
    c13 = _Footprint("C13", (150.37, 119.25))

    n = placement._normalize_origin_after_write(_PCB([u2, c13]), skip=[])

    assert n == 2
    assert u2.position == pytest.approx((16.21, 11.76))
    assert c13.position == pytest.approx((50.37, 19.25))


def test_ne_touche_jamais_un_composant_deja_correct(contour):
    """Un placement sain doit traverser la normalisation intact."""
    sain = _Footprint("C1", (45.59, 17.11))

    n = placement._normalize_origin_after_write(_PCB([sain]), skip=[])

    assert n == 0
    assert sain.position == (45.59, 17.11)


def test_no_op_si_le_sous_module_est_corrige(contour):
    """Auto-détectante : plus de double offset, plus rien à faire.

    C'est ce qui rend le correctif sûr dans la durée — il ne devient jamais
    une correction en trop.
    """
    pcb = _PCB([_Footprint("U1", (10.0, 10.0)), _Footprint("U2", (50.0, 30.0))])

    assert placement._normalize_origin_after_write(pcb, skip=[]) == 0


def test_ne_deplace_pas_un_composant_que_la_soustraction_n_aide_pas(contour):
    """Hors contour ET toujours hors après soustraction → on ne touche pas.

    Un vrai composant hors carte n'est pas un problème de repère : le
    normaliser au hasard masquerait le défaut au lieu de le signaler.
    """
    perdu = _Footprint("X1", (500.0, 500.0))

    n = placement._normalize_origin_after_write(_PCB([perdu]), skip=[])

    assert n == 0
    assert perdu.position == (500.0, 500.0)


def test_les_connecteurs_ancres_sont_ignores(contour):
    """``J1`` est clampé AVANT l'optimisation : ses coordonnées sont déjà justes.

    C'est d'ailleurs pour ça qu'il était le seul composant correct sur les
    boards mesurés.
    """
    j1 = _Footprint("J1", (155.0, 122.0))

    n = placement._normalize_origin_after_write(_PCB([j1]), skip=["J1"])

    assert n == 0
    assert j1.position == (155.0, 122.0)


def test_origine_nulle_ne_declenche_rien(contour):
    """Sans offset d'origine, il n'y a rien à normaliser."""
    fp = _Footprint("U1", (500.0, 500.0))

    n = placement._normalize_origin_after_write(_PCB([fp], origine=(0.0, 0.0)),
                                                skip=[])

    assert n == 0

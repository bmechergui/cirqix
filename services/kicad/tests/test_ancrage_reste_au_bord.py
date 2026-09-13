"""Le clamp des ancrages ne défait pas la règle des bords (2026-09-13).

Mesuré sur le banc, phase 1 avec la règle « bord le plus proche » :
presque chaque connecteur ancré au bord était « reposé » plus loin par
`_position_libre_pour_ancrage`, qui jugeait la collision contre TOUS les
footprints — y compris ceux de la grille initiale que le génétique déplace
ensuite — et testait les bornes sur l'ORIGINE du footprint, pas sur son corps :
J10 (carte-06) finissait 4,6 mm hors carte, `copper_edge_clearance` trois
tirages sur trois.

Ce que ces tests discriminent :
  - un composant MOBILE sous le point d'ancrage ne déplace pas le connecteur ;
  - deux ANCRAGES qui se recouvrent sont séparés, corps dans le contour ;
  - le corps d'un connecteur reposé reste dans le contour, jamais son origine seule.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
for chemin in (_SERVICE_ROOT, _SERVICE_ROOT / "kicad-tools" / "src"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

from kicad_tools.schema.pcb import PCB  # noqa: E402
from tools import placement as placement_mod  # noqa: E402
from tools.contour_et_bords import ancrer_connecteurs_au_bord  # noqa: E402

_FIXTURE = _SERVICE_ROOT / "examples" / "carte-01-diviseur" / "expected" / "placement.kicad_pcb"
pytestmark = pytest.mark.skipif(not _FIXTURE.exists(), reason="fixture carte-01 absente")


@pytest.fixture
def pcb(tmp_path: Path):
    f = tmp_path / "b.kicad_pcb"
    shutil.copy(_FIXTURE, f)
    return PCB.load(str(f))


def _fp(pcb, ref):
    return next(fp for fp in pcb.footprints if fp.reference == ref)


def _corps(fp):
    b = placement_mod._boite_locale_fp(fp)
    return (fp.position[0] + b[0], fp.position[1] + b[1], fp.position[0] + b[2], fp.position[1] + b[3])


def test_un_composant_mobile_sous_l_ancrage_ne_deplace_pas_le_connecteur(pcb):
    ancrer_connecteurs_au_bord(pcb)          # J1 au milieu du bord gauche
    j1 = _fp(pcb, "J1")
    # Une resistance MOBILE posee exactement sur J1 : c est la grille du generateur.
    _fp(pcb, "R1").position = j1.position
    avant = j1.position
    reposes = placement_mod._clamp_fixed_refs_to_outline(pcb, ["J1"])
    assert reposes == [] and j1.position == avant


def test_deux_ancrages_qui_se_recouvrent_sont_separes_dans_le_contour(pcb):
    # On promeut R1 en connecteur et on le pose SUR J1.
    _fp(pcb, "R1").reference = "J2"
    ancrer_connecteurs_au_bord(pcb)
    _fp(pcb, "J2").position = _fp(pcb, "J1").position
    reposes = placement_mod._clamp_fixed_refs_to_outline(pcb, ["J1", "J2"])
    assert reposes, "l un des deux doit bouger"
    a, b = _corps(_fp(pcb, "J1")), _corps(_fp(pcb, "J2"))
    assert not (a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]), "plus de recouvrement"
    for c in (a, b):   # contour 25 x 20, marge de clamp 2 mm
        assert c[0] >= 2.0 - 1e-6 and c[2] <= 23.0 + 1e-6 and c[1] >= 2.0 - 1e-6 and c[3] <= 18.0 + 1e-6


def test_le_corps_reste_dans_le_contour_pas_seulement_l_origine(pcb):
    """Le cas J10 : ancre au bord bas, un autre ancrage dessus ; le repos ne
    doit pas franchir le bord (l origine d un en-tete est sur sa pastille 1,
    son corps s etend de 9,4 mm au-dela)."""
    _fp(pcb, "R1").reference = "J2"
    j1, j2 = _fp(pcb, "J1"), _fp(pcb, "J2")
    j2.position = (12.5, 20.0 - 2.0 - 9.39)   # J2 colle au bord bas
    j1.position = j2.position                  # J1 par-dessus
    placement_mod._clamp_fixed_refs_to_outline(pcb, ["J2", "J1"])
    for fp in (j1, j2):
        c = _corps(fp)
        assert c[3] <= 18.0 + 1e-6 and c[1] >= 2.0 - 1e-6, f"{fp.reference} corps hors contour : {c}"

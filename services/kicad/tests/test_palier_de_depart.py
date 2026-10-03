"""Un placement gardé se reroute à partir du palier déjà atteint (validé le 2026-10-02).

Banc dense du 2026-10-01 : carte-09 atteint 97 % à 6 couches ; la règle des
95 % garde le placement, et le banc le reroute — mais chaque reroutage
repartait de 2 couches et refaisait toute l'escalade (~25 min chacun, 82 min
au total, 100 % au 3e). `palier_depart` fait commencer l'échelle au palier où
le placement avait déjà atteint 95 %.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402


def test_les_paliers_inferieurs_sont_sautes():
    assert R._paliers_a_partir_de([2, 4, 4, 4, 6, 6, 6, 8], 6) == [6, 6, 6, 8]


def test_sans_palier_de_depart_l_echelle_est_intacte():
    assert R._paliers_a_partir_de([2, 4, 6], None) == [2, 4, 6]


def test_un_palier_au_dessus_du_plafond_garde_le_plafond():
    assert R._paliers_a_partir_de([2, 4, 4], 8) == [4]


def test_le_champ_est_valide():
    req = R.RouteAutoRequest(kicad_pcb_b64="eA==", layers=8, palier_depart=6)
    assert req.palier_depart == 6
    with pytest.raises(ValueError):
        R.RouteAutoRequest(kicad_pcb_b64="eA==", layers=8, palier_depart=5)


def test_route_auto_applique_le_palier_de_depart():
    src = inspect.getsource(R.route_auto)
    assert "essais = _paliers_a_partir_de(essais, req.palier_depart)" in src

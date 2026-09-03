"""Une carte de 100 composants ne tient pas dans 200 mm.

⚠️ Mesure du 2026-08-28, banc complet. Six cartes sur sept passent la chaine
entiere ; la septieme echoue AVANT le placement :

    stm32-100   ECHEC   1 validation error for SchematicRequest
                        board_width_mm

`_dimensions` deduit la taille de l encombrement REEL des boitiers et demande
208 x 156 mm pour 100 composants. Les modeles la refusaient : `le=200.0`.

Ce plafond n a aucune justification physique. Le procede standard de JLCPCB
accepte jusqu a 400 x 500 mm, et le generateur se plafonne lui-meme a 400 mm de
cote. 200 etait un chiffre rond, pose sans mesure, qui rendait TOUTE carte de
plus de ~90 composants impossible a generer.

⚠️ On garde un plafond : sans borne, une taille aberrante — issue d un calcul
faux ou d une entree hostile — produirait un board de plusieurs metres que le
routeur mettrait des heures a traiter. 500 mm est la borne du fabricant, pas un
chiffre rond de plus.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers.pcb import PcbRequest  # noqa: E402
from routers.schematic import SchematicRequest  # noqa: E402

_MODELES = (SchematicRequest, PcbRequest)

# ⚠️ Les champs obligatoires DOIVENT etre fournis. Sans eux, chaque `raises`
# passait pour la mauvaise raison — l exception venait du champ manquant, pas
# du plafond — et les tests « refuse » etaient des faux verts.
_MINIMUM = {
    "components": [{"ref": "R1", "value": "1k", "symbol": "Device:R",
                    "footprint": "Resistor_SMD:R_0603_1608Metric"}],
    "nets": [],
}


def _req(modele, **taille):
    return modele(**_MINIMUM, **taille)



class TestPlafond:
    @pytest.mark.parametrize("modele", _MODELES)
    def test_une_carte_de_100_composants_est_acceptee(self, modele):
        # 208 x 156 mm : la taille exacte que `_dimensions` demande.
        r = _req(modele, board_width_mm=208.0, board_height_mm=156.0)
        assert r.board_width_mm == 208.0

    @pytest.mark.parametrize("modele", _MODELES)
    def test_le_maximum_du_fabricant_est_accepte(self, modele):
        r = _req(modele, board_width_mm=500.0, board_height_mm=500.0)
        assert r.board_height_mm == 500.0

    @pytest.mark.parametrize("modele", _MODELES)
    def test_au_dela_du_fabricant_c_est_refuse(self, modele):
        # Sans borne, une taille aberrante ferait router pendant des heures.
        with pytest.raises(Exception):
            _req(modele, board_width_mm=501.0)

    @pytest.mark.parametrize("modele", _MODELES)
    def test_le_plancher_est_conserve(self, modele):
        with pytest.raises(Exception):
            _req(modele, board_width_mm=9.0)

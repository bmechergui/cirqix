"""Un connecteur va au bord vers lequel POINTE le rayon de ses broches.

⚠️ Mesure du 2026-09-23, `carte-10`. `_position_au_bord` classe les quatre
bords par DISTANCE et prend le plus proche. Sur une carte resserrée, les quatre
bords sont presque équidistants : le critère perd son sens, tous les
connecteurs sortent du même côté, et il reste un vide entre le circuit et eux.

Première tentative — resserrer le cadre sur la frontière du circuit — MESURÉE
ET RÉFUTÉE le même jour : aucun gain de taille, et les connecteurs se sont
entassés sur le bord droit, deux se chevauchant, les trois autres bords vides.
Ce n'est pas le cadre qu'il fallait changer, c'est la règle de choix du bord.

RÈGLE : quand l'appelant connaît la DIRECTION (le rayon des broches), le bord
retenu est celui vers lequel ce rayon pointe. À direction égale, le plus
proche. Sans direction, le comportement ne change pas — `_coller_les_ancrages_
au_bord` glisse toujours au plus court chemin, et c'est sa règle propre.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools import placement as P  # noqa: E402

# Une carte large et basse : le bord HAUT est tout proche, les bords gauche et
# droit sont loin. C'est la configuration qui piège le critere de distance.
BORNES = (0.0, 100.0, 0.0, 20.0)
BOITE = (-2.5, -1.3, 2.5, 1.3)      # un connecteur de 5 x 2,6 mm


class TestSansDirection:
    """Le comportement existant ne bouge pas : au plus proche."""

    def test_il_glisse_au_bord_le_plus_proche(self):
        # Pose a 2 mm du bord haut, 50 mm des bords lateraux.
        pos = P._position_au_bord((50.0, 3.3), BOITE, BORNES, [])
        assert abs(pos[1] - (0.0 + 1.3)) < 0.01, "le bord HAUT est le plus proche"


class TestAvecDirection:
    """La direction commande, meme quand un autre bord est bien plus proche."""

    def test_un_rayon_vers_la_droite_donne_le_bord_DROIT(self):
        pos = P._position_au_bord((50.0, 3.3), BOITE, BORNES, [],
                                  direction=0.0)
        assert abs(pos[0] - (100.0 - 2.5)) < 0.01, (
            "le rayon pointe vers +x : le connecteur va au bord DROIT, meme si "
            "le bord haut est a 2 mm et le droit a 50")

    def test_un_rayon_vers_la_gauche_donne_le_bord_GAUCHE(self):
        pos = P._position_au_bord((50.0, 3.3), BOITE, BORNES, [],
                                  direction=math.pi)
        assert abs(pos[0] - (0.0 + 2.5)) < 0.01

    def test_un_rayon_vers_le_bas_donne_le_bord_BAS(self):
        # y descend en KiCad : +pi/2 pointe vers le BAS de la carte.
        pos = P._position_au_bord((50.0, 3.3), BOITE, BORNES, [],
                                  direction=math.pi / 2.0)
        assert abs(pos[1] - (20.0 - 1.3)) < 0.01

    def test_un_bord_occupe_fait_glisser_LE_LONG_de_ce_bord(self):
        # Le bord droit est pris au milieu : on reste a droite, on descend.
        occupe = (100.0 - 5.0, 3.3 - 1.3, 100.0, 3.3 + 1.3)
        pos = P._position_au_bord((50.0, 3.3), BOITE, BORNES, [occupe],
                                  direction=0.0)
        assert abs(pos[0] - (100.0 - 2.5)) < 0.01, (
            "on ne change pas de bord parce qu'il est occupe : on glisse")
        assert abs(pos[1] - 3.3) > 1.0, "il doit avoir glisse le long du bord"


class TestLaGraineDonneLaDirection:
    """Une regle correcte jamais appelee est indistinguable d'une regle absente."""

    def test_la_graine_passe_la_direction(self):
        source = (RACINE / "tools" / "graine_etoile.py").read_text(encoding="utf-8")
        lignes = [l for l in source.splitlines() if not l.lstrip().startswith("#")]
        code = chr(10).join(lignes)
        debut = code.index("def _poser_les_connecteurs")
        fin = code.index(chr(10) + "def ", debut + 1)
        corps = code[debut:fin]
        assert "direction=" in corps, (
            "la graine connait l'angle du rayon : elle doit le PASSER, sinon "
            "le bord reste choisi par la distance")

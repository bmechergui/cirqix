"""Un plan de masse doit porter du CUIVRE, pas seulement un contour.

Trouve le 2026-08-23 en mesurant la variante « confier GND au plan » demandee
par l utilisateur : 17 connexions manquantes, et pas seulement sur le
fine-pitch — C1, C2, C3, C12..C16, U1, de gros pads qu un plan atteindrait
sans peine. D ou la verification, sans appel :

    zones declarees : 3
    filled_polygon  : 0

Nos plans etaient des CONTOURS VIDES. `_specctra_roundtrip` appelle bien
`ZONE_FILLER.Fill`, mais il s execute AVANT que les plans soient coules : rien
ne remplissait donc les notres.

L ordre actuel masquait le defaut — les pistes relient tout, donc le DRC ne
signalait rien. Un plan vide ne casse pas la connectivite, il ne fournit
simplement AUCUN blindage, ce que l utilisateur avait demande explicitement.

⚠️ Ne pas se contenter du drapeau `SetIsFilled(True)` : il DECLARE la zone
remplie sans calculer le moindre polygone. Seul `ZONE_FILLER.Fill` produit du
cuivre. Confondre les deux, c est refabriquer le probleme sous une autre forme.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402
from tools import routing_pcbnew_runner  # noqa: E402


class TestOperationDuRunner:
    def test_le_runner_expose_le_remplissage(self):
        assert hasattr(routing_pcbnew_runner, "_fill_zones")

    def test_le_remplissage_est_dispatche(self):
        source = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
            encoding="utf-8"
        )
        assert '"fill_zones"' in source

    def test_le_remplissage_appelle_le_filler_pas_le_drapeau(self, tmp_path):
        appels: list[str] = []

        class Zone:
            def SetIsFilled(self, _v):
                appels.append("drapeau")

        class Filler:
            def __init__(self, _b):
                pass

            def Fill(self, _zones):
                appels.append("filler")
                return True

        class Board:
            def Zones(self):
                return [Zone()]

        class FakePcbnew:
            ZONE_FILLER = Filler

            @staticmethod
            def LoadBoard(_p):
                return Board()

            @staticmethod
            def SaveBoard(p, _b):
                Path(p).write_bytes(b"REMPLI")

        sortie = tmp_path / "out.kicad_pcb"
        routing_pcbnew_runner._fill_zones(
            FakePcbnew, {"pcb": "in.kicad_pcb", "output": str(sortie)}
        )
        assert "filler" in appels, "ZONE_FILLER.Fill n a pas ete appele"
        assert sortie.read_bytes() == b"REMPLI"


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_remplissage_suit_la_coulee(self):
        # Remplir AVANT de couler ne remplirait rien : la zone n existe pas
        # encore. On regarde le CORPS de l enveloppe, pas le fichier — comparer
        # des positions globales comparerait les DEFINITIONS de fonctions.
        debut = self.SOURCE.index('@router.post("/route/auto"')
        corps = self.SOURCE[debut:]
        # ⚠️ On comparait deux positions de TEXTE. Depuis que la coulee est
        # imbriquee — `_fill_zones(_add_ground_planes(...))` — le remplissage
        # s ecrit AVANT dans la ligne tout en s executant APRES. Le test
        # echouait sur un code juste. On verifie l imbrication elle-meme.
        assert "_fill_zones(_add_ground_planes(" in corps, (
            "le remplissage doit envelopper la coulee : une zone non remplie "
            "n est qu un contour, dont le routeur ne tient aucun compte")

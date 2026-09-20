"""Les tirages de placement se classent ENTRE EUX sur les croisements du chevelu.

⚠️ Demande de l utilisateur le 2026-09-20 : « une solution qui marche sur tout
type de carte ». Un seuil (« bon si X < 42 ») serait une calibration sur nos
onze cartes. Ici on ne compare la carte qu a elle-meme : parmi ses tirages,
celui qui impose le moins de croisements au routeur passe devant.

Mesure qui motive la regle (rejeu du 2026-09-20) : carte-03, 07, 09 et 10
re-placees rendaient des boards que Freerouting ne routait pas (tirages figes
a ~0 %), alors que leurs placements du 14/09 routaient a 100 %. `fil_mm`
(longueur de fil) ne le voyait pas : un placement court peut etre
non planaire.

Critere NATIF : `kicad_tools.optim.fom_geometry.crossing_count` — croisements
inter-nets d une projection en etoile, 0 = planaire. Les nets confies au plan
(GND…) sont retires AVANT le compte : ils ne se routent pas, leurs croisements
ne genent personne.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools import placement as P  # noqa: E402


class TestClassement:
    def test_les_conflits_priment(self):
        assert P._placement_meilleur({"conflits_restants": 0, "croisements": 50.0, "fil_mm": 900.0},
                                     {"conflits_restants": 1, "croisements": 0.0, "fil_mm": 100.0})

    def test_a_conflits_egaux_moins_de_croisements_gagne(self):
        assert P._placement_meilleur({"conflits_restants": 0, "croisements": 3.0, "fil_mm": 900.0},
                                     {"conflits_restants": 0, "croisements": 12.0, "fil_mm": 100.0})
        assert not P._placement_meilleur({"conflits_restants": 0, "croisements": 12.0, "fil_mm": 100.0},
                                         {"conflits_restants": 0, "croisements": 3.0, "fil_mm": 900.0})

    def test_a_croisements_egaux_le_fil_departage(self):
        assert P._placement_meilleur({"conflits_restants": 0, "croisements": 3.0, "fil_mm": 100.0},
                                     {"conflits_restants": 0, "croisements": 3.0, "fil_mm": 900.0})

    def test_un_compte_inconnu_ne_gagne_jamais(self):
        # Sans mesure, on ne prefere pas — comme pour le fil.
        assert not P._placement_meilleur({"conflits_restants": 0, "croisements": None, "fil_mm": 10.0},
                                         {"conflits_restants": 0, "croisements": 3.0, "fil_mm": 900.0})
        assert P._placement_meilleur({"conflits_restants": 0, "croisements": 3.0, "fil_mm": 900.0},
                                     {"conflits_restants": 0, "croisements": None, "fil_mm": 10.0})

    def test_ancien_resultat_sans_croisements_reste_comparable(self):
        # Deux tirages sans la cle : le fil departage, comme avant.
        assert P._placement_meilleur({"conflits_restants": 0, "fil_mm": 100.0},
                                     {"conflits_restants": 0, "fil_mm": 900.0})


class TestMesure:
    def test_les_nets_de_plan_sont_retires_avant_le_compte(self, monkeypatch):
        from kicad_tools.optim import fom_features as FF
        feats = FF.BoardFeatures()
        feats.net_names = {1: "GND", 2: "SDA", 3: "SCL"}
        feats.nets_to_pads = {1: ["g1", "g2"], 2: ["a1", "a2"], 3: ["b1", "b2"]}
        vus = {}

        def faux_compte(f):
            vus["nets"] = set(f.nets_to_pads)
            return 7.0

        monkeypatch.setattr(P, "_charger_features", lambda chemin: feats)
        monkeypatch.setattr(P, "_crossing_count", faux_compte)
        assert P._croisements_du_placement(Path("x.kicad_pcb")) == 7.0
        assert vus["nets"] == {2, 3}

    def test_une_mesure_qui_leve_rend_none(self, monkeypatch):
        def boum(chemin):
            raise RuntimeError("board illisible")
        monkeypatch.setattr(P, "_charger_features", boum)
        assert P._croisements_du_placement(Path("x.kicad_pcb")) is None


BANC = RACINE / "examples" / "carte-05-capteur-i2c" / "expected" / "placement.kicad_pcb"


class TestSurUnVraiBoard:
    """⚠️ Les deux mesures rendaient None SANS BRUIT : `PCB` n etait pas
    importe dans le module, `NameError` etait avale — `fil_mm` n a jamais
    departage un tirage depuis le 2026-08-29. Une mesure qui echoue comme
    « pas de mesure » ne se voit qu en la lisant sur un vrai board."""

    def test_les_croisements_se_mesurent(self):
        import pytest
        pytest.importorskip("kicad_tools")
        if not BANC.is_file():
            pytest.skip("board du banc absent")
        x = P._croisements_du_placement(BANC)
        assert x is not None and x >= 0

    def test_le_fil_se_mesure(self):
        import pytest
        pytest.importorskip("kicad_tools")
        if not BANC.is_file():
            pytest.skip("board du banc absent")
        f = P._longueur_de_fil_mm(BANC)
        assert f is not None and f > 0


class TestCablage:
    SOURCE = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_chaque_tirage_porte_ses_croisements(self):
        corps = self.SOURCE[self.SOURCE.index("def _auto_place_une_fois("):]
        assert '"croisements": _croisements_du_placement(out)' in corps

    def test_le_critere_est_natif(self):
        assert "from kicad_tools.optim.fom_geometry import crossing_count" in self.SOURCE
        assert "from kicad_tools.optim.fom_features import extract_features" in self.SOURCE

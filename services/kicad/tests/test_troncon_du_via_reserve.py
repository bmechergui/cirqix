"""Le via GND reserve avant routage est declare au routeur AVEC son troncon
pastille -> via, protege lui aussi.

Mesure du 2026-09-11 (carte-08, campagne 1789158962) : « Via [GND] on F.Cu -
B.Cu <-> Pad 23 [GND] of U1 » separes au DRC final. Le via etait declare
`(type protect)`, le troncon ne l etait pas : le routeur posait un signal
dans le couloir de 1,2 mm, et la repose du troncon echouait. Le pad restait
orphelin du plan alors que son via etait la.

Second defaut, meme carte, a chaque tirage : « Pad 1 [GND] of U2 <-> Zone
[GND] on F.Cu » — la pastille est SUR le plan mais le relief thermique ne la
rejoint pas (« le cuivre est la, la connexion non »). Elle passe en
connexion pleine, comme une pastille affamee.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


class TestTroncon:
    VIA = {"ref": "U1", "pad": "23", "pad_x": 10_000_000, "pad_y": 20_000_000,
           "via_x": 11_200_000, "via_y": 20_000_000, "layer": 0,
           "layer_nom": "F.Cu", "net": 1, "net_nom": "GND"}

    def test_le_troncon_est_declare_protege_avec_le_via(self):
        bloc = R._bloc_wiring([self.VIA], "GND")
        assert '(via "%s" 11200.0 -20000.0 (net GND) (type protect))' % R._PADSTACK_VIA in bloc
        assert "(wire (path F.Cu 250.0 10000.0 -20000.0 11200.0 -20000.0) (net GND) (type protect))" in bloc

    def test_sans_position_de_pastille_seul_le_via_est_declare(self):
        bloc = R._bloc_wiring([{"via_x": 0, "via_y": 0, "net": "SIG1"}], "GND")
        assert "(wire" not in bloc and "(via" in bloc

    def test_sans_nom_de_couche_pas_de_troncon_devine(self):
        via = dict(self.VIA)
        del via["layer_nom"]
        assert "(wire" not in R._bloc_wiring([via], "GND")

    def test_le_runner_rend_le_nom_de_la_couche(self):
        src = (_SERVICE / "tools" / "routing_pcbnew_runner.py").read_text(encoding="utf-8")
        i = src.index("def _plan_escape")
        assert '"layer_nom": board.GetLayerName(pad.GetLayer())' in src[i:i + 4000]


class TestPastilleSurLePlanSansRaccord:
    RAPPORT = {"violations": [], "unconnected_items": [
        {"items": [{"description": "Pad 1 [GND] of U2 on F.Cu"},
                   {"description": "Zone [GND] on F.Cu, priority 1"}]},
        {"items": [{"description": "Pad 30 [EXT3_1] of U1 on F.Cu"},
                   {"description": "PTH pad 1 [EXT3_1] of J13"}]},
        {"items": [{"description": "Via [GND] on F.Cu - B.Cu"},
                   {"description": "Pad 23 [GND] of U1 on F.Cu"}]},
    ]}

    def test_la_pastille_separee_de_sa_zone_est_promue(self):
        assert R._pastilles_sur_le_plan_sans_raccord(self.RAPPORT) == [("U2", "1")]

    def test_les_affamees_et_les_sans_raccord_sont_reunies(self):
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(R._reparer_reliefs_affames).splitlines())
        assert "_pastilles_sur_le_plan_sans_raccord(" in code

    def test_la_garde_compte_aussi_les_liaisons_manquantes(self):
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(R._reparer_reliefs_affames).splitlines())
        assert "_secours_est_meilleur(" in code

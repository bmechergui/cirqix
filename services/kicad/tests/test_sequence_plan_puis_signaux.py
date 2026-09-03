"""La sequence demandee par l utilisateur, et son repli.

    ① le plan prend GND en charge — retire de la netlist du DSN
    ② le routeur ne route que les SIGNAUX
    ③ coulee finale, remplie
    ④ les broches GND non reliees recoivent une sortie fine + un via

Elle divise le cuivre pose par deux (~105 segments contre 214) : les pistes GND
que le routeur tirait deviennent redondantes des que le plan est coule.

⚠️ Elle n aboutit pas toujours. Sur le board STM32, 1 a 3 broches fine-pitch du
LQFP-48 restent orphelines — l espace libre autour d elles (0,318 mm) est
inferieur a ce qu un via reclame (0,500 mm), et le trajet vers la zone degagee
doit traverser cette zone saturee.

Une carte non connectee ne part pas en fabrication. Le repli refait donc le
routage EN INCLUANT GND, qui relie tout par des pistes : plus de cuivre, mais
une carte complete. Mesure du 2026-08-23, chaine reelle :

    ① 18 broches confiees au plan -> 91 %, 2 orphelines
    ② repli                        -> 100 %, 0 manquante

⚠️ Le repli n intervient QUE si des broches sont restees orphelines : la
sequence est toujours essayee d abord, et gardee des qu elle aboutit.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


class TestSequenceActive:
    def test_gnd_est_confie_au_plan(self):
        assert "GND" in routing_router._NETS_CONFIES_AU_PLAN


class TestComptageDesOrphelines:
    def test_compte_les_broches_signalees_par_le_drc(self, monkeypatch):
        monkeypatch.setattr(routing_router, "_rapport_drc", lambda _b: {
            "unconnected_items": [
                {"items": [{"description": "Pad 35 [GND] of U2 on F.Cu"},
                           {"description": "Zone [GND] on F.Cu, priority 0"}]},
                {"items": [{"description": "Pad 47 [GND] of U2 on F.Cu"},
                           {"description": "Zone [GND] on F.Cu, priority 0"}]},
            ]})
        assert routing_router._gnd_orphelines(b"BOARD") == 2

    def test_une_mesure_impossible_ne_declenche_pas_le_repli(self, monkeypatch):
        # Sans verdict, on garde ce que la sequence a produit : un repli coute
        # un routage complet, on ne le paie pas sur une incertitude.
        def leve(_b):
            raise RuntimeError("drc indisponible")

        monkeypatch.setattr(routing_router, "_rapport_drc", leve)
        assert routing_router._gnd_orphelines(b"BOARD") == 0


class TestRepli:
    def test_le_repli_restaure_le_reglage_meme_en_cas_d_echec(self, monkeypatch):
        # `_NETS_CONFIES_AU_PLAN` est un etat GLOBAL : le laisser a () apres un
        # repli desactiverait silencieusement la sequence pour tous les appels
        # suivants du processus.
        avant = routing_router._NETS_CONFIES_AU_PLAN

        def leve(_r):
            raise RuntimeError("service injoignable")

        monkeypatch.setattr(routing_router, "_route_auto_once", leve)
        req = routing_router.RouteAutoRequest(kicad_pcb_b64="", layers=2)
        assert routing_router._router_en_incluant_gnd(b"BOARD", req, 60) is None
        assert routing_router._NETS_CONFIES_AU_PLAN == avant

    def test_un_repli_en_echec_ne_detruit_pas_le_board(self, monkeypatch):
        # Rendre None, jamais un board vide : l appelant garde le resultat de la
        # sequence. Un repli qui echoue ne doit pas detruire ce qu il devait
        # ameliorer.
        monkeypatch.setattr(routing_router, "_route_auto_once",
                            lambda _r: routing_router.RouteAutoResponse(
                                kicad_pcb_b64="", skipped=True, routed_percent=0))
        req = routing_router.RouteAutoRequest(kicad_pcb_b64="", layers=2)
        assert routing_router._router_en_incluant_gnd(b"BOARD", req, 60) is None


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_repli_suit_le_fanout(self):
        # Replier AVANT la reparation condamnerait la sequence : on n aurait
        # jamais laisse sa chance aux vias d echappement.
        debut = self.SOURCE.index('@router.post("/route/auto"')
        corps = self.SOURCE[debut:]
        assert corps.index("_router_en_incluant_gnd(") > corps.index("_fanout_pads_isolees(")

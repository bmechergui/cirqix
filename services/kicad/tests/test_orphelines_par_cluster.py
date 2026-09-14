"""Une broche de plan isolee se cache derriere une description SANS pastille.

Mesure du 2026-09-14, carte-10 (98 %, 6 couches, 1 connexion manquante) : le
DRC du service disait « Zone [GND] on F.Cu <-> Zone [GND] on B.Cu », celui de
kicad-cli avec recoulee « Track [GND] 1,2 mm <-> Track [GND] 1,2 mm » — deux
descriptions du MEME defaut : la broche U1.8, son troncon, son via et le petit
ilot de B.Cu qui porte ce via forment un amas coupe du plan principal. Aucune
des deux descriptions ne nomme la pastille ; aucun item n est POSE sur elle
(`_pastilles_sous_les_items` cherche a 0,05 mm). Le fanout ne visait rien, le
repli GND cible ne se declenchait pas, et la carte restait a 98 % de 2 a 8
couches — l escalade ne peut rien pour une broche que personne ne designe.

La regle : quand un item d un net de plan ne designe aucune pastille, on
demande a pcbnew QUELLES pastilles du net sont HORS de son amas principal.
C est la connectivite reelle qui designe l orpheline, pas la description.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402
from tools import routing_pcbnew_runner as runner  # noqa: E402

_BOARD = b'(kicad_pcb (version 20240108) (net 0 "") (net 1 "GND"))'


def _rapport(*descriptions: str) -> dict:
    return {"unconnected_items": [{"items": [
        {"description": d, "pos": {"x": 100.0 + i, "y": 50.0}} for i, d in enumerate(descriptions)
    ]}]}


class TestDetection:
    def test_une_paire_zone_zone_gnd_designe_les_pastilles_hors_de_l_amas_principal(self, monkeypatch):
        monkeypatch.setattr(R, "_positions_des_pastilles", lambda b, nets: {("U1", "8"): (152.66, 99.25)})
        monkeypatch.setattr(R, "_pads_hors_du_cluster_principal",
                            lambda b, nets: [("U1", "8")] if "GND" in nets else [])
        rap = _rapport("Zone [GND] on F.Cu, priority 1", "Zone [GND] on B.Cu, priority 1")
        assert R._pads_isolees_du_plan(rap, _BOARD) == [("U1", "8")]

    def test_une_paire_track_track_gnd_aussi(self, monkeypatch):
        monkeypatch.setattr(R, "_positions_des_pastilles", lambda b, nets: {})
        monkeypatch.setattr(R, "_pads_hors_du_cluster_principal", lambda b, nets: [("U1", "8")])
        rap = _rapport("Track [GND] on F.Cu, length 1.2000 mm", "Track [GND] on F.Cu, length 1.2000 mm")
        assert R._pads_isolees_du_plan(rap, _BOARD) == [("U1", "8")]

    def test_un_net_de_signal_ne_declenche_pas_la_recherche(self, monkeypatch):
        appels = []
        monkeypatch.setattr(R, "_positions_des_pastilles", lambda b, nets: {})
        monkeypatch.setattr(R, "_pads_hors_du_cluster_principal",
                            lambda b, nets: appels.append(nets) or [])
        rap = _rapport("Track [SIG] on F.Cu, length 3 mm", "Track [SIG] on B.Cu, length 2 mm")
        assert R._pads_isolees_du_plan(rap, _BOARD) == []
        assert appels == []

    def test_sans_board_rien_ne_change(self):
        rap = _rapport("Zone [GND] on F.Cu, priority 1", "Zone [GND] on B.Cu, priority 1")
        assert R._pads_isolees_du_plan(rap) == []

    def test_une_panne_de_pcbnew_ne_leve_pas(self, monkeypatch):
        monkeypatch.setattr(R, "_positions_des_pastilles", lambda b, nets: {})
        monkeypatch.setattr(R, "_run_pcbnew_operation", lambda payload: (_ for _ in ()).throw(RuntimeError("boom")))
        rap = _rapport("Zone [GND] on F.Cu, priority 1", "Zone [GND] on B.Cu, priority 1")
        assert R._pads_isolees_du_plan(rap, _BOARD) == []

    def test_les_pastilles_deja_designees_ne_sont_pas_doublees(self, monkeypatch):
        monkeypatch.setattr(R, "_positions_des_pastilles", lambda b, nets: {("U1", "8"): (100.0, 50.0)})
        monkeypatch.setattr(R, "_pads_hors_du_cluster_principal", lambda b, nets: [("U1", "8")])
        rap = _rapport("Track [GND] on F.Cu, length 1.2000 mm", "Via [GND] on F.Cu - B.Cu")
        assert R._pads_isolees_du_plan(rap, _BOARD) == [("U1", "8")]


class TestCablage:
    def test_le_runner_expose_l_operation(self):
        corps = inspect.getsource(runner.main)
        assert '"pads_hors_cluster_principal"' in corps
        assert callable(getattr(runner, "_pads_hors_cluster_principal", None))

    def test_le_service_demande_bien_cette_operation(self):
        corps = inspect.getsource(R._pads_hors_du_cluster_principal)
        assert '"pads_hors_cluster_principal"' in corps

    def test_l_amas_principal_est_le_plus_grand(self):
        # Pure : parmi des amas de pastilles, ceux qui ne sont pas le plus grand sont orphelins.
        amas = [{("U1", "8")}, {("C1", "2"), ("C2", "2"), ("U1", "1")}, {("J1", "3")}]
        assert sorted(runner._hors_du_plus_grand_amas(amas)) == [("J1", "3"), ("U1", "8")]
        assert runner._hors_du_plus_grand_amas([]) == []
        assert runner._hors_du_plus_grand_amas([{("U1", "8")}]) == []

"""Un net pris en charge par le PLAN n est pas un net non route.

Mesure du 2026-08-26, carte LED de 3 composants passee dans la chaine complete :

    4 segments (LED_ANODE 2, VCC 2) | ZERO segment GND
    0 connexion manquante | 0 violation DRC
    routed_percent annonce : 66 %

Trois nets, dont GND confie au plan : 2 routes sur 3. La carte est pourtant
ENTIEREMENT connectee — le DRC le dit.

⚠️ Ce chiffre n est pas decoratif. `routed_percent < 100` declenche le reasoner
(`shouldRescueRouting`), les re-tirages de placement (`shouldRetryPlacement`) et
le repli sur un routage incluant GND. Une carte parfaite relancait donc la
machine indefiniment.

C est aussi l explication des « 91 % » vus tout au long du board STM32 : 12 nets
routables, GND confie au plan, 11/12 = 91 %.

Un net confie au plan n a PAS a etre route : l exclure du denominateur n est pas
une indulgence, c est la bonne question posee.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _board(nets: list[str]) -> bytes:
    lignes = ["(kicad_pcb"]
    for i, nom in enumerate(nets, start=1):
        lignes.append(f'(net {i} "{nom}")')
        lignes.append(f'(pad "1" thru_hole circle (net {i} "{nom}"))')
        lignes.append(f'(pad "2" thru_hole circle (net {i} "{nom}"))')
    lignes.append(")")
    return "\n".join(lignes).encode()


class TestComptage:
    def test_un_net_confie_au_plan_n_est_pas_compte(self, monkeypatch):
        monkeypatch.setattr(routing_router, "_NETS_CONFIES_AU_PLAN", ("GND",))
        assert routing_router._count_routable_nets(_board(["VCC", "LED", "GND"])) == 2

    def test_sans_net_a_plan_tous_comptent(self, monkeypatch):
        monkeypatch.setattr(routing_router, "_NETS_CONFIES_AU_PLAN", ())
        assert routing_router._count_routable_nets(_board(["VCC", "LED", "GND"])) == 3

    def test_les_nets_mono_pad_restent_exclus(self, monkeypatch):
        # Garde d origine : un net a une seule pastille n est pas routable.
        monkeypatch.setattr(routing_router, "_NETS_CONFIES_AU_PLAN", ("GND",))
        b = _board(["VCC", "GND"]) + b'\n(net 9 "SEUL")\n(pad "1" thru_hole circle (net 9 "SEUL"))'
        assert routing_router._count_routable_nets(b) == 1

    def test_une_carte_dont_le_plan_porte_tout_vaut_100(self, monkeypatch):
        # Le cas mesure : plus rien a router par des pistes. Rendre 0 % ferait
        # boucler la chaine sur une carte parfaite.
        monkeypatch.setattr(routing_router, "_NETS_CONFIES_AU_PLAN", ("GND",))
        assert routing_router._count_routable_nets(_board(["GND"])) == 0

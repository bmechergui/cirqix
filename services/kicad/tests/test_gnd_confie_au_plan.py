"""Router les signaux, confier GND au plan, echapper le residuel.

Demande de l utilisateur (2026-08-23) : « router d abord les pistes importantes,
puis faire le plan de masse ». C est la sequence d un concepteur humain, et
notre implementation ne la respectait qu a moitie : le routeur, ne voyant aucun
plan, traitait GND comme un signal ordinaire et lui tirait 18 liaisons
completes (181 segments au lieu de 105), dont beaucoup deviennent REDONDANTES
des que le plan est coule par-dessus.

Deux facons de dire au routeur « ne route pas GND », et une seule est bonne :

  ① declarer un plan dans le DSN  -> MESURE, et c est le piege connu : le
     routeur tient alors pour connectees les pastilles qui tombent
     GEOMETRIQUEMENT dans le polygone, or sur un pas de 0,5 mm aucun cuivre
     n atteint les pattes -> 3 connexions manquantes, jamais 0.
  ② retirer le net de la NETLIST du DSN -> le routeur n a rien a router pour
     GND, et AUCUNE geometrie de plan ne contraint son travail sur les autres
     nets. C est ce que fait cette fonction.

Le plan est ensuite coule, et les seules pastilles qu il n atteint pas
reellement — celles que le DRC designe nommement — recoivent un via
d echappement (`_fanout_pads_isolees`).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


DSN = """(pcb board
  (network
    (net VCC
      (pins U1-1 C1-1)
    )
    (net GND
      (pins U1-2 C1-2 U2-8 U2-23
        U2-35 U2-47)
    )
    (net SWDIO
      (pins U2-34 J1-2)
    )
  )
)"""


class TestRetraitDuNet:
    def test_le_net_gnd_disparait_de_la_netlist(self):
        out, retires = routing_router._strip_net_from_dsn(DSN, "GND")
        assert "(net GND" not in out
        assert retires == 6, "les 6 broches GND doivent etre comptees"

    def test_les_autres_nets_sont_intacts(self):
        out, _ = routing_router._strip_net_from_dsn(DSN, "GND")
        assert "(net VCC" in out and "U1-1 C1-1" in out
        assert "(net SWDIO" in out and "U2-34 J1-2" in out

    def test_le_dsn_reste_equilibre(self):
        # Un DSN aux parentheses desequilibrees est refuse par Freerouting :
        # on remplacerait un routage imparfait par une absence de routage.
        out, _ = routing_router._strip_net_from_dsn(DSN, "GND")
        assert out.count("(") == out.count(")")

    def test_un_net_absent_ne_change_rien(self):
        out, retires = routing_router._strip_net_from_dsn(DSN, "INEXISTANT")
        assert out == DSN and retires == 0

    def test_un_prefixe_commun_n_est_pas_confondu(self):
        # `GND` ne doit pas emporter `GNDA` : deux masses distinctes existent
        # sur les cartes analogiques, et en perdre une silencieusement
        # laisserait un net entier non route sans que rien ne le signale.
        dsn = DSN.replace("(net SWDIO", "(net GNDA")
        out, _ = routing_router._strip_net_from_dsn(dsn, "GND")
        assert "(net GNDA" in out


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_retrait_suit_chaque_export_specctra(self):
        # Un seul site oublie et le net repart au routage : la mesure
        # deviendrait incomprehensible (« pourquoi 181 segments ici et 105 la »).
        exports = self.SOURCE.count("_export_specctra(pcb_bytes,")
        retraits = self.SOURCE.count("_confier_au_plan(")
        assert retraits >= exports, f"{exports} exports, {retraits} retraits"

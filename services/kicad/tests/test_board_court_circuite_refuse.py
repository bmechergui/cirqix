"""Un board dont un net réunit des broches de PLUSIEURS nets du schéma est refusé.

⚠️ Mesuré le 2026-09-24 : sur `carte-05`, le net `PWR_FLAG` du board reliait en
cuivre (22 pistes et vias) des broches que le schéma place sur +3V3, GND, SDA et
VIN. Un court-circuit des rails d'alimentation, sur un board déclaré 100 %
routé, 0 erreur, fabricable — et présent dans le dépôt comme référence.

**Aucun juge ne comparait le board à son schéma.** Le DRC compare le board à
SON netlist, qui dit que ces pastilles sont le même net : il ne peut pas voir
qu'elles ne devraient pas l'être. Le court est donc passé par le routage, le
DRC, le banc, et un banc de preuve.

La cause de CE court est corrigée (`test_pwr_flag_jamais_sur_une_broche.py`).
Cette garde-ci ferme la porte à la SUIVANTE : quelle que soit l'étape qui
corrompt le netlist, un board qui réunit deux nets du schéma n'est pas un board
de ce circuit.

La règle ne porte AUCUN seuil. Un net du schéma est une équipotentielle
déclarée ; en réunir deux sur le board n'est jamais légitime — une liaison
voulue entre deux nets passe par un composant (résistance de 0 Ω, pont), pas par
une fusion. On ne bloque QUE sur ce qui est certain : les coupures, elles,
peuvent venir d'un simple écart de numérotation entre broche et pastille.

Même traitement que `_composants_perdus` : le niveau fautif est refusé, on tente
le suivant. Un échec qui se voit vaut mieux qu'un court qui ne se voit pas.
"""
from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import pcb as P  # noqa: E402
from tools.schematic import SchemaNet, SchemaPin  # noqa: E402


def _pad(num: str, net: str) -> str:
    return (f'    (pad "{num}" smd rect (at 0 0) (size 1 1) (layers "F.Cu") '
            f'(net "{net}"))\n' if net else
            f'    (pad "{num}" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))\n')


def _board(**empreintes: dict) -> str:
    corps = ""
    for ref, pads in empreintes.items():
        corps += (f'  (footprint "X" (layer "F.Cu")\n    (property "Reference" "{ref}")\n'
                  + "".join(_pad(n, net) for n, net in pads.items()) + "  )\n")
    return '(kicad_pcb (version 20240108) (generator "pcbnew")\n' + corps + ")\n"


def _schema(**nets: list) -> list:
    return [SchemaNet(name=n, pins=[SchemaPin(ref=r, pin=p) for r, p in pins])
            for n, pins in nets.items()]


SCHEMA = _schema(VIN=[("J1", "1"), ("U2", "3")], **{"+3V3": [("U2", "2"), ("U1", "36")]})


class TestLaRegle:
    def test_le_court_de_carte_10_est_vu(self):
        """U2.3 (VIN) et U1.36 (+3V3) sur le même net du board."""
        board = _board(J1={"1": "VIN"}, U2={"3": "PWR_FLAG", "2": "+3V3"}, U1={"36": "PWR_FLAG"})
        courts = P._courts_circuits(board, SCHEMA)
        assert courts, "VIN et +3V3 reunis sur le net PWR_FLAG : c est un court-circuit"
        assert "PWR_FLAG" in courts[0]

    def test_un_board_conforme_n_a_aucun_court(self):
        board = _board(J1={"1": "VIN"}, U2={"3": "VIN", "2": "+3V3"}, U1={"36": "+3V3"})
        assert P._courts_circuits(board, SCHEMA) == []

    def test_un_renommage_n_est_pas_un_court(self):
        """Le schéma dit +3.3V, le board +3V3 : même net, autre nom."""
        schema = _schema(**{"+3.3V": [("U2", "2"), ("U1", "36")]})
        board = _board(U2={"2": "+3V3"}, U1={"36": "+3V3"})
        assert P._courts_circuits(board, schema) == []

    def test_une_orpheline_n_est_pas_un_court(self):
        """Une broche seule sur son net est une COUPURE, pas un court — elle
        relève de `_patch_floating_nets`, pas de ce refus."""
        board = _board(J1={"1": "VIN"}, U2={"3": "Net-(U2-3)", "2": "+3V3"}, U1={"36": "+3V3"})
        assert P._courts_circuits(board, SCHEMA) == []

    def test_une_pastille_sans_net_n_est_pas_un_court(self):
        board = _board(J1={"1": ""}, U2={"3": "", "2": "+3V3"}, U1={"36": "+3V3"})
        assert P._courts_circuits(board, SCHEMA) == []

    def test_deux_pastilles_du_MEME_numero_ne_sont_pas_un_court(self):
        """La broche et la languette d'un SOT-223 portent toutes deux « 2 »."""
        board = ('(kicad_pcb\n  (footprint "X" (layer "F.Cu")\n    (property "Reference" "U2")\n'
                 + _pad("2", "+3V3") + _pad("2", "+3V3") + "  )\n)\n")
        assert P._courts_circuits(board, SCHEMA) == []


class TestLeCABLAGE:
    """Même traitement que `_composants_perdus` : aux DEUX niveaux."""

    def _appels(self):
        arbre = ast.parse(textwrap.dedent(inspect.getsource(P.generate_pcb)))
        return [getattr(n.func, "id", getattr(n.func, "attr", ""))
                for n in ast.walk(arbre) if isinstance(n, ast.Call)]

    def test_generate_pcb_refuse_un_board_court_circuite(self):
        assert "_courts_circuits" in self._appels()

    def test_les_DEUX_niveaux_sont_controles(self):
        assert self._appels().count("_courts_circuits") >= 2

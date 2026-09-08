"""Une paire à deux bornes doit être serrée — et la règle doit être APPELÉE.

⚠️ MESURE DU 2026-09-08, sur les boards livrés du banc. Une LED et sa
résistance série partagent un net qui ne touche qu'**elles deux** — la paire la
plus serrable qui existe sur une carte :

    carte-09   D12 ↔ R13   100,9 mm
    carte-10   D9  ↔ R10    86,8 mm
    carte-08   D14 ↔ R15    76,7 mm

Moyenne par carte : 3 mm à 5 composants, **55 mm à 62**. La dispersion suit la
taille de la carte : le GA disperse d'autant plus qu'il a de place.

C'est le reproche que l'utilisateur formule le 2026-09-08, capture à l'appui :
« le placement, c'est un placement d'amateur ».

⚠️ POURQUOI LE SNAP EXISTANT NE LES VOYAIT PAS. `tools/placement_bypass.py` ne
traite que les clusters de `detect_functional_clusters` — POWER, TIMING,
DRIVER, INTERFACE. Une paire résistance-LED n'est AUCUN de ces types : elle
n'est jamais regardée. Le snap fonctionne ; il ne regarde pas là.

⚠️ LE LEVIER ÉTAIT NATIF, ET PERSONNE NE L'APPELAIT. `OptimizationWorkflow` —
celui que nous appelons déjà — accepte `constraints=[GroupingConstraint]`
(`optim/workflow.py:244`) et `WorkflowConfig.grid` (ligne 187). Ni l'un ni
l'autre n'a jamais été passé. Troisième fois pour ce dépôt, après
`FunctionalCluster.max_distance_mm` et `anchor_pin`.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import placement_contraintes as C  # noqa: E402


class _Pad:
    def __init__(self, net_name: str) -> None:
        self.net_name = net_name


class _Fp:
    def __init__(self, reference: str, nets: list[str]) -> None:
        self.reference = reference
        self.pads = [_Pad(n) for n in nets]


class _Pcb:
    def __init__(self, footprints: list[_Fp]) -> None:
        self.footprints = footprints


def _carte() -> _Pcb:
    """Une LED, sa résistance, un MCU, un connecteur — le cas réel en petit."""
    return _Pcb([
        _Fp("R5", ["IO_L5", "LEDA5"]),          # 2 pastilles
        _Fp("D5", ["LEDA5", "GND"]),            # 2 pastilles
        _Fp("U1", ["IO_L5", "GND", "+3V3"] + ["SIG%d" % i for i in range(45)]),
        _Fp("J1", ["+3V3", "GND", "SIG0", "SIG1", "SIG2"]),
    ])


class TestDetection:
    def test_la_paire_LED_resistance_est_vue(self):
        paires = C.paires_du_board(_carte())
        assert ("LEDA5", "D5", "R5") in paires

    def test_un_CONCENTRATEUR_n_est_jamais_contraint(self):
        """`R5` et `U1` partagent `IO_L5`, un net à deux bornes.

        ⚠️ Mesuré sur `carte-09` : 38 paires, dont 20 de la forme `R<n>-U1`.
        Contraindre le MCU à 5 mm de VINGT résistances est insatisfiable, et le
        solveur aurait arbitré au hasard entre des ressorts contradictoires —
        un placement pire, pas meilleur. Un boîtier à 48 pastilles est un nœud
        du circuit, pas un élément de chaîne.
        """
        paires = C.paires_du_board(_carte())
        assert not any("U1" in (a, b) for _, a, b in paires), (
            "un concentrateur a ete contraint : %s" % paires)

    def test_un_rail_d_alimentation_n_est_jamais_une_adjacence(self):
        """`GND` et `+3V3` relient tout à tout : les serrer tirerait la carte
        entière vers un point."""
        paires = C.paires_du_board(_carte())
        assert not any(n in ("GND", "+3V3") for n, _, _ in paires)

    def test_un_net_a_TROIS_bornes_est_ignore(self):
        """Trois bornes n'ont pas de « bonne » distance évidente ; forcer une
        adjacence inventerait une intention que la netlist n'exprime pas."""
        pcb = _Pcb([_Fp("R1", ["N"]), _Fp("R2", ["N"]), _Fp("R3", ["N"])])
        assert C.paires_du_board(pcb) == []

    def test_un_composant_boucle_sur_lui_meme_n_est_pas_une_paire(self):
        pcb = _Pcb([_Fp("R1", ["N", "N"])])
        assert C.paires_du_board(pcb) == []


class TestConstruction:
    def test_une_contrainte_native_est_produite_par_paire(self):
        c = C.contraintes_du_board(_carte())
        assert len(c) == 1
        assert sorted(c[0].members) == ["D5", "R5"]

    def test_l_ancre_est_celle_qui_NE_BOUGE_PAS(self):
        """Ancrer sur un composant libre laisserait satisfaire la contrainte en
        déplaçant les DEUX, ce qui n'aide en rien."""
        c = C.contraintes_du_board(_carte(), refs_ancrees=["D5"])
        assert c[0].constraints[0].parameters["anchor"] == "D5"

    def test_sans_ancre_le_choix_est_STABLE(self):
        """Un ancrage instable rendrait le placement irreproductible pour une
        raison sans rapport avec le GA."""
        def _ancre():
            return C.contraintes_du_board(_carte())[0].constraints[0].parameters["anchor"]
        a, b = _ancre(), _ancre()
        assert a == b == "D5"  # premier par ordre alphabetique


class TestCablage:
    """⚠️ Une règle correcte jamais appelée est indistinguable d'une absente.

    C'est exactement ce qui a masqué pendant des semaines le fait que le
    Géomètre ne tournait jamais en production. On teste le comportement ET le
    câblage.
    """

    def test_auto_place_passe_les_contraintes_au_workflow(self):
        from tools import placement as P
        code = inspect.getsource(P._auto_place_une_fois)
        # On ne lit que le CODE : un commentaire qui cite le nom ne prouve rien.
        code = "\n".join(l.split("#")[0] for l in code.splitlines())
        assert "contraintes_du_board" in code, (
            "les contraintes ne sont pas construites")
        assert "constraints=" in code, (
            "les contraintes ne sont pas transmises au workflow")

    def test_auto_place_passe_la_grille_au_workflow(self):
        from tools import placement as P
        code = "\n".join(l.split("#")[0]
                         for l in inspect.getsource(P._auto_place_une_fois).splitlines())
        assert "grid=" in code, "la grille n'est pas transmise"

    def test_la_grille_n_est_pas_nulle(self):
        """`WorkflowConfig.grid` vaut 0.0 par defaut, et 0 signifie AUCUN snap.

        Transmettre la valeur par defaut serait indistinguable de ne rien
        transmettre — et c'est precisement l'etat d'avant.
        """
        from tools import placement as P
        assert P._GRILLE_MM > 0

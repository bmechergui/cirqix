"""`_patch_floating_nets` est APPELÉ par `generate_pcb` — pas seulement par ses tests.

⚠️ Constaté le 2026-09-24 : la fonction n'était appelée NULLE PART en
production. Seul `tests/test_nets_kicad10_dans_pcb.py` l'invoquait,
directement. Le correctif du 2026-09-09, inscrit dans CLAUDE.md comme réglant
« six cartes sur onze livraient des broches d'alimentation sur des nets
orphelins — dont la sortie d'un régulateur », vivait dans une fonction que
personne n'invoquait.

Mesure sur `carte-10`, schéma fraîchement généré :

    U1.36 -> Net-(U1-36)   (1 broche)   le schéma dit +3V3   (VDD du MCU)
    U1.48 -> Net-(U1-48)   (1 broche)   le schéma dit +3V3   (VDD du MCU)
    U2.2  -> Net-(U2-2)    (2 pastilles) le schéma dit +3V3   (SORTIE du régulateur)

Le régulateur n'alimentait rien, et le microcontrôleur n'était pas alimenté —
sur une carte « 100 % routée, 0 erreur ». Un net orphelin n'a aucune connexion
manquante : aucun DRC ne pouvait le voir.

C'est la NEUVIÈME « règle écrite et jamais appelée » de ce dépôt. La leçon est
inscrite depuis le 2026-08-29 : « une règle correcte jamais invoquée est
indistinguable d'une règle absente — tester le comportement ET le câblage ».
Ses tests testaient le comportement ; rien ne testait le câblage.
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


def _appels(fonction) -> list[tuple[int, str]]:
    """(ligne, nom) de chaque appel de fonction dans le CODE — l'AST ne voit ni
    les commentaires ni les docstrings, où ce nom apparaît aussi."""
    arbre = ast.parse(textwrap.dedent(inspect.getsource(fonction)))
    out = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Call):
            f = noeud.func
            nom = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
            out.append((noeud.lineno, nom))
    return sorted(out)


class TestLeCABLAGE:
    def test_generate_pcb_appelle_la_reparation(self):
        noms = [n for _, n in _appels(P.generate_pcb)]
        assert "_patch_floating_nets" in noms, (
            "generate_pcb doit reparer les broches orphelines avec les connexions "
            "du schema — sinon la sortie du regulateur n alimente rien")

    def test_les_DEUX_niveaux_sont_repares(self):
        """Niveau 1 (kicad-tools) et niveau 2 (pcbnew) produisent chacun un
        board : réparer l'un et pas l'autre serait la même faute, un niveau plus
        loin."""
        noms = [n for _, n in _appels(P.generate_pcb)]
        assert noms.count("_patch_floating_nets") >= 2

    def test_la_reparation_precede_le_controle_des_composants(self):
        """Réparer après avoir rendu le board ne répare rien."""
        appels = _appels(P.generate_pcb)
        rep = [l for l, n in appels if n == "_patch_floating_nets"]
        ctrl = [l for l, n in appels if n == "_composants_perdus"]
        assert rep and ctrl and min(rep) < min(ctrl)


class TestLeComportementSurUnVraiCas:
    """La broche de sortie du régulateur, sur ses DEUX pastilles (broche et
    languette d'un SOT-223), revient sur son net du schéma."""

    BOARD = """(kicad_pcb (version 20240108) (generator "pcbnew")
  (net 0 "")
  (net 1 "+3V3")
  (net 2 "Net-(U2-2)")
  (footprint "Package_TO_SOT_SMD:SOT-223-3_TabPin2" (layer "F.Cu")
    (property "Reference" "U2")
    (pad "2" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 2 "Net-(U2-2)"))
    (pad "2" smd rect (at 0 3) (size 3 2) (layers "F.Cu") (net 2 "Net-(U2-2)"))
  )
)
"""

    def test_les_deux_pastilles_2_rejoignent_le_rail(self):
        from tools.schematic import SchemaNet, SchemaPin  # le type réel de la requête
        conn = [SchemaNet(name="+3V3", pins=[SchemaPin(ref="U2", pin="2")])]
        apres = P._patch_floating_nets(self.BOARD, conn)
        assert apres.count('(net 1 "+3V3")') == 2 + 1   # déclaration + 2 pastilles
        assert "Net-(U2-2))" not in apres.split("(footprint", 1)[1]

"""Les outils de livraison ne gardent jamais un board court-circuité.

⚠️ Mesuré le 2026-09-24 : les boards versionnés de `carte-04` à `carte-10`
reliaient VIN, +3V3 et d'autres nets en cuivre, et obtenaient pourtant
« 100 %, 0 erreur, 0 composant perdu ». Les deux outils de livraison classaient
sur `(perdus, erreurs, -% routé)` : leur protection « on ne remplace jamais
par moins bon » GARDAIT le court face à un board correct à 98 %.

Même correction que pour les composants perdus le 2026-09-08 : un board SANS
court l'emporte toujours, quel que soit son DRC — que le DRC ne peut d'ailleurs
pas voir, puisqu'il juge le board contre SON netlist.

⚠️ `livrer_campagne` lit sa note PAR POSITION à quatre endroits, dont un qui
écrit les mesures livrées. Le court n'y est donc pas inséré dans la note : on
compare sur une clé séparée `(courts, note)`. Dans `regenerer_le_banc`, où il
est inséré en tête, l'affichage passe par `_lisible`, qui nomme chaque champ.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import sys
import textwrap
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools.pcb import courts_du_board  # noqa: E402


def _script(nom: str):
    spec = importlib.util.spec_from_file_location(nom, _SERVICE / "scripts" / (nom + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCHEMA = {"components": [{"ref": "U2"}, {"ref": "U1"}, {"ref": "J1"}],
          "connections": [{"name": "VIN", "pins": [{"ref": "J1", "pin": 1}, {"ref": "U2", "pin": 3}]},
                          {"name": "+3V3", "pins": [{"ref": "U2", "pin": 2}, {"ref": "U1", "pin": 36}]}]}


def _board(net_u2_3: str) -> str:
    fp = lambda ref, pads: ('  (footprint "X" (layer "F.Cu")\n    (property "Reference" "%s")\n' % ref
                            + "".join('    (pad "%s" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "%s"))\n'
                                      % (n, net) for n, net in pads) + "  )\n")
    return ("(kicad_pcb (version 20240108)\n" + fp("J1", [("1", "VIN")])
            + fp("U2", [("3", net_u2_3), ("2", "+3V3")]) + fp("U1", [("36", "+3V3")]) + ")\n")


class TestLaMesurePartagee:
    def test_un_court_est_compte(self):
        """Le cas de carte-10 : U2.3 (VIN) sur le net de +3V3."""
        assert len(courts_du_board(_board("+3V3"), SCHEMA)) == 1

    def test_un_board_conforme_n_en_a_aucun(self):
        assert courts_du_board(_board("VIN"), SCHEMA) == []

    def test_les_deux_formats_d_entree(self):
        """`circuit.json` met les liaisons dans `nets`, pas dans `connections`."""
        circuit = {"components": SCHEMA["components"], "nets": SCHEMA["connections"]}
        assert len(courts_du_board(_board("+3V3"), circuit)) == 1


class TestRegenererLeBanc:
    def test_la_note_met_le_court_EN_TETE(self, tmp_path):
        """Un vrai dossier d'exemple, reconstitué : la note se lit sur le disque."""
        R = _script("regenerer_le_banc")
        (tmp_path / "input").mkdir()
        (tmp_path / "expected").mkdir()
        (tmp_path / "input" / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        (tmp_path / "expected" / "mesures.json").write_text(
            json.dumps({"routed_percent": 100, "drc_du_board": {"nb_erreurs": 0}}), encoding="utf-8")
        (tmp_path / "expected" / "final.kicad_pcb").write_text(_board("+3V3"), encoding="utf-8")
        court = R._note(tmp_path)
        (tmp_path / "expected" / "final.kicad_pcb").write_text(_board("VIN"), encoding="utf-8")
        sain = R._note(tmp_path)
        assert court[0] == 1 and sain[0] == 0
        assert sain < court, "un board sain a 100 %% doit battre le meme board court-circuite"

    def test_un_board_sain_a_98_bat_un_court_a_100(self):
        assert (0, 0, 0, -98) < (1, 0, 0, -100)

    def test_l_affichage_nomme_chaque_champ(self):
        """⚠️ Sans `_lisible`, le décalage du tuple aurait affiché « 0 % » pour
        une carte à 100 %."""
        R = _script("regenerer_le_banc")
        assert R._lisible((0, 1, 2, -100)) == "100% · 2 err · 1 perdu(s) · 0 court(s)"


class TestLivrerCampagne:
    def test_la_cle_fait_perdre_le_court(self):
        L = _script("livrer_campagne")
        mieux_sur_le_papier = (0, 0, -100, 2)    # 100 %, mais court-circuité
        moins_bien = (0, 0, -98, 2)              # 98 %, sans court
        assert L._cle(0, moins_bien) < L._cle(1, mieux_sur_le_papier)

    def test_les_TROIS_comparaisons_passent_par_la_cle(self):
        """Tri, refus et verdict : en oublier une, c'est garder le court."""
        L = _script("livrer_campagne")
        arbre = ast.parse(textwrap.dedent(inspect.getsource(L.main)))
        appels = [getattr(n.func, "id", "") for n in ast.walk(arbre) if isinstance(n, ast.Call)]
        assert appels.count("_cle") >= 5, "tri + refus (2 cles) + verdict (2 cles)"

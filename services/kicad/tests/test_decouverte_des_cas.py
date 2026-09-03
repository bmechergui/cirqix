"""Un banc qui omet une carte rend la meme sortie qu un banc qui ne l a pas.

⚠️ Constat du 2026-08-30, souleve par l utilisateur — pas par moi, ni par un
test. La decouverte des cas filtrait sur `input/circuit.json` EN SILENCE :

    led-blinker-full-pipeline   ->  input/schema.json   jamais mesure
    stm32-validation            ->  input/generate_design.py

Le premier est presente par CLAUDE.md comme LE cas de reference du pipeline
complet ①→⑧ (« expected/led_blinker_final.kicad_pcb = 100 % route / DRC-clean »).
Son fichier portait simplement un autre nom, et son contenu est deja la forme
que le banc CONSTRUIT pour appeler le service :

    circuit.json   nets = [{name, pins}]
    schema.json    nets = ["VCC", ...]  +  connections = [{name, pins}]

Sept lignes s affichaient, huit cartes existaient, et rien ne le disait. C est
la meme famille que tous les defauts de la semaine : une omission silencieuse
est indistinguable d une absence.

⚠️ `stm32-validation` reste hors banc — son entree est un GENERATEUR, ce n est
pas un cas schema -> Gerber. Mais son exclusion doit etre DITE, avec son motif.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT / "scripts"))

import banc_exemples as B  # noqa: E402


def _cas(tmp_path: Path, nom: str, fichier: str | None) -> Path:
    d = tmp_path / nom
    (d / "input").mkdir(parents=True)
    if fichier:
        (d / "input" / fichier).write_text("{}", encoding="utf-8")
    return d


class TestReconnaissance:
    def test_circuit_json_est_reconnu(self, tmp_path):
        d = _cas(tmp_path, "a", "circuit.json")
        assert B._fichier_de_cas(d).name == "circuit.json"

    def test_schema_json_est_reconnu(self, tmp_path):
        # Le defaut EXACT : ce cas etait ecarte alors qu il est mesurable.
        d = _cas(tmp_path, "b", "schema.json")
        assert B._fichier_de_cas(d).name == "schema.json"

    def test_circuit_json_prime_si_les_deux_existent(self, tmp_path):
        d = _cas(tmp_path, "c", "circuit.json")
        (d / "input" / "schema.json").write_text("{}", encoding="utf-8")
        assert B._fichier_de_cas(d).name == "circuit.json"

    def test_un_generateur_n_est_pas_un_cas(self, tmp_path):
        d = _cas(tmp_path, "d", "generate_design.py")
        assert B._fichier_de_cas(d) is None


class TestMotifDit:
    def test_le_motif_NOMME_ce_qui_est_present(self, tmp_path):
        # Sans le contenu reel, le motif ne permet pas de corriger le cas.
        d = _cas(tmp_path, "e", "generate_design.py")
        assert "generate_design.py" in B._pourquoi_ecarte(d)

    def test_un_input_absent_est_dit(self, tmp_path):
        d = tmp_path / "f"
        d.mkdir()
        assert "input" in B._pourquoi_ecarte(d)

    def test_un_input_vide_est_dit(self, tmp_path):
        d = _cas(tmp_path, "g", None)
        assert "vide" in B._pourquoi_ecarte(d)


class TestNormalisation:
    def test_connections_devient_nets(self):
        # `schema.json` : les noms d un cote, les liaisons de l autre. Le banc
        # attend la forme detaillee.
        brut = {"nets": ["VCC", "GND"],
                "connections": [{"name": "VCC", "pins": [{"ref": "U1", "pin": 8}]}]}
        assert B._normaliser(brut)["nets"] == brut["connections"]

    def test_circuit_json_traverse_inchange(self):
        brut = {"nets": [{"name": "VIN", "pins": []}]}
        assert B._normaliser(brut) == brut

    def test_la_normalisation_ne_MUTE_pas_l_entree(self):
        brut = {"nets": ["VCC"], "connections": [{"name": "VCC", "pins": []}]}
        avant = brut["nets"]
        B._normaliser(brut)
        assert brut["nets"] is avant


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "scripts" / "banc_exemples.py").read_text(
        encoding="utf-8")

    def test_la_decouverte_passe_par_le_reconnaisseur(self):
        # ⚠️ Le filtre littéral `circuit.json` ne doit plus decider seul du
        # perimetre : c est lui qui a rendu l omission invisible.
        i = self.SOURCE.index("def main(")
        corps = self.SOURCE[i:]
        assert "_fichier_de_cas(" in corps

    def test_les_cas_ecartes_sont_IMPRIMES(self):
        i = self.SOURCE.index("def main(")
        corps = self.SOURCE[i:]
        assert "ecarte" in corps and "_pourquoi_ecarte(" in corps

    def test_l_entree_est_normalisee_avant_usage(self):
        assert "_normaliser(json.loads(" in self.SOURCE

"""Un schéma que `kicad-cli` refuse doit être CONSERVÉ, sinon il est indiagnostiquable.

`run_erc` travaille dans un `TemporaryDirectory` : quand `kicad-cli sch erc`
échoue, le fichier fautif est détruit avant même que l'erreur soit lue. Il ne
reste qu'un message — et ce message est GÉNÉRIQUE :

    rc=3: Failed to load schematic

Le même texte sort pour une valeur de propriété non quotée (corrigée le
2026-08-20), pour un fichier tronqué, et même pour un fichier ABSENT — vérifié
par accident en lançant kicad-cli sur un chemin inexistant.

Constaté le 2026-08-21 : un run échoue encore avec ce message alors que le
requotage ne trouve rien à corriger. Il y a donc une seconde cause, et sans
l'artefact on ne peut ni la nommer ni la reproduire. Deux journées d'enquête
sur ce service ont buté exactement là.

⚠️ Conserver est BORNÉ : le volume `/tmp/kicad-jobs` est persistant, donc on ne
garde que les derniers échecs. Un diagnostic ne doit pas remplir le disque.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import erc as erc_router  # noqa: E402


class TestConservation:
    def test_le_schema_fautif_est_ecrit_sur_disque(self, tmp_path, monkeypatch):
        monkeypatch.setattr(erc_router, "_FAILED_ERC_DIR", tmp_path)
        chemin = erc_router._keep_failed_schematic("(kicad_sch (version 1))")

        assert chemin is not None
        assert chemin.is_file()
        assert chemin.read_text(encoding="utf-8") == "(kicad_sch (version 1))"
        assert chemin.suffix == ".kicad_sch"

    def test_les_anciens_artefacts_sont_purges(self, tmp_path, monkeypatch):
        monkeypatch.setattr(erc_router, "_FAILED_ERC_DIR", tmp_path)
        monkeypatch.setattr(erc_router, "_MAX_FAILED_ARTEFACTS", 3)

        for i in range(6):
            erc_router._keep_failed_schematic(f"(kicad_sch (n {i}))")

        restants = sorted(tmp_path.glob("*.kicad_sch"))
        assert len(restants) == 3, f"{len(restants)} artefacts conservés au lieu de 3"

    def test_un_echec_d_ecriture_ne_masque_pas_l_erreur_d_origine(self, tmp_path, monkeypatch):
        # Le diagnostic est un CONFORT : s'il échoue, l'erreur réelle doit
        # continuer de remonter telle quelle.
        #
        # Un dossier « sous un FICHIER » est invalide sur tout système — plus sûr
        # qu'un chemin absolu inexistant, que Windows crée volontiers.
        fichier = tmp_path / "pas-un-dossier"
        fichier.write_text("x", encoding="utf-8")
        monkeypatch.setattr(erc_router, "_FAILED_ERC_DIR", fichier / "sous-dossier")

        assert erc_router._keep_failed_schematic("(kicad_sch)") is None


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "erc.py").read_text(encoding="utf-8")

    def test_l_echec_de_kicad_cli_conserve_le_schema(self):
        assert "_keep_failed_schematic(" in self.SOURCE
        # Et le chemin doit être journalisé : un artefact qu'on ne sait pas
        # retrouver ne sert à rien.
        assert "artefact" in self.SOURCE.lower()

    def test_la_conservation_n_avale_pas_l_exception(self):
        # `run_erc` doit continuer de basculer sur le repli TypeScript.
        assert "except Exception" in self.SOURCE

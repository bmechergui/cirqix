"""Un routage dont TOUS les tirages figent rend quand meme un board.

⚠️ A/B du 2026-09-19 : carte-03, 07, 09 et 10 sorties SANS board dans les
deux bras. Chaque tirage figeait (« 30 passes sans progres, 83 non routes »),
l attente etait abandonnee, la JVM tuee — et le job avec elle. Le « dernier
recours » `_recuperer_jobs_abandonnes` trouvait « 7 irrecuperable(s) ».

Mesure du 2026-09-20 sur l API Freerouting 2.1.0 : un job en cours ne rend
jamais son board (`/output` 400, `/output/stream` 500, `cancel` 501) et
`max_passes` / `job_timeout` sont ignores, par job comme en global. Le SEUL
moyen d obtenir un partiel est le CLI, qui honore `-mp` et ecrit son .ses.

Regle : un tirage fige a la passe P vaut un CLI `-mp P` sur le meme DSN.
Sans board, l orchestrateur ne peut pas re-tirer le placement — il n a aucun
pourcentage a juger. Avec un partiel, sa boucle existante repart.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402


class TestLaStagnationPorteLaPasse:
    def test_passes_transportees(self):
        f = R.RoutageFige(unrouted=83, nets=100, passes=37)
        assert f.passes == 37 and f.routed_percent == 17

    def test_defaut_zero(self):
        assert R.RoutageFige(unrouted=1, nets=2).passes == 0


class TestLeCliHonoreLesPasses:
    def test_run_freerouting_transmet_mp(self, monkeypatch, tmp_path):
        vu = {}

        def faux_run(cmd, **kw):
            vu["cmd"] = cmd
            (tmp_path / "b.ses").write_text("(session)")
            return type("R", (), {"returncode": 0})()

        monkeypatch.setattr(R.subprocess, "run", faux_run)
        R._run_freerouting(("java", "fr.jar"), tmp_path / "b.dsn", tmp_path / "b.ses",
                           60, max_passes=37)
        assert vu["cmd"][vu["cmd"].index("-mp") + 1] == "37"

    def test_partiel_par_cli_rejoue_la_passe_atteinte(self, monkeypatch, tmp_path):
        vu = {}
        monkeypatch.setattr(R, "_export_specctra", lambda pcb, dsn: dsn.write_text("(dsn)"))
        monkeypatch.setattr(R, "_confier_au_plan", lambda dsn: None)
        monkeypatch.setattr(R, "_find_freerouting", lambda: ("java", "fr.jar"))

        def faux_cli(paths, dsn, ses, timeout_s, max_passes=100):
            vu["max_passes"], vu["timeout_s"] = max_passes, timeout_s
            ses.write_text("(session)")

        monkeypatch.setattr(R, "_run_freerouting", faux_cli)
        monkeypatch.setattr(R, "_specctra_roundtrip", lambda pcb, ses: b"BOARD PARTIEL")
        assert R._board_partiel_par_cli(b"(kicad_pcb)", passes=37, budget_s=600) == b"BOARD PARTIEL"
        assert vu["max_passes"] == 37
        assert vu["timeout_s"] <= 600

    def test_zero_passe_ne_lance_rien(self, monkeypatch):
        monkeypatch.setattr(R, "_find_freerouting", lambda: ("java", "fr.jar"))
        monkeypatch.setattr(R, "_run_freerouting",
                            lambda *a, **k: pytest.fail("CLI lance pour 0 passe"))
        assert R._board_partiel_par_cli(b"(kicad_pcb)", passes=0, budget_s=600) is None

    def test_une_panne_du_cli_rend_none_et_le_dit(self, monkeypatch, caplog):
        monkeypatch.setattr(R, "_export_specctra", lambda pcb, dsn: dsn.write_text("(dsn)"))
        monkeypatch.setattr(R, "_confier_au_plan", lambda dsn: None)
        monkeypatch.setattr(R, "_find_freerouting", lambda: ("java", "fr.jar"))

        def boum(*a, **k):
            raise RuntimeError("Freerouting exit 1")

        monkeypatch.setattr(R, "_run_freerouting", boum)
        with caplog.at_level("WARNING"):
            assert R._board_partiel_par_cli(b"(kicad_pcb)", passes=5, budget_s=600) is None
        assert "partiel" in caplog.text.lower()


class TestCablage:
    SOURCE = (RACINE / "routers" / "routing.py").read_text(encoding="utf-8")

    def _route_auto(self):
        i = self.SOURCE.index("def route_auto(")
        return self.SOURCE[i: self.SOURCE.index("\nclass RouteProgressResponse", i)]

    def test_le_tirage_fige_memorise_sa_passe(self):
        corps = self._route_auto()
        i = corps.index("except RoutageFige as fige:")
        bloc = corps[i: corps.index("\n        # ⚠️ Initialise AVANT le bloc", i)]
        assert "fige.passes" in bloc

    def test_le_partiel_est_tente_avant_le_recours_aux_jobs_morts(self):
        corps = self._route_auto()
        i = corps.index("if meilleur is None:")
        fin = corps[i:]
        assert "_board_partiel_par_cli(" in fin
        assert fin.index("_board_partiel_par_cli(") < fin.index("_recuperer_jobs_abandonnes(")

    def test_la_stagnation_transmet_la_passe(self):
        i = self.SOURCE.index("raise RoutageFige(unrouted=unrouted,")
        assert "passes=" in self.SOURCE[i: i + 200]

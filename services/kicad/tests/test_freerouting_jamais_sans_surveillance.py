"""Freerouting n'est jamais lance sans surveillance.

Mesure du 2026-09-29, carte-09 (placement fige du 24) : la sonde de l'API
(`timeout=2`) a echoue sans rien journaliser, `route_auto` est tombe sur le
CLI (`_run_freerouting`), qui a tourne 18 min pour rendre 83 % — sans aucune
coupure de stagnation, `-mp` etant ignore par Freerouting 2.1.0. Le meme
moteur, par l'API, rend cette carte en quelques secondes.

Trois gardes :
- la sonde patiente tant que la JVM tourne, la relance si elle reste muette,
  et DIT pourquoi elle renonce ;
- le CLI est surveille avec les memes criteres que l'API et arrete s'il fige ;
- un CLI fige remonte `RoutageFige`, comme l'API, au lieu de partir vers
  kicad-tools.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402

LIGNE = ("2026-09-29 15:04:53.045 INFO   [05A2BD\\7C8741] Auto-router pass #{p} on board "
         "'x' was completed in 0.87 seconds with the score of {s} ({u} unrouted), "
         "using 1 CPU seconds and 1 MB memory.\n")


def _passes(debut, fin, unrouted, score="981.50"):
    return "".join(LIGNE.format(p=p, s=score, u=unrouted) for p in range(debut, fin + 1))


class Horloge:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# --------------------------------------------------------------------------
# La sonde de l API
# --------------------------------------------------------------------------
class TestLaSondePatiente:
    def test_api_qui_repond_est_rendue_sans_attente(self, monkeypatch):
        monkeypatch.setattr(R, "_find_freerouting_api", lambda *a, **k: "http://api")
        monkeypatch.setattr(R.time, "sleep", lambda s: pytest.fail("aucune attente"))
        assert R._api_freerouting_prete() == "http://api"

    def test_sans_jvm_on_renonce_tout_de_suite_et_on_le_dit(self, monkeypatch, caplog):
        monkeypatch.setattr(R, "_find_freerouting_api", lambda *a, **k: None)
        monkeypatch.setattr(R, "_jvm_api_lancee", lambda: False)
        monkeypatch.setattr(R.time, "sleep", lambda s: pytest.fail("aucune attente"))
        with caplog.at_level("WARNING"):
            assert R._api_freerouting_prete() is None
        assert "API" in caplog.text

    def test_jvm_lente_a_repondre_on_l_attend(self, monkeypatch):
        reponses = iter([None, None, "http://api"])
        monkeypatch.setattr(R, "_find_freerouting_api", lambda *a, **k: next(reponses))
        monkeypatch.setattr(R, "_jvm_api_lancee", lambda: True)
        horloge = Horloge()
        monkeypatch.setattr(R.time, "time", horloge)
        monkeypatch.setattr(R.time, "sleep", lambda s: setattr(horloge, "t", horloge.t + s))
        monkeypatch.setattr(R, "_tuer_la_jvm", lambda *a, **k: pytest.fail("pas de relance"))
        assert R._api_freerouting_prete(attente_s=30) == "http://api"

    def test_jvm_muette_on_la_relance(self, monkeypatch, caplog):
        monkeypatch.setattr(R, "_jvm_api_lancee", lambda: True)
        relancee = {"oui": False}

        def sonde(*a, **k):
            return "http://api" if relancee["oui"] else None

        def relance(*a, **k):
            relancee["oui"] = True
            return True

        monkeypatch.setattr(R, "_find_freerouting_api", sonde)
        monkeypatch.setattr(R, "_tuer_la_jvm", relance)
        horloge = Horloge()
        monkeypatch.setattr(R.time, "time", horloge)
        monkeypatch.setattr(R.time, "sleep", lambda s: setattr(horloge, "t", horloge.t + s))
        with caplog.at_level("WARNING"):
            assert R._api_freerouting_prete(attente_s=30) == "http://api"
        assert relancee["oui"]
        assert "relance" in caplog.text

    def test_route_auto_once_passe_par_la_sonde_patiente(self):
        import inspect
        src = inspect.getsource(R._route_auto_once)
        assert "api_url = _api_freerouting_prete()" in src


# --------------------------------------------------------------------------
# Le suivi de stagnation, partage par le CLI
# --------------------------------------------------------------------------
class TestSuiviStagnation:
    def test_journal_vide_on_attend(self):
        suivi = R._SuiviStagnation(horloge=Horloge())
        assert suivi.observer("") is None

    def test_job_qui_progresse_on_attend(self):
        suivi = R._SuiviStagnation(horloge=Horloge())
        journal = "".join(LIGNE.format(p=p, s=900 - p, u=40 - p // 5) for p in range(1, 120))
        assert suivi.observer(journal) is None

    def test_fenetre_de_passes_depassee_on_coupe(self):
        suivi = R._SuiviStagnation(horloge=Horloge())
        verdict = suivi.observer(_passes(1, 170, unrouted=6))
        assert verdict is not None
        assert verdict.unrouted == 6 and verdict.passes == 170

    def test_deux_jobs_dans_le_journal_on_ne_juge_pas(self):
        autre = _passes(1, 170, unrouted=6).replace("7C8741", "AAAAAA")
        suivi = R._SuiviStagnation(horloge=Horloge())
        assert suivi.observer(_passes(1, 170, unrouted=6) + autre) is None

    def test_presque_fini_coupe_seulement_a_l_horloge(self):
        horloge = Horloge()
        suivi = R._SuiviStagnation(horloge=horloge)
        journal = _passes(1, 400, unrouted=1)
        assert suivi.observer(journal) is None, "1 non route : pas de coupure aux passes"
        horloge.t += R._PLAFOND_ATTENTE_S + 1
        journal += _passes(401, 402, unrouted=1)
        assert suivi.observer(journal) is not None, "300 s sans progres : on coupe"


# --------------------------------------------------------------------------
# Le CLI surveille
# --------------------------------------------------------------------------
class FauxProcessus:
    """Un `java -jar` qui ecrit son journal et ne se termine jamais seul."""

    def __init__(self, journal: Path, texte: str, finit: bool = False, ses: Path = None):
        self.tue = False
        self._finit = finit
        self._ses = ses
        with open(journal, "a", encoding="utf-8") as f:
            f.write(texte)
        if finit and ses is not None:
            ses.write_text("(session)")

    def wait(self, timeout=None):
        if self._finit or self.tue:
            return 0
        raise subprocess.TimeoutExpired("java", timeout)

    def poll(self):
        return 0 if (self._finit or self.tue) else None

    def kill(self):
        self.tue = True

    @property
    def returncode(self):
        return 0


class TestLeCliEstSurveille:
    def test_cli_fige_est_arrete_et_leve_routage_fige(self, monkeypatch, tmp_path):
        journal = tmp_path / "freerouting.log"
        journal.write_text("")
        monkeypatch.setattr(R, "_FREEROUTING_LOG", journal)
        procs = []

        def faux_popen(cmd, **kw):
            p = FauxProcessus(journal, _passes(1, 170, unrouted=6))
            procs.append(p)
            return p

        monkeypatch.setattr(R.subprocess, "Popen", faux_popen)
        monkeypatch.setattr(R.time, "sleep", lambda s: None)
        with pytest.raises(R.RoutageFige) as fige:
            R._run_freerouting(("java", "fr.jar"), tmp_path / "b.dsn", tmp_path / "b.ses",
                               3000, nets_routables=48)
        assert procs[0].tue, "le processus fige doit etre arrete"
        assert fige.value.unrouted == 6 and fige.value.routed_percent == 88

    def test_cli_qui_finit_rend_la_main(self, monkeypatch, tmp_path):
        journal = tmp_path / "freerouting.log"
        journal.write_text("")
        monkeypatch.setattr(R, "_FREEROUTING_LOG", journal)
        ses = tmp_path / "b.ses"
        monkeypatch.setattr(R.subprocess, "Popen",
                            lambda cmd, **kw: FauxProcessus(journal, _passes(1, 3, 0),
                                                            finit=True, ses=ses))
        R._run_freerouting(("java", "fr.jar"), tmp_path / "b.dsn", ses, 3000)
        assert ses.exists()

    def test_budget_depasse_le_processus_est_arrete(self, monkeypatch, tmp_path):
        journal = tmp_path / "freerouting.log"
        journal.write_text("")
        monkeypatch.setattr(R, "_FREEROUTING_LOG", journal)
        procs = []
        monkeypatch.setattr(R.subprocess, "Popen",
                            lambda cmd, **kw: procs.append(FauxProcessus(journal, "")) or procs[-1])
        horloge = Horloge()
        monkeypatch.setattr(R.time, "time", horloge)
        monkeypatch.setattr(R.time, "sleep", lambda s: setattr(horloge, "t", horloge.t + s))
        with pytest.raises(subprocess.TimeoutExpired):
            R._run_freerouting(("java", "fr.jar"), tmp_path / "b.dsn", tmp_path / "b.ses", 60)
        assert procs[0].tue

    def test_cli_muet_sans_passe_n_est_pas_un_100_pourcent(self, monkeypatch, tmp_path):
        # Revue du 2026-09-29 : coupe « muet » sans aucune passe lue, le compte
        # de non routes vaut 0 — RoutageFige en deduisait 100 %.
        journal = tmp_path / "freerouting.log"
        journal.write_text("")
        monkeypatch.setattr(R, "_FREEROUTING_LOG", journal)
        monkeypatch.setattr(R.subprocess, "Popen", lambda cmd, **kw: FauxProcessus(journal, ""))
        horloge = Horloge()
        monkeypatch.setattr(R.time, "time", horloge)
        monkeypatch.setattr(R.time, "sleep", lambda s: setattr(horloge, "t", horloge.t + s))
        with pytest.raises(R.RoutageFige) as fige:
            R._run_freerouting(("java", "fr.jar"), tmp_path / "b.dsn", tmp_path / "b.ses",
                               3000, nets_routables=48)
        assert fige.value.routed_percent == 0

    def test_rejeu_partiel_non_surveille(self, monkeypatch, tmp_path):
        journal = tmp_path / "freerouting.log"
        journal.write_text("")
        monkeypatch.setattr(R, "_FREEROUTING_LOG", journal)
        procs = []
        monkeypatch.setattr(R.subprocess, "Popen",
                            lambda cmd, **kw: procs.append(
                                FauxProcessus(journal, _passes(1, 170, unrouted=6))) or procs[-1])
        horloge = Horloge()
        monkeypatch.setattr(R.time, "time", horloge)
        monkeypatch.setattr(R.time, "sleep", lambda s: setattr(horloge, "t", horloge.t + s))
        # Seul le budget l arrete : TimeoutExpired, jamais RoutageFige.
        with pytest.raises(subprocess.TimeoutExpired):
            R._run_freerouting(("java", "fr.jar"), tmp_path / "b.dsn", tmp_path / "b.ses",
                               60, surveiller=False)
        import inspect
        assert "surveiller=False" in inspect.getsource(R._board_partiel_par_cli)

    def test_niveau_2_laisse_remonter_la_stagnation(self):
        import inspect
        src = inspect.getsource(R._route_auto_once)
        niveau2 = src[src.index("--- Niveau 2"):src.index("--- Niveau 3")]
        assert "except RoutageFige" in niveau2
        assert niveau2.index("except RoutageFige") < niveau2.index("except Exception")
        assert "nets_routables=net_count" in niveau2


# --------------------------------------------------------------------------
# Le chrono de chaque tirage
# --------------------------------------------------------------------------
class TestChronoDuTirage:
    def test_format(self):
        ligne = R._chrono_tirage(2, 184.4, 1080.2, 312.0, "freerouting-cli")
        assert ligne == ("chrono tirage 2 couches : preparation 184 s, moteur 1080 s "
                         "(freerouting-cli), finitions 312 s, total 1577 s")

    def test_route_auto_journalise_le_chrono(self):
        import inspect
        src = inspect.getsource(R.route_auto)
        assert src.count("_chrono_tirage(") >= 2, "tirage abouti ET tirage fige"

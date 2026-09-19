"""La JVM Freerouting est recyclee apres chaque routage, sous le verrou.

⚠️ Mesure du 2026-09-19. Au repos, AUCUN routage en cours, la JVM consommait
104 a 113 % d'un coeur et 2,5 Go. Un seul thread, ne pendant le 2e run d'une
serie et jamais arrete depuis (8 677 s de CPU cumule, ~2 h 25 a plein coeur) :

    "Thread-17" RUNNABLE
      at java.util.LinkedList.toArray
      at app.freerouting.management.RoutingJobScheduler.lambda$new$2(RoutingJobScheduler.java:58)

C'est l'ordonnanceur de Freerouting (v2.1.0, build 1c1edc12). Son code :

    while (true) {
      while (jobs.stream().count() > 0) { ... }   // AUCUNE pause ici
      Thread.sleep(250);                           // seulement si la file est VIDE
    }

Un job termine n'est JAMAIS retire de la file (seul `clearJobs(sessionId)`
le fait, et aucune route de l'API v1 ne l'appelle ; `cancel` repond 501,
aucune suppression de session). Des le premier routage de sa vie, la JVM
tourne donc a vide pour toujours — et la file garde chaque board en memoire.
Meme boucle en v2.2.4.

Le remede est deja dans le service : `_tuer_la_jvm` tue la JVM de l'API sans
toucher a la boucle de l'entrypoint qui la relance, puis attend qu'elle
reponde. Une JVM neuve a une file vide. On la recycle a la FIN de chaque
routage, ENCORE SOUS le verrou : aucun autre routage ne peut demarrer pendant
qu'elle redemarre, et le recyclage a lieu meme si le routage leve.
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


@pytest.fixture
def journal(monkeypatch):
    evenements: list[str] = []

    @contextlib.contextmanager
    def verrou_temoin(*a, **k):
        evenements.append("verrou pris")
        try:
            yield
        finally:
            evenements.append("verrou rendu")

    monkeypatch.setattr(R, "verrou_de_routage", verrou_temoin)
    monkeypatch.setattr(R, "_tuer_la_jvm", lambda *a, **k: evenements.append("jvm recyclee") or True)
    # Un routage qui a envoye un job : la file de la JVM n est plus vide.
    monkeypatch.setattr(R, "_JOBS_DEPUIS_RECYCLAGE", 1)
    return evenements


def test_la_jvm_est_recyclee_apres_le_routage_et_sous_le_verrou(journal):
    route = R._un_seul_routage_a_la_fois(lambda req: journal.append("routage") or "resultat")
    assert route(object()) == "resultat"
    assert journal == ["verrou pris", "routage", "jvm recyclee", "verrou rendu"]


def test_la_jvm_est_recyclee_meme_si_le_routage_leve(journal):
    def routage_qui_casse(req):
        journal.append("routage")
        raise RuntimeError("panne")

    route = R._un_seul_routage_a_la_fois(routage_qui_casse)
    with pytest.raises(RuntimeError, match="panne"):
        route(object())
    assert journal == ["verrou pris", "routage", "jvm recyclee", "verrou rendu"]


def test_un_recyclage_en_echec_ne_change_pas_le_resultat_du_routage(journal, monkeypatch):
    def recyclage_qui_casse(*a, **k):
        raise OSError("pkill introuvable")

    monkeypatch.setattr(R, "_tuer_la_jvm", recyclage_qui_casse)
    route = R._un_seul_routage_a_la_fois(lambda req: "resultat")
    assert route(object()) == "resultat"


def test_sans_job_envoye_depuis_le_dernier_recyclage_on_ne_recycle_pas(journal, monkeypatch):
    """Revue du 2026-09-19 : une JVM deja relancee apres le dernier job (job
    abandonne tue en fin de routage), ou jamais sollicitee (repli CLI), a une
    file VIDE — la recycler couterait ~9 s sous le verrou pour rien."""
    monkeypatch.setattr(R, "_JOBS_DEPUIS_RECYCLAGE", 0)
    route = R._un_seul_routage_a_la_fois(lambda req: journal.append("routage") or "resultat")
    assert route(object()) == "resultat"
    assert "jvm recyclee" not in journal


def test_un_job_envoye_apres_un_abandon_fait_recycler_encore(journal, monkeypatch):
    """Le cas que la suggestion « ne pas recycler deux fois » aurait casse : la
    JVM est tuee en cours de routage (abandon), puis d autres tirages la
    remplissent. Il FAUT recycler a la fin."""
    monkeypatch.setattr(R, "_JOBS_DEPUIS_RECYCLAGE", 0)

    def routage(req):
        R._noter_job_envoye()          # un tirage apres l abandon
        return "resultat"

    assert R._un_seul_routage_a_la_fois(routage)(object()) == "resultat"
    assert "jvm recyclee" in journal


def test_une_jvm_vraiment_relancee_remet_le_compteur_a_zero(monkeypatch):
    monkeypatch.setattr(R, "_JOBS_DEPUIS_RECYCLAGE", 3)
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    monkeypatch.setattr(R, "_find_freerouting_api", lambda: "http://127.0.0.1:37864")
    assert R._tuer_la_jvm() is True
    assert R._JOBS_DEPUIS_RECYCLAGE == 0


def test_une_jvm_qui_ne_revient_pas_garde_le_compteur(monkeypatch):
    # Pas revenue = on ne sait pas si la file est vide : on ne le pretend pas.
    monkeypatch.setattr(R, "_JOBS_DEPUIS_RECYCLAGE", 3)
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    monkeypatch.setattr(R, "_find_freerouting_api", lambda: None)
    assert R._tuer_la_jvm(attente_s=0.0) is False
    assert R._JOBS_DEPUIS_RECYCLAGE == 3


def test_le_recyclage_se_coupe_par_reglage_pour_un_a_b(journal, monkeypatch):
    import tools.reglages_banc as reglages

    monkeypatch.setattr(reglages, "reglage",
                        lambda nom, defaut=None: False if nom == "recycler_jvm_apres_routage" else defaut)
    route = R._un_seul_routage_a_la_fois(lambda req: journal.append("routage") or "resultat")
    assert route(object()) == "resultat"
    assert "jvm recyclee" not in journal

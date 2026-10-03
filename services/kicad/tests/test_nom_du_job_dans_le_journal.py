"""La boucle d'attente retrouve le job dans le journal, même sans son nom API.

Carte-09 compacte, 2026-09-28 : après deux relances de la JVM, deux jobs de
repli GND ont tourné 999 passes sans progrès (13,5 et 7,5 min), sans qu'aucune
coupure ne tire — ni la fenêtre de passes, ni les 300 s sans progrès. La
seule condition qui désarme les deux à la fois : le bloc de mesure est sauté
quand le `short_name` de l'API est vide ou absent du journal. Le job y figure
pourtant, sous son étiquette : on le lit là.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402

LIGNE = ("2026-09-29 00:02:05.000 INFO   [{job}] Auto-router pass #{p} on board 'x' "
         "was completed in 0.50 seconds with the score of 983.54 ({u} unrouted), using 1 CPU")


def _journal(job, passes):
    return "\n".join(LIGNE.format(job=job, p=p, u=u) for p, u in passes) + "\n"


def test_l_etiquette_du_journal_est_lue():
    # Garde du parseur lui-même : sans elle, les tests suivants passeraient
    # par accident sur un journal dont aucune ligne n est reconnue.
    texte = _journal(r"59CBBB\17EA61", [(1, 6), (2, 6)])
    assert {m.group(1) for m in R._LIGNE_PASSE_RE.finditer(texte)} == {"17EA61"}


def test_le_nom_api_present_dans_le_journal_est_garde():
    texte = _journal(r"59CBBB\17EA61", [(1, 6), (2, 6)])
    assert R._nom_du_job_dans_le_journal(texte, "17EA61") == "17EA61"


def test_sans_nom_api_on_prend_l_unique_job_du_journal():
    texte = _journal(r"59CBBB\17EA61", [(1, 6), (2, 6)])
    assert R._nom_du_job_dans_le_journal(texte, "") == "17EA61"
    assert R._nom_du_job_dans_le_journal(texte, "ABCDEF") == "17EA61"


def test_deux_jobs_dans_le_journal_on_ne_devine_pas():
    texte = _journal(r"AAAAAA\111111", [(1, 5)]) + _journal(r"BBBBBB\222222", [(1, 3)])
    assert R._nom_du_job_dans_le_journal(texte, "") == ""
    assert R._nom_du_job_dans_le_journal(texte, "222222") == "222222"


def test_journal_vide():
    assert R._nom_du_job_dans_le_journal("", "ABC123") == "ABC123"


def test_la_boucle_utilise_le_nom_retrouve():
    src = (RACINE / "routers" / "routing.py").read_text(encoding="utf-8")
    assert "nom_job = _nom_du_job_dans_le_journal(journal_du_job, short_name)" in src
    assert "plat = _passes_sans_progres(journal_du_job, nom_job)" in src
    assert "if _FREEROUTING_LOG.is_file():" in src

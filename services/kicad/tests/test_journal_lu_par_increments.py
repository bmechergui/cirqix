"""Le journal Freerouting est lu par INCREMENTS — jamais relu en entier.

Voir `tools/journal_freerouting.py` : un journal de 564 Mo relu a chaque tour
de sondage tenait le GIL 6 a 9 s, et le superviseur uvicorn tuait le worker
(ping sans reponse en 5 s). Trois tirages sur quatre perdus le 2026-09-10.

Les fixtures ecrivent en BINAIRE : sous Windows, le mode texte traduit le
retour a la ligne en CRLF et la comparaison echoue pour une raison etrangere
au lecteur.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools.journal_freerouting import LecteurIncremental  # noqa: E402


def _ajouter(chemin: Path, octets: bytes) -> None:
    with open(chemin, "ab") as f:
        f.write(octets)


class TestLecture:
    def test_ignore_ce_qui_precede_sa_creation(self, tmp_path):
        j = tmp_path / "freerouting.log"
        j.write_bytes(b"ancien job, des millions de lignes\n" * 1000)
        lecteur = LecteurIncremental(j)
        assert lecteur.lire() == ""
        _ajouter(j, b"[ABC] pass #1\n")
        assert lecteur.lire() == "[ABC] pass #1\n"

    def test_accumule_sans_relire(self, tmp_path):
        j = tmp_path / "freerouting.log"
        j.write_bytes(b"")
        lecteur = LecteurIncremental(j)
        _ajouter(j, b"a\n")
        lecteur.lire()
        _ajouter(j, b"b\n")
        assert lecteur.lire() == "a\nb\n"
        assert lecteur.offset == 4

    def test_un_journal_tronque_repart_du_debut(self, tmp_path):
        j = tmp_path / "freerouting.log"
        j.write_bytes(b"x" * 100)
        lecteur = LecteurIncremental(j)
        j.write_bytes(b"neuf\n")
        assert lecteur.lire() == "neuf\n"

    def test_un_journal_absent_rend_vide_sans_lever(self, tmp_path):
        lecteur = LecteurIncremental(tmp_path / "absent.log")
        assert lecteur.lire() == ""


class TestCablage:
    def test_la_boucle_de_sondage_ne_relit_jamais_le_journal_entier(self):
        from routers import routing
        code = "\n".join(l.split("#")[0] for l in
                         inspect.getsource(routing._route_with_freerouting_api).splitlines())
        assert "_FREEROUTING_LOG.read_text" not in code, (
            "un read_text du journal entier tient le GIL > 5 s et fait tuer le worker")
        assert "LecteurIncremental" in code

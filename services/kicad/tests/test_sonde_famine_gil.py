"""La sonde de famine du GIL est armee dans chaque worker, et elle tire quand
un thread Python est affame — pas quand il tourne.

Voir `tools/sonde_gil.py` et `docs/DECISIONS.md` (2026-09-10) : un SIGKILL du
superviseur uvicorn ne laisse aucune trace ; la sonde ecrit la pile AVANT.
"""
from __future__ import annotations

import faulthandler
import re
import subprocess
import sys
import time
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import sonde_gil  # noqa: E402


def _dans_un_processus_neuf(lignes: list[str], tmp_path: Path) -> str:
    """Execute `lignes` dans un interprete NEUF et rend ce que faulthandler y a ecrit.

    ⚠️ `faulthandler` n a qu UN minuteur par processus. La sonde de production
    (`_boucle`) le re-arme chaque seconde des qu un test a importe `main` —
    `test_service_security`, `test_rl_*` — et remplace alors le minuteur de
    0,2 s pose ici avant qu il ne tire. Mesure du 2026-09-13 : la suite entiere
    dans un seul processus (CI, image Docker) rendait `assert "Timeout" in ""`,
    la meme suite en local passait selon l ordre. Un processus neuf n a pas de
    sonde.
    """
    sortie = tmp_path / "s.txt"
    script = "\n".join(
        ["import faulthandler, time", f"with open({str(sortie)!r}, 'w') as f:"]
        + ["    " + l for l in lignes]
        + ["    faulthandler.cancel_dump_traceback_later()", ""]
    )
    subprocess.run([sys.executable, "-c", script], check=True, timeout=30)
    return sortie.read_text()


def test_le_minuteur_re_arme_ne_tire_pas(tmp_path):
    # faulthandler ecrit sur un DESCRIPTEUR : un vrai fichier, pas un StringIO.
    texte = _dans_un_processus_neuf([
        "for _ in range(4):",
        "    faulthandler.dump_traceback_later(0.3, repeat=False, file=f)",
        "    time.sleep(0.1)",
    ], tmp_path)
    assert texte == ""


def test_le_minuteur_non_re_arme_tire(tmp_path):
    """Simule la famine : personne ne re-arme pendant plus que le seuil."""
    texte = _dans_un_processus_neuf([
        "faulthandler.dump_traceback_later(0.2, repeat=False, file=f)",
        "time.sleep(0.6)",
    ], tmp_path)
    assert "Timeout" in texte and "Thread" in texte


def test_armee_une_seule_fois_par_processus(monkeypatch):
    monkeypatch.setattr(sonde_gil, "_demarree", False)
    assert sonde_gil.armer_la_sonde_de_famine(seuil_s=60.0) is True
    assert sonde_gil.armer_la_sonde_de_famine(seuil_s=60.0) is False
    faulthandler.cancel_dump_traceback_later()


def test_le_seuil_est_sous_les_cinq_secondes_du_superviseur():
    assert 0 < sonde_gil.SEUIL_S < 5.0


def test_main_arme_la_sonde():
    texte = (_SERVICE / "main.py").read_text(encoding="utf-8")
    code = "\n".join(l.split("#")[0] for l in texte.splitlines())
    assert re.search(r"armer_la_sonde_de_famine\(", code), (
        "la sonde n est pas armee dans le service : un prochain SIGKILL "
        "du superviseur restera sans trace")

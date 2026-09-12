"""Le superviseur uvicorn tolere un worker OCCUPE — voir `lancer_service.py`.

Mesure du 2026-09-10 : deux workers abattus en 5 s, l un dans un parseur pur
Python de 0,15 s, pendant que la VM paginait. Un worker qui route n est pas
pendu.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

import lancer_service as L  # noqa: E402


def test_la_tolerance_est_posee_sur_les_deux_methodes_du_superviseur():
    import uvicorn.supervisors.multiprocess as m
    anciens = (m.Process.ping.__defaults__, m.Process.is_alive.__defaults__)
    try:
        assert L.elargir_la_tolerance(42.0) == 42.0
        assert m.Process.ping.__defaults__ == (42.0,)
        assert m.Process.is_alive.__defaults__ == (42.0,)
    finally:
        m.Process.ping.__defaults__, m.Process.is_alive.__defaults__ = anciens


def test_la_tolerance_par_defaut_depasse_les_cinq_secondes_codees_en_dur():
    assert L.TOLERANCE_PING_S >= 20.0


def test_le_superviseur_appelle_bien_ces_methodes_sans_argument():
    """Si uvicorn change de forme, la garde doit le dire : les valeurs par
    defaut ne servent que si le superviseur les laisse s appliquer."""
    import inspect
    import uvicorn.supervisors.multiprocess as m
    src = inspect.getsource(m)
    assert re.search(r"process\.is_alive\(\)", src), "is_alive() n est plus appele sans argument"
    assert "def ping(self, timeout: float" in src and "def is_alive(self, timeout: float" in src


def test_l_entrypoint_lance_le_service_par_le_lanceur():
    texte = (_SERVICE / "docker-entrypoint.sh").read_text(encoding="utf-8")
    code = "\n".join(l.split("#")[0] for l in texte.splitlines())
    assert "lancer_service.py" in code, "l entrypoint lance uvicorn nu : tolerance de 5 s"
    assert not re.search(r"^\s*exec uvicorn ", code, re.M)

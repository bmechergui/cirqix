"""Le routeur recoit des degagements 5 % plus larges que la regle : mesure du
2026-09-12, « clearance 0.2000 mm ; actual 0.1987 mm » entre une piste du
routeur et une pastille — l aller-retour Specctra arrondit sous la regle."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402

_DSN = """(structure
    (rule
      (width 250)
      (clearance 200)
      (clearance 50 (type smd_smd))
    )
  )"""


def test_chaque_clearance_est_margee():
    out = R._marger_les_clearances(_DSN)
    assert "(clearance 210)" in out and "(clearance 52.5 (type smd_smd))" in out
    assert "(width 250)" in out


def test_la_marge_est_petite_et_positive():
    assert 1.01 <= R._MARGE_CLEARANCE_DSN <= 1.15


def test_l_export_applique_la_marge():
    code = "\n".join(l.split("#")[0] for l in inspect.getsource(R._export_specctra).splitlines())
    assert "_marger_les_clearances(" in code

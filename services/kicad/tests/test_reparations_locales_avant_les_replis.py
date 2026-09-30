"""Les reparations GND locales passent AVANT les replis Freerouting.

Mesure du 2026-09-29, carte-09 a 2 couches : Freerouting rend 100 % en 2 min,
la coulee du plan isole 1 ou 2 broches GND, et les replis GND (qui relancent
Freerouting) coutent 1167 s de finitions pour rien. Les reparations locales et
deterministes — connexion pleine d un relief affame, courte piste GND d un amas
orphelin, retrait des ilots, fanout — existaient deja, mais APRES les replis.
Avis concordant de Codex, Grok, GLM et OpenCode : les passer d abord, et ne
payer un repli que s il reste une orpheline.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402


def test_l_ordre_contraint_est_garde(monkeypatch):
    vu = []
    for nom in ("_reparer_reliefs_affames", "_relier_les_amas_orphelins",
                "_retirer_ilots_flottants", "_fanout_pads_isolees"):
        monkeypatch.setattr(R, nom, lambda b, _n=nom: vu.append(_n) or b + b".")
    assert R._reparations_locales_gnd(b"B") == b"B...."
    assert vu == ["_reparer_reliefs_affames", "_relier_les_amas_orphelins",
                  "_retirer_ilots_flottants", "_fanout_pads_isolees"]


def test_route_auto_repare_localement_avant_les_replis():
    src = inspect.getsource(R.route_auto)
    locale = src.index("final = _reparations_locales_gnd(final)")
    assert locale < src.index("_repli_gnd_cible_iteratif(")
    assert locale < src.index("rap_final = _rapport_drc(final)"), \
        "les orphelines se mesurent APRES la reparation locale"


def test_on_ne_repasse_que_si_un_repli_a_change_le_board():
    src = inspect.getsource(R.route_auto)
    apres = src[src.index("_repli_gnd_cible_iteratif("):]
    assert "if final != apres_locales:" in apres
    assert "_reparations_locales_gnd(final)" in apres

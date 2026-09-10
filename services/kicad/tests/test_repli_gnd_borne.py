"""Le repli GND ne se paie que sur une carte PRESQUE complete.

Mesure du 2026-09-10 sur carte-08 : 17 min pour passer de 36 a 33
connexions manquantes, puis 11 min pour un repli refuse. Il existe pour
refermer les dernieres broches d une carte a portee, pas pour en sauver une
a 56 %.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


def test_quelques_manquantes_valent_le_repli():
    assert R._repli_gnd_vaut_le_coup(0) and R._repli_gnd_vaut_le_coup(R._REPLI_GND_MAX_MANQUANTES)


def test_beaucoup_de_manquantes_ne_le_valent_pas():
    assert not R._repli_gnd_vaut_le_coup(36) and not R._repli_gnd_vaut_le_coup(R._REPLI_GND_MAX_MANQUANTES + 1)


def test_le_seuil_couvre_les_cas_qui_ont_marche_et_coupe_carte_08():
    """Historique retenu : (2, 0) -> (0, 1), (0, 73)... non ; carte-08 : 36 et 10 manquantes."""
    assert 3 <= R._REPLI_GND_MAX_MANQUANTES < 10


def test_le_reglage_est_lu():
    from tools import reglages_banc
    original = reglages_banc.reglage
    try:
        reglages_banc.reglage = lambda nom, defaut=None: 50 if nom == "repli_gnd_max_manquantes" else defaut
        assert R._repli_gnd_vaut_le_coup(36)
    finally:
        reglages_banc.reglage = original


def test_le_repli_est_garde_par_le_compte_de_manquantes():
    code = "\n".join(l.split("#")[0] for l in inspect.getsource(R.route_auto).splitlines())
    i_garde = code.find("_repli_gnd_vaut_le_coup(manquantes_avant)")
    i_repli = code.find("repli sur un routage incluant GND")
    assert i_garde != -1 and i_repli != -1 and i_garde < i_repli, (
        "le repli GND part sans regarder combien de connexions manquent")

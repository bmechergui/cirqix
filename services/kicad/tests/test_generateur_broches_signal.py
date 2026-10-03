"""Le generateur d exemples ne branche jamais un signal sur une broche
d alimentation du MCU, ni au-dela de son nombre de broches (2026-10-03).

stm32-100 branchait GPIO18, GPIO34 et GPIO50 sur les trois VSS du
STM32F103C8 (23, 35, 47), que KiCad relie entre elles : le PCB etait refuse
pour court-circuit. Il allait aussi jusqu a la broche 51 d un LQFP-48.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "scripts"))

import generer_exemples as G  # noqa: E402

_RAILS = {"GND", "+3.3V"}


def _broches_de_signal(c):
    return [p["pin"] for n in c["nets"] if n["name"] not in _RAILS
            for p in n["pins"] if p["ref"] == "U1"]


@pytest.mark.parametrize("nom,famille,cible", G.CAS)
def test_aucun_signal_sur_une_broche_reservee(nom, famille, cible):
    reservees, total = G._NON_SIGNAL[famille]
    broches = _broches_de_signal(G.circuit(famille, cible))
    assert broches
    assert not [b for b in broches if b in reservees or b > total]


@pytest.mark.parametrize("nom", ["stm32-60", "stm32-100", "arduino-uno", "nucleo-f401"])
def test_les_entrees_versionnees_sont_saines(nom):
    famille = dict((n, f) for n, f, _ in G.CAS)[nom]
    reservees, total = G._NON_SIGNAL[famille]
    c = json.loads((RACINE / "examples" / nom / "input" / "circuit.json").read_text(encoding="utf-8"))
    assert not [b for b in _broches_de_signal(c) if b in reservees or b > total]


def test_broche_signal_saute_les_reservees():
    assert G._broche_signal("stm32", 23) == 25
    assert G._broche_signal("stm32", 47) is None

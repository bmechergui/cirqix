"""Pas de repli GND sur un tirage qu'un signal empeche de livrer.

Mesure du 2026-09-29, carte-09 (placement fige du 24), tirage a 2 couches :

    preparation 48 s, moteur 149 s, FINITIONS 686 s, total 883 s
    il manque EXT3_2, EXT4_1, GND ; le palier suivant sera tente

Les 686 s sont surtout les replis GND (cible puis global), qui relancent
Freerouting pour relier la masse — « 4 manquantes -> 4 manquantes », refuses.
Or un repli GND ne relie aucun SIGNAL : avec EXT3_2 et EXT4_1 ouverts, le
tirage n'etait pas livrable, et l'escalade (D-2026-09-24-e : toute connexion
manquante fait monter) allait avoir lieu quoi qu'il arrive.

Au plafond, en revanche, il n'y a pas de palier suivant : le repli reste le
seul levier, on le garde.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402


def test_un_signal_manque_et_un_palier_reste_on_saute():
    assert R._replis_gnd_inutiles({"EXT3_2", "EXT4_1", "GND"}, ["GND"], 2, 8)


def test_seule_la_masse_manque_on_garde_les_replis():
    assert not R._replis_gnd_inutiles({"GND"}, ["GND"], 2, 8)
    assert not R._replis_gnd_inutiles({"GND", "AGND"}, ["GND"], 2, 8)


def test_au_plafond_on_garde_les_replis():
    assert not R._replis_gnd_inutiles({"EXT3_2", "GND"}, ["GND"], 8, 8)


def test_rien_ne_manque_on_ne_decide_rien():
    assert not R._replis_gnd_inutiles(set(), ["GND"], 2, 8)


def test_route_auto_consulte_la_regle_avant_les_replis():
    src = inspect.getsource(R.route_auto)
    regle = src.index("_replis_gnd_inutiles(")
    assert regle < src.index("_repli_gnd_cible_iteratif(")
    assert regle < src.index("_router_en_incluant_gnd(etendu")

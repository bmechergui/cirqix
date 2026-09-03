"""La carte doit tenir compte de la TAILLE des composants, pas de leur nombre.

Mesure du 2026-08-26, ESP32 du banc — 12 `courtyards_overlap` et 8
`shorting_items`, tous imputes au placement. La cause est en amont :

    courtyard de U1 (ESP32-WROOM) : 41,3 x 48,1 mm
    carte generee                 : 56,0 x 42,0 mm

Le courtyard est PLUS HAUT que la carte. Aucun placeur ne peut resoudre cela.

Le generateur dimensionnait par `18 + 1,9 x nombre_de_composants` : vingt
resistances et un module ESP32 donnaient la meme carte. Il tient desormais
compte de l encombrement reel de chaque boitier.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[1]
_SCRIPT = _RACINE / "scripts" / "generer_exemples.py"

# ⚠️ La suite tourne le plus souvent DANS le conteneur, ou `scripts/` est cuit
# dans l image et ne contient pas forcement ce fichier. On SAUTE en le disant,
# plutot que d echouer sur une absence qui ne prouve rien — le meme decalage
# conteneur/hote a deja fabrique un faux defaut (`test_docker_compose_mounts`).
if not _SCRIPT.is_file():
    pytest.skip(f"{_SCRIPT} absent (image sans scripts/)", allow_module_level=True)

_spec = importlib.util.spec_from_file_location("generer_exemples", _SCRIPT)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


class TestDimensionnement:
    def test_une_carte_a_module_est_plus_grande_qu_une_carte_a_passifs(self):
        petit = gen.circuit("stm32", 20)
        gros = gen.circuit("esp32", 20)
        assert gros["board_width_mm"] > petit["board_width_mm"], (
            "un module ESP32 demande plus de place que 20 passifs")

    def test_la_carte_contient_le_plus_gros_boitier(self):
        c = gen.circuit("esp32", 20)
        # Le module ESP32-WROOM a un courtyard mesure a ~41 x 48 mm.
        assert c["board_height_mm"] > 48.0, (
            f"carte de {c['board_height_mm']} mm pour un boitier de 48 mm")

    def test_la_carte_grandit_avec_le_nombre_de_composants(self):
        petit = gen.circuit("stm32", 20)
        grand = gen.circuit("stm32", 100)
        assert grand["board_width_mm"] > petit["board_width_mm"]

    def test_la_carte_reste_fabricable(self):
        # Au-dela de ~400 mm on sort des tarifs standard des fabricants.
        for cible in (17, 20, 30, 60, 100):
            for famille in ("stm32", "esp32"):
                c = gen.circuit(famille, cible)
                assert c["board_width_mm"] <= 400.0
                assert c["board_height_mm"] <= 400.0

"""L'image construit ET installe le moteur C++ du placement.

Mesure du 2026-09-30, carte-07 (44 composants), même board de départ : le
placement prenait 2144 s, dont 32 min dans le calcul des forces de répulsion
en Python pur (`_compute_component_repulsion_cpu`). `kct build-native` ne
construit que le routeur : `placement_cpp` n'était jamais installé. Compilé
et copié à sa place : 107 s.
"""
from __future__ import annotations

from pathlib import Path

DOCKERFILE = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")


def test_le_module_de_placement_est_construit():
    assert "--target placement_cpp" in DOCKERFILE


def test_il_est_copie_la_ou_kicad_tools_le_cherche():
    assert "src/kicad_tools/placement/" in DOCKERFILE


def test_le_build_echoue_s_il_ne_se_charge_pas():
    assert "assert ok(), why()" in DOCKERFILE
    assert DOCKERFILE.index("--target placement_cpp") < DOCKERFILE.index("assert ok(), why()")

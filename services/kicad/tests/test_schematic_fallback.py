"""Tests — fallback kicad-tools de generate_schematic (voie ② de /schematic/generate).

Bug trouvé par run_full_pipeline.py (2026-06-11) : depuis le passage au dépôt
officiel kicad-tools (2026-06-03), ``Schematic.__init__`` exige ``title`` —
``_generate_with_kicad_tools`` appelait ``Schematic()`` nu → TypeError → la
voie ② était morte en prod (cascade silencieuse vers le fallback TypeScript).
"""
from __future__ import annotations

from tools.schematic import (
    SchemaComponent,
    SchemaNet,
    SchemaPin,
    _generate_with_kicad_tools,
)


def _minimal_circuit() -> tuple[list[SchemaComponent], list[SchemaNet]]:
    comps = [
        SchemaComponent(ref="R1", value="10k",
                        footprint="Resistor_SMD:R_0805_2012Metric"),
        SchemaComponent(ref="C1", value="100nF",
                        footprint="Capacitor_SMD:C_0805_2012Metric"),
    ]
    nets = [SchemaNet(name="GND", pins=[SchemaPin(ref="R1", pin=2),
                                        SchemaPin(ref="C1", pin=2)])]
    return comps, nets


def test_kicad_tools_fallback_returns_schematic():
    """La voie ② construit un .kicad_sch valide (ne crashe pas sur Schematic())."""
    comps, nets = _minimal_circuit()

    content = _generate_with_kicad_tools(comps, nets)

    assert content, "la voie kicad-tools doit produire un schéma"
    assert content.lstrip().startswith("(kicad_sch")


def test_kicad_tools_fallback_has_title():
    """Le title block est renseigné (exigé par l'API kicad-tools officielle)."""
    comps, nets = _minimal_circuit()

    content = _generate_with_kicad_tools(comps, nets)

    assert content and "(title_block" in content

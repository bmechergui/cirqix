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


def test_kicad_tools_fallback_labels_at_pin_positions(tmp_path):
    """Les labels de net sont placés AUX positions exactes des pins.

    Sinon ``extract_netlist()`` ne relie pas les labels aux pins (positions
    différentes) et chaque pin finit dans son propre ``Net-(REF-PinN)``
    isolé — c'est la cause racine de la fragmentation du netlist PCB
    (83 nets au lieu de 12, routage bloqué à 0%, Leçon #4).
    """
    from kicad_tools.schematic.models.schematic import Schematic

    comps, nets = _minimal_circuit()

    content = _generate_with_kicad_tools(comps, nets)
    assert content

    sch_path = tmp_path / "schematic.kicad_sch"
    sch_path.write_text(content, encoding="utf-8")

    net_map = Schematic.load(str(sch_path)).extract_netlist()

    assert "GND" in net_map, f"GND absent — labels non reliés aux pins: {sorted(net_map)}"
    gnd_refs = {(p.symbol_ref, p.pin) for p in net_map["GND"]}
    assert gnd_refs == {("R1", "2"), ("C1", "2")}

"""TDD tests for the 'pro schematic' upgrade of circuit_synth fallback generator.

These tests cover the visual quality improvements that turn the schematic from
a functional MVP into a professional-looking deliverable:

  1. Standard `power:GND` triangle symbol (instead of plain "GND" text label)
  2. Standard `power:VCC` arrow symbol for power rails (+5V, +3V3, VCC, VDD…)
  3. Filled title block (project, date, revision, company)
  4. Non-power nets keep their text labels — no regression
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow imports from services/kicad/routers without installing the package
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from routers.circuit_synth import (  # noqa: E402
    _INLINE_LIB_SYMBOLS,
    _generate_schematic_fallback,
    _is_power_net,
)
from routers.circuit_synth import (  # noqa: E402
    SchemaComponent,
    SchemaNet,
    SchemaPin,
)


# --- Helpers -----------------------------------------------------------------


def _lm7805_components() -> list[SchemaComponent]:
    return [
        SchemaComponent(ref="U1", value="LM7805", footprint="TO-220", symbol="Regulator_Linear:L7805"),
        SchemaComponent(ref="C1", value="330nF", footprint="0603", symbol="Device:C"),
        SchemaComponent(ref="C2", value="100nF", footprint="0603", symbol="Device:C"),
        SchemaComponent(ref="J1", value="VIN_CONN", footprint="Conn_2", symbol="Connector_Generic:Conn_01x02"),
        SchemaComponent(ref="J2", value="VOUT_5V", footprint="Conn_2", symbol="Connector_Generic:Conn_01x02"),
    ]


def _lm7805_connections() -> list[SchemaNet]:
    # SchemaPin requires `pin: int` — use 1-indexed pad numbers as in
    # the real Layrix pipeline (LM7805 pads: 1=IN, 2=GND, 3=OUT).
    return [
        SchemaNet(
            name="VIN",
            pins=[
                SchemaPin(ref="J1", pin=1),
                SchemaPin(ref="U1", pin=1),
                SchemaPin(ref="C1", pin=1),
            ],
        ),
        SchemaNet(
            name="VOUT",
            pins=[
                SchemaPin(ref="U1", pin=3),
                SchemaPin(ref="C2", pin=1),
                SchemaPin(ref="J2", pin=1),
            ],
        ),
        SchemaNet(
            name="GND",
            pins=[
                SchemaPin(ref="J1", pin=2),
                SchemaPin(ref="U1", pin=2),
                SchemaPin(ref="C1", pin=2),
                SchemaPin(ref="C2", pin=2),
                SchemaPin(ref="J2", pin=2),
            ],
        ),
    ]


# --- Test: power net classification ------------------------------------------


class TestIsPowerNet:
    def test_gnd_is_power(self) -> None:
        assert _is_power_net("GND") is True

    def test_vcc_is_power(self) -> None:
        assert _is_power_net("VCC") is True

    def test_5v_is_power(self) -> None:
        assert _is_power_net("+5V") is True

    def test_3v3_is_power(self) -> None:
        assert _is_power_net("+3V3") is True

    def test_3_3v_is_power(self) -> None:
        assert _is_power_net("+3.3V") is True

    def test_vdd_is_power(self) -> None:
        assert _is_power_net("VDD") is True

    def test_vbus_is_power(self) -> None:
        assert _is_power_net("VBUS") is True

    def test_arbitrary_signal_is_NOT_power(self) -> None:
        assert _is_power_net("VIN") is False
        assert _is_power_net("VOUT") is False
        assert _is_power_net("NET1") is False
        assert _is_power_net("THR_DIS") is False
        assert _is_power_net("LED_K") is False

    def test_case_insensitive(self) -> None:
        assert _is_power_net("gnd") is True
        assert _is_power_net("Vcc") is True

    def test_empty_string_is_NOT_power(self) -> None:
        assert _is_power_net("") is False


# --- Test: inline lib_symbols includes power symbols -------------------------


class TestInlineLibSymbols:
    def test_includes_power_gnd(self) -> None:
        # Required so KiCanvas can render the (lib_id "power:GND") references
        assert '(symbol "power:GND"' in _INLINE_LIB_SYMBOLS

    def test_includes_power_vcc(self) -> None:
        assert '(symbol "power:VCC"' in _INLINE_LIB_SYMBOLS

    def test_power_gnd_has_polyline(self) -> None:
        # The triangle shape — any non-trivial GND symbol must include a polyline.
        # The library contains sub-symbols like (symbol "GND_0_1" ...); split on the
        # next TOP-LEVEL symbol declaration (one that uses a colon-separated lib_id).
        section = _INLINE_LIB_SYMBOLS.split('(symbol "power:GND"', 1)[1]
        # Stop at the next top-level symbol — power:VCC or any "Lib:Name" form
        next_top = section.find('(symbol "power:VCC"')
        if next_top < 0:
            next_top = section.find('(symbol "Device:')
        gnd_section = section if next_top < 0 else section[:next_top]
        assert "polyline" in gnd_section


# --- Test: schematic generation uses power symbols ---------------------------


class TestSchematicProGeneration:
    def test_title_block_is_filled(self) -> None:
        sch = _generate_schematic_fallback(_lm7805_components(), _lm7805_connections())
        assert "(title_block" in sch
        # Required fields per KiCad spec — at minimum a non-empty title
        assert "(title" in sch
        assert "(date" in sch
        assert "(rev" in sch
        assert "(company" in sch

    def test_company_is_layrix(self) -> None:
        sch = _generate_schematic_fallback(_lm7805_components(), _lm7805_connections())
        assert "Layrix" in sch

    def test_gnd_uses_power_symbol(self) -> None:
        sch = _generate_schematic_fallback(_lm7805_components(), _lm7805_connections())
        # At least one GND power-symbol instance must be placed
        assert '(lib_id "power:GND")' in sch

    def test_gnd_has_NO_text_label(self) -> None:
        # Regression: previous version wrote (label "GND" ...). The pro version
        # replaces these with (symbol (lib_id "power:GND") ...) entirely.
        sch = _generate_schematic_fallback(_lm7805_components(), _lm7805_connections())
        assert '(label "GND"' not in sch

    def test_non_power_nets_keep_text_labels(self) -> None:
        # VIN / VOUT are NOT power nets in our taxonomy → should still appear as labels
        sch = _generate_schematic_fallback(_lm7805_components(), _lm7805_connections())
        assert '(label "VIN"' in sch
        assert '(label "VOUT"' in sch

    def test_vcc_net_uses_power_symbol(self) -> None:
        # Synthetic case with a VCC rail
        comps = [
            SchemaComponent(ref="U1", value="ATmega328", footprint="TSSOP-8"),
            SchemaComponent(ref="C1", value="100nF", footprint="0603", symbol="Device:C"),
        ]
        nets = [
            SchemaNet(name="VCC", pins=[SchemaPin(ref="U1", pin=8), SchemaPin(ref="C1", pin=1)]),
        ]
        sch = _generate_schematic_fallback(comps, nets)
        assert '(lib_id "power:VCC")' in sch

    def test_5v_rail_uses_power_symbol(self) -> None:
        comps = [
            SchemaComponent(ref="U1", value="ATmega328", footprint="TSSOP-8"),
        ]
        nets = [
            SchemaNet(name="+5V", pins=[SchemaPin(ref="U1", pin=1)]),
        ]
        sch = _generate_schematic_fallback(comps, nets)
        assert '(lib_id "power:VCC")' in sch  # +5V rendered with VCC arrow shape

    def test_pcb_rect_unchanged(self) -> None:
        # Sanity check: the fallback still produces a valid kicad_sch envelope
        sch = _generate_schematic_fallback(_lm7805_components(), _lm7805_connections())
        assert sch.startswith("(kicad_sch")
        assert sch.endswith(")")
        assert '(paper "User"' in sch

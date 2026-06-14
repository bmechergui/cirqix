"""Tests — niveau-1 netlist Python pur de generate_pcb (tools/pcb.py).

Cause racine du routage 0% (Leçon #4, mémoire project-netlist-niveau1-broken) :
``_generate_with_kicad_tools`` importait ``build_netlist_from_schematic`` depuis
``kicad_tools.workflow._netlist`` — module INEXISTANT dans le dépôt officiel
vendoré → ModuleNotFoundError à 100% → fallback systématique kicad-cli → netlist
PCB fragmenté (1 net/pad, ``Net-(REF-PinN)``) → routage structurellement bloqué.

Le module réel est ``kicad_tools.operations.netlist``. Ce test verrouille :
1. l'import correct (le niveau-1 Python pur est réellement disponible) ;
2. qu'un schéma aux labels-sur-pins donne des nets multi-pads (pas de fragmentation).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from tools.schematic import (
    SchemaComponent,
    SchemaNet,
    SchemaPin,
    _generate_with_kicad_tools as _gen_schematic,
)


def _rc_circuit() -> tuple[list[SchemaComponent], list[SchemaNet]]:
    comps = [
        SchemaComponent(ref="R1", value="10k",
                        footprint="Resistor_SMD:R_0805_2012Metric"),
        SchemaComponent(ref="C1", value="100nF",
                        footprint="Capacitor_SMD:C_0805_2012Metric"),
    ]
    nets = [
        SchemaNet(name="GND", pins=[SchemaPin(ref="R1", pin=2),
                                    SchemaPin(ref="C1", pin=2)]),
        SchemaNet(name="SIG", pins=[SchemaPin(ref="R1", pin=1),
                                    SchemaPin(ref="C1", pin=1)]),
    ]
    return comps, nets


def test_niveau1_module_path_exists():
    """``build_netlist_from_schematic`` est importable depuis le bon module.

    L'ancien chemin ``kicad_tools.workflow._netlist`` n'existe pas → niveau-1
    cassé. Le bon chemin est ``kicad_tools.operations.netlist``.
    """
    from kicad_tools.operations.netlist import build_netlist_from_schematic  # noqa: F401


def test_niveau1_pure_python_netlist_not_fragmented():
    """Le niveau-1 Python pur relie les pins par net (pas 1 net/pad).

    C'est le test anti-régression de la fragmentation (83 nets au lieu de N).
    """
    from kicad_tools.operations.netlist import build_netlist_from_schematic

    comps, nets = _rc_circuit()
    sch = _gen_schematic(comps, nets)
    assert sch

    sch_path = Path(tempfile.mkdtemp()) / "schematic.kicad_sch"
    sch_path.write_text(sch, encoding="utf-8")

    nl = build_netlist_from_schematic(str(sch_path))
    by_name = {n.name: sorted((nd.reference, nd.pin) for nd in n.nodes)
               for n in nl.nets}

    assert by_name.get("GND") == [("C1", "2"), ("R1", "2")], by_name
    assert by_name.get("SIG") == [("C1", "1"), ("R1", "1")], by_name
    # Aucun net fragmenté mono-pad Net-(REF-PinN)
    fragmented = [n for n in by_name if n.startswith("Net-(") or n.startswith("unconnected-")]
    assert not fragmented, f"netlist fragmenté: {fragmented}"

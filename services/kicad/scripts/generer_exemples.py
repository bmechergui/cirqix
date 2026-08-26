"""Fabrique une serie de circuits de complexite croissante.

Objectif : eprouver la chaine sur autre chose qu un seul board. On monte le
nombre de composants par paliers jusqu a la centaine, en gardant des circuits
ELECTRIQUEMENT COHERENTS — un MCU, son alimentation, son quartz, ses
decouplages, ses connecteurs. Un tas de composants relies au hasard ne dirait
rien du routage reel : il faut des grappes fonctionnelles, des rails partages et
des broches qui vont quelque part.

    python3 scripts/generer_exemples.py

⚠️ Le nombre de COUCHES n est jamais impose : `route_auto` escalade tout seul
(2 -> 4 -> 6 ...) tant que le routage n aboutit pas. C est la seule facon
d obtenir la meme reponse sur une carte simple et sur une carte dense.
"""
from __future__ import annotations

import json
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[1]

# Empreintes volontairement standard : on teste le ROUTAGE, pas la resolution
# d empreintes exotiques.
_CMS = "Capacitor_SMD:C_0402_1005Metric"
_RES = "Resistor_SMD:R_0402_1005Metric"
_LED = "LED_SMD:LED_0603_1608Metric"


def _mcu(famille: str) -> dict:
    if famille == "esp32":
        return {"ref": "U1", "value": "ESP32-WROOM-32",
                "symbol": "RF_Module:ESP32-WROOM-32",
                "footprint": "RF_Module:ESP32-WROOM-32"}
    return {"ref": "U1", "value": "STM32F103C8T6",
            "symbol": "MCU_ST_STM32F1:STM32F103C8Tx",
            "footprint": "Package_QFP:LQFP-48_7x7mm_P0.5mm"}


def circuit(famille: str, cible: int) -> dict:
    """Circuit coherent d environ `cible` composants."""
    composants = [_mcu(famille)]
    liaisons: dict[str, list] = {"GND": [], "+3.3V": [], "VIN": []}

    def relier(net: str, ref: str, pin) -> None:
        liaisons.setdefault(net, []).append({"ref": ref, "pin": pin})

    # Regulateur : VIN -> +3.3V
    composants.append({"ref": "U2", "value": "AMS1117-3.3",
                       "symbol": "Regulator_Linear:AMS1117-3.3",
                       "footprint": "Package_TO_SOT_SMD:SOT-223-3_TabPin2"})
    relier("VIN", "U2", 3), relier("+3.3V", "U2", 2), relier("GND", "U2", 1)
    relier("+3.3V", "U1", 1), relier("GND", "U1", 8)

    # Connecteur d alimentation
    composants.append({"ref": "J1", "value": "5V",
                       "symbol": "Connector_Generic:Conn_01x02",
                       "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"})
    relier("VIN", "J1", 1), relier("GND", "J1", 2)

    # Le reste : grappes de decouplage, puis LED indicatrices, puis rappels.
    # Chaque condensateur relie +3.3V a GND — c est ce qui charge reellement le
    # plan de masse et met le routage a l epreuve.
    i = 1
    while len(composants) < cible:
        n = len(composants)
        if n % 3 != 2:
            ref = f"C{i}"
            composants.append({"ref": ref, "value": "100nF",
                               "symbol": "Device:C", "footprint": _CMS})
            relier("+3.3V", ref, 1), relier("GND", ref, 2)
        elif n % 6 == 2:
            ref = f"R{i}"
            composants.append({"ref": ref, "value": "10k",
                               "symbol": "Device:R", "footprint": _RES})
            relier("+3.3V", ref, 1), relier(f"SIG{i}", ref, 2)
            relier(f"SIG{i}", "U1", 10 + (i % 30))
        else:
            ref = f"D{i}"
            composants.append({"ref": ref, "value": "LED",
                               "symbol": "Device:LED", "footprint": _LED})
            relier(f"SIG{i - 1}", ref, 1), relier("GND", ref, 2)
        i += 1

    nets = [{"name": nom, "pins": pins} for nom, pins in liaisons.items() if len(pins) >= 2]
    cote = max(40.0, min(180.0, 18.0 + 1.9 * len(composants)))
    return {"components": composants, "nets": nets,
            "board_width_mm": round(cote, 1), "board_height_mm": round(cote * 0.75, 1)}


CAS = [
    ("stm32-baseline", "stm32", 17),
    ("esp32-baseline", "esp32", 20),
    ("stm32-30", "stm32", 30),
    ("stm32-60", "stm32", 60),
    ("stm32-100", "stm32", 100),
]


def main() -> int:
    for nom, famille, cible in CAS:
        c = circuit(famille, cible)
        d = _RACINE / "examples" / nom / "input"
        d.mkdir(parents=True, exist_ok=True)
        (d / "circuit.json").write_text(json.dumps(c, indent=2), encoding="utf-8")
        print(f"{nom:<18} {len(c['components']):3d} composants | "
              f"{len(c['nets']):2d} nets | {c['board_width_mm']}x{c['board_height_mm']} mm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

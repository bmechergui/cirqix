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
    if famille == "arduino":
        return {"ref": "U1", "value": "ATmega328P-AU",
                "symbol": "MCU_Microchip_ATmega:ATmega328P-AU",
                "footprint": "Package_QFP:TQFP-32_7x7mm_P0.8mm"}
    if famille == "nucleo":
        return {"ref": "U1", "value": "STM32F401RET6",
                "symbol": "MCU_ST_STM32F4:STM32F401RETx",
                "footprint": "Package_QFP:LQFP-64_10x10mm_P0.5mm"}
    return {"ref": "U1", "value": "STM32F103C8T6",
            "symbol": "MCU_ST_STM32F1:STM32F103C8Tx",
            "footprint": "Package_QFP:LQFP-48_7x7mm_P0.5mm"}


# Connecteurs de carte-mere, par famille. Ils ne sont pas decoratifs : leur
# ORIGINE est sur la broche 1, tres loin du centre de leur corps — c est
# exactement le cas qui faisait tomber la couronne sur le module ESP32.
_CONNECTEURS = {
    "arduino": [
        # TQFP-32 : 1-8 a gauche, 9-16 en bas, 17-24 a droite, 25-32 en haut.
        ("J10", "POWER", "Connector_Generic:Conn_01x08",
         "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical", 8, 2),
        ("J11", "ANALOG", "Connector_Generic:Conn_01x06",
         "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical", 6, 10),
        ("J12", "DIGITAL", "Connector_Generic:Conn_01x10",
         "Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical", 10, 18),
    ],
    "nucleo": [
        # ⚠️ La derniere valeur est la PREMIERE broche du MCU a utiliser, et
        # elle n est pas decorative. Un LQFP-64 numerote ses broches par cote :
        # 1-16 a gauche, 17-32 en bas, 33-48 a droite, 49-64 en haut. Le
        # connecteur de GAUCHE prend donc les broches de gauche, celui de
        # DROITE les broches de droite.
        ("J10", "MORPHO_L", "Connector_Generic:Conn_02x19_Odd_Even",
         "Connector_PinHeader_2.54mm:PinHeader_2x19_P2.54mm_Vertical", 38, 2),
        ("J11", "MORPHO_R", "Connector_Generic:Conn_02x19_Odd_Even",
         "Connector_PinHeader_2.54mm:PinHeader_2x19_P2.54mm_Vertical", 38, 34),
    ],
}


def circuit(famille: str, cible: int) -> dict:
    """Circuit coherent d environ `cible` composants.

    ⚠️ La premiere version reliait chaque condensateur entre +3,3 V et GND et ne
    creait un signal que tous les six composants. Resultat mesure le 2026-08-26
    sur l ESP32 du banc : 78 pastilles portant un net, dont 37 sur DEUX rails,
    et seulement 5 nets a deux pastilles ou plus.

    Une telle carte n eprouve pas le ROUTAGE, elle eprouve la distribution de
    puissance — et elle fausse la mesure : avec 4 nets routables au
    denominateur, chaque echec coute 25 points de pourcentage.

    On construit donc des GRAPPES : chaque peripherique est relie au MCU par un
    net de signal qui lui est propre. Les decouplages restent sur les rails,
    puisque c est leur role, mais ils cessent d etre la majorite.
    """
    composants = [_mcu(famille)]
    liaisons: dict[str, list] = {}

    def relier(net: str, ref: str, pin) -> None:
        liaisons.setdefault(net, []).append({"ref": ref, "pin": pin})

    # Alimentation : entree, regulateur, rails.
    composants.append({"ref": "U2", "value": "AMS1117-3.3",
                       "symbol": "Regulator_Linear:AMS1117-3.3",
                       "footprint": "Package_TO_SOT_SMD:SOT-223-3_TabPin2"})
    composants.append({"ref": "J1", "value": "5V",
                       "symbol": "Connector_Generic:Conn_01x02",
                       "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"})
    relier("VIN", "J1", 1), relier("VIN", "U2", 3)
    relier("GND", "J1", 2), relier("GND", "U2", 1)
    relier("+3.3V", "U2", 2), relier("+3.3V", "U1", 1)
    relier("GND", "U1", 8)

    # Connecteurs de carte-mere. Broche 1 sur GND, broche 2 sur +3,3 V, le
    # reste sur des signaux propres — un connecteur non relie ne serait qu un
    # obstacle, jamais une contrainte de routage.
    # ⚠️ Les broches du MCU etaient attribuees SEQUENTIELLEMENT a partir de 30,
    # sans regarder la geometrie. Mesure du 2026-08-28 sur la Nucleo : les seize
    # liaisons des DEUX connecteurs — l un a x = 50, l autre a x = 110 —
    # aboutissaient toutes sur la meme bande de 8 mm du MCU, par des fils de 44
    # a 62 mm. Seize signaux dans la meme fenetre : aucun routeur ne demele
    # cela, ni en ajoutant des couches, ni en re-tirant. La carte plafonnait a
    # 68 %.
    #
    # Un concepteur choisit ses broches selon le cote ou part le signal. C est
    # ce qui rend une vraie carte Nucleo routable, et c est ce qu on fait ici.
    for ref, val, sym, fp, n_broches, premiere in _CONNECTEURS.get(famille, []):
        composants.append({"ref": ref, "value": val,
                           "symbol": sym, "footprint": fp})
        relier("GND", ref, 1)
        relier("+3.3V", ref, 2)
        broche_mcu = premiere
        for k in range(3, min(n_broches, 10) + 1):
            relier("%s_%d" % (val, k), ref, k)
            relier("%s_%d" % (val, k), "U1", broche_mcu)
            broche_mcu += 1

    # Grappes de signal : une LED pilotee par une broche du MCU a travers sa
    # resistance de limitation. Chaque grappe cree DEUX nets a deux pastilles —
    # exactement ce qu un routeur doit resoudre.
    broche = 10
    i = 1
    while len(composants) < cible:
        reste = cible - len(composants)
        if reste >= 2 and i % 4 != 0:
            r, d_ = f"R{i}", f"D{i}"
            composants.append({"ref": r, "value": "330",
                               "symbol": "Device:R", "footprint": _RES})
            composants.append({"ref": d_, "value": "LED",
                               "symbol": "Device:LED", "footprint": _LED})
            relier(f"GPIO{i}", "U1", broche)
            relier(f"GPIO{i}", r, 1)
            relier(f"LED{i}", r, 2)
            relier(f"LED{i}", d_, 1)
            relier("GND", d_, 2)
            broche += 1
        else:
            # Un decouplage tous les quatre composants : leur vraie proportion
            # sur une carte reelle.
            c = f"C{i}"
            composants.append({"ref": c, "value": "100nF",
                               "symbol": "Device:C", "footprint": _CMS})
            relier("+3.3V", c, 1), relier("GND", c, 2)
        i += 1

    nets = [{"name": nom, "pins": pins} for nom, pins in liaisons.items() if len(pins) >= 2]
    l, h = _dimensions(composants)
    return {"components": composants, "nets": nets,
            "board_width_mm": l, "board_height_mm": h}


# Encombrement approximatif (courtyard) des boitiers qu on genere, en mm.
# Mesure sur les empreintes reelles ; le module ESP32-WROOM est de loin le plus
# gros, et c est lui qui dictait l echec.
_ENCOMBREMENT = {
    "RF_Module:ESP32-WROOM-32": (41.3, 48.1),
    "Package_QFP:LQFP-48_7x7mm_P0.5mm": (9.0, 9.0),
    "Package_QFP:TQFP-32_7x7mm_P0.8mm": (9.0, 9.0),
    "Package_QFP:LQFP-64_10x10mm_P0.5mm": (12.0, 12.0),
    "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical": (3.6, 17.0),
    "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical": (3.6, 22.1),
    "Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical": (3.6, 27.2),
    "Connector_PinHeader_2.54mm:PinHeader_2x19_P2.54mm_Vertical": (6.2, 50.0),
    "Package_TO_SOT_SMD:SOT-223-3_TabPin2": (8.9, 7.3),
    "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical": (3.6, 9.0),
    _RES: (1.6, 3.0),
    _CMS: (1.6, 3.0),
    _LED: (1.6, 3.0),
}
_DEFAUT = (3.0, 3.0)


def _dimensions(composants: list) -> tuple:
    """Taille de carte deduite de l encombrement REEL des boitiers.

    ⚠️ Le dimensionnement se faisait au NOMBRE de composants —
    `18 + 1,9 x n` — sans regarder leur taille. Vingt resistances et un module
    ESP32 donnaient la meme carte.

    Mesure du 2026-08-26 : courtyard de l ESP32-WROOM 41,3 x 48,1 mm pour une
    carte generee a 56 x 42. Le boitier etait PLUS HAUT que la carte, et le
    placement rendait 12 `courtyards_overlap` et 8 `shorting_items` — un echec
    qu aucun placeur ne pouvait resoudre.

    Deux contraintes, on prend la plus forte :
      - la surface totale des boitiers, avec de la marge de routage ;
      - le plus gros boitier, qui doit tenir avec ses degagements.
    """
    aires, maxi_l, maxi_h = 0.0, 0.0, 0.0
    for c in composants:
        l, h = _ENCOMBREMENT.get(c.get("footprint", ""), _DEFAUT)
        aires += l * h
        maxi_l, maxi_h = max(maxi_l, l), max(maxi_h, h)
    # Facteur 4 : un placement routable n occupe pas plus du quart de la
    # surface en cuivre, le reste sert aux pistes et aux degagements.
    par_surface = (aires * 4.0) ** 0.5
    # ⚠️ On CONSERVE le dimensionnement par nombre de composants comme plancher.
    # Il donnait 75 x 56 mm a 30 composants et 180 x 135 a 100 — des tailles qui
    # rendaient ZERO erreur de fabricabilite au banc du 2026-08-26. Le seul
    # critere de surface les ramenait a 40 x 30 et 51 x 38, nettement plus
    # serre : on aurait corrige l ESP32 en degradant les quatre autres.
    par_nombre = 18.0 + 1.9 * len(composants)
    # Le plus gros boitier doit tenir, avec 10 mm de degagement de chaque cote.
    cote = max(par_surface, par_nombre, maxi_l + 20.0, maxi_h + 20.0, 40.0)
    cote = min(cote, 400.0)
    return round(cote, 1), round(max(cote * 0.75, maxi_h + 20.0), 1)


CAS = [
    ("stm32-baseline", "stm32", 17),
    ("esp32-baseline", "esp32", 20),
    ("stm32-30", "stm32", 30),
    ("stm32-60", "stm32", 60),
    ("stm32-100", "stm32", 100),
    ("arduino-uno", "arduino", 35),
    ("nucleo-f401", "nucleo", 55),
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

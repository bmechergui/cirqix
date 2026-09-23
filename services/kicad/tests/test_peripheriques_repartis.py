"""Les périphériques se RÉPARTISSENT autour du centre — ils ne s'empilent pas.

⚠️ Mesure du 2026-09-23, `carte-10`, question de l'utilisateur devant le
rendu : « c'est quoi ce type de placement ? ». Les seize diodes `D10`..`D25`
formaient un tas d'un seul côté du LQFP, étiquettes de sérigraphie par-dessus
les unes des autres, pendant que trois quarts de la couronne restaient vides.

La cause est dans `_poser_les_peripheriques` :

- les SUIVEURS d'un même parent recevaient tous le MÊME angle,
  `atan2(parent - centre)`, et le même rayon de départ. Ils se rangeaient donc
  sur une seule file radiale, `le_long_du_rayon` ne s'écartant que lorsque la
  place manquait ;
- les ISOLÉS partaient tous de l'angle `0.0`, c'est-à-dire du même point.

RÈGLE : à parent égal, les suiveurs s'écartent de part et d'autre du rayon du
parent ; les isolés se répartissent sur toute la couronne.

⚠️ On ne déplace RIEN de ce qui est déjà posé — centres, connecteurs,
périphériques directs gardent exactement leur place. Seul l'ANGLE DE DÉPART de
la recherche change, et `le_long_du_rayon` reste seul juge de ce qui est libre.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools import graine_etoile as G  # noqa: E402


def _pad(net, x, y):
    return SimpleNamespace(net_name=net, position=(x, y), number="1")


def _fp(ref, pads, pos=(0.0, 0.0), demi=(0.8, 0.5), rot=0.0):
    g = SimpleNamespace(layer="F.CrtYd", start=(-demi[0], -demi[1]),
                        end=(demi[0], demi[1]))
    return SimpleNamespace(reference=ref, pads=pads, position=pos,
                           rotation=rot, graphics=[g])


def _mcu(ref="U1", pos=(0.0, 0.0), nets=("A", "B", "C", "D")):
    a, b, c, d = nets
    pads = [_pad(a, 4.0, 0.0), _pad(b, -4.0, 0.0), _pad(c, 0.0, 4.0),
            _pad(d, 0.0, -4.0),
            _pad("GND", 4.0, 1.0), _pad("GND", -4.0, 1.0),
            _pad("GND", 1.0, 4.0), _pad("GND", 1.0, -4.0)]
    return _fp(ref, pads, pos=pos, demi=(4.5, 4.5))


BORNES = (0.0, 60.0, 0.0, 60.0)


def _angles(positions, centre_pos, refs):
    """L'angle de chaque ref vue depuis le centre, en degrés."""
    out = {}
    for r in refs:
        if r not in positions:
            continue
        x, y = positions[r]
        out[r] = math.degrees(math.atan2(y - centre_pos[1], x - centre_pos[0]))
    return out


class TestLesSuiveursNeFontPasLaFile:
    """Quatre résistances sur la broche `A`, chacune tirant sa diode. Les
    quatre diodes sont des SUIVEURS du même parent : elles ne doivent pas
    occuper un seul rayon."""

    def _scene(self):
        fps = [_mcu()]
        for i in range(4):
            fps.append(_fp("R%d" % i, [_pad("A", -0.5, 0.0),
                                       _pad("S%d" % i, 0.5, 0.0)]))
            fps.append(_fp("D%d" % i, [_pad("S%d" % i, -0.5, 0.0),
                                       _pad("GND", 0.5, 0.0)]))
        return fps

    def test_les_suiveurs_occupent_plusieurs_directions(self):
        positions, centres = G.calculer(self._scene(), [], BORNES)
        assert centres and centres[0] == "U1"
        a = _angles(positions, positions.get("U1", (0.0, 0.0)),
                    ["D0", "D1", "D2", "D3"])
        assert len(a) == 4, "les quatre diodes doivent être placées"
        etendue = max(a.values()) - min(a.values())
        assert etendue >= 20.0, (
            "les suiveurs s'empilent sur un seul rayon : étendue de %.1f deg "
            "pour quatre diodes" % etendue)


class TestLesIsolesFontLeTourDuCentre:
    """Des composants qu'aucun lien ne rattache partaient TOUS de l'angle 0."""

    def _scene(self):
        fps = [_mcu()]
        for i in range(6):
            fps.append(_fp("X%d" % i, [_pad("N%d" % i, -0.5, 0.0),
                                       _pad("M%d" % i, 0.5, 0.0)]))
        return fps

    def test_ils_se_repartissent_sur_la_couronne(self):
        positions, centres = G.calculer(self._scene(), [], BORNES)
        a = _angles(positions, positions.get("U1", (0.0, 0.0)),
                    ["X%d" % i for i in range(6)])
        assert len(a) == 6
        etendue = max(a.values()) - min(a.values())
        assert etendue >= 90.0, (
            "les isolés s'entassent : étendue de %.1f deg pour six" % etendue)


class TestRienDeDejaPoseNeBouge:
    """⚠️ La répartition ne touche QUE l'angle de départ de la recherche.
    Un périphérique DIRECT vise toujours la broche qui le relie."""

    def test_le_peripherique_direct_garde_le_cote_de_sa_broche(self):
        fps = [_mcu(), _fp("R1", [_pad("A", -0.5, 0.0), _pad("X", 0.5, 0.0)])]
        positions, _ = G.calculer(fps, [], BORNES)
        x, _y = positions["R1"]
        cx = positions.get("U1", (0.0, 0.0))[0]
        assert x > cx, "R1 doit rester du côté de la broche A (x positif)"

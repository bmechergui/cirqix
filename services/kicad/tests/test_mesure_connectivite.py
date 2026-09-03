"""`GetConnectedItems()` a change de signature sous KiCad 10.

    TypeError: CONNECTIVITY_DATA.GetConnectedItems() takes from 2 to 3
               positional arguments but 4 were given

Le code passait `(pad, [PCB_PAD_T], False)` — trois arguments plus `self`. KiCad
10 n'en accepte plus qu'un ou deux.

⚠️ Ce defaut est reste invisible parce que `_measure_connectivity` n est appele
que par `_measured_routed_percent`, lui-meme reserve aux chemins FREEROUTING.
kicad-tools rend son propre pourcentage sans mesure. Or Freerouting n a jamais
tourne avant le 2026-08-21 : la sonde interrogeait un prefixe d URL inexistant.

C est le QUATRIEME defaut du meme motif dans la meme journee — ERC, plan de
masse, `SetIsFilled`, et celui-ci. Tous sur le chemin de Freerouting, tous
reveles en le reparant. Un chemin mort ne signale pas ses pannes : il faut le
ranimer pour les voir.

Consequence mesuree : `route_auto` levait sur toute reponse Freerouting, la
cascade retombait sur kicad-tools (698 s au lieu de 4), et l escalade de couches
ne pouvait jamais aboutir.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

_RUNNER = _SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py"


def _pcbnew_dispo() -> bool:
    try:
        import pcbnew  # noqa: F401
        return True
    except Exception:
        return False


class TestSignature:
    def test_les_deux_signatures_sont_supportees(self):
        """On ne code PAS une version en dur.

        Le service tourne sous KiCad 9 ou 10 selon l image : la forme a trois
        arguments doit rester tentee, et la forme a deux servir de repli. Une
        premiere version de ce test INTERDISAIT l ancien appel — c etait plus
        strict que juste, et cela aurait casse KiCad 9.
        """
        source = _RUNNER.read_text(encoding="utf-8")
        assert "except TypeError:" in source, "aucun repli de signature"
        assert source.count("GetConnectedItems(") >= 2, (
            "les deux formes doivent etre presentes"
        )
        # Le filtrage revient a l appelant sous KiCad 10.
        assert "i.Type() == pcbnew.PCB_PAD_T" in source


@pytest.mark.skipif(not _pcbnew_dispo(), reason="pcbnew absent")
class TestExecutionReelle:
    """Une garde de signature ne suffit pas : on execute vraiment le runner."""

    _BOARD = """(kicad_pcb
\t(version 20240108)
\t(generator "test")
\t(general (thickness 1.6))
\t(paper "A4")
\t(layers
\t\t(0 "F.Cu" signal)
\t\t(31 "B.Cu" signal)
\t\t(44 "Edge.Cuts" user)
\t)
\t(net 0 "")
\t(net 1 "GND")
\t(gr_rect (start 0 0) (end 50 40) (layer "Edge.Cuts"))
\t(footprint "R_0805" (layer "F.Cu") (at 10 10)
\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "GND"))
\t)
\t(footprint "R_0805" (layer "F.Cu") (at 30 10)
\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "GND"))
\t)
)"""

    def test_le_runner_rend_un_compte(self, tmp_path):
        pcb = tmp_path / "b.kicad_pcb"
        pcb.write_text(self._BOARD, encoding="utf-8")
        resultat = tmp_path / "r.json"

        proc = subprocess.run(
            [
                sys.executable,
                str(_RUNNER),
                json.dumps({
                    "operation": "measure_connectivity",
                    "pcb": str(pcb),
                    "result": str(resultat),
                }),
            ],
            capture_output=True, text=True, timeout=300, check=False,
        )

        assert proc.returncode == 0, f"runner en echec : {proc.stderr[-400:]}"
        assert resultat.is_file()
        # Deux pads GND non relies : le net est bien compte comme non route.
        assert json.loads(resultat.read_text(encoding="utf-8"))["unrouted_nets"] == 1

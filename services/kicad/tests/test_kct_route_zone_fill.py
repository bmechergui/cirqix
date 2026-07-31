"""Le board livré doit sortir avec ses zones REMPLIES.

Défaut trouvé le 2026-07-30 sur le board STM32 de `examples/stm32-validation`.
``ZoneGenerator.add_zone`` déclare le contour d'un plan mais ne le remplit pas :
les boards rendus par ``route_kct`` sortaient avec ``filled_polygon`` absent.

Deux conséquences, mesurées :

- **DRC** — 12 des 17 « connexions manquantes » GND étaient un artefact du
  non-remplissage. Le juge, lancé avec ``--refill-zones``, remplissait pour
  lui-même ce que le board ne contenait pas : 17 → 5 non connectés.
- **Fabrication** — une zone non remplie ne produit aucun cuivre à l'export
  Gerber : la carte livrée n'avait tout simplement pas de plan de masse.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kicad-tools" / "src"))

from tools import kct_route  # noqa: E402


def test_fill_zones_appelle_kct_zones_fill(monkeypatch, tmp_path):
    """Le remplissage passe par la commande native, pas par un algo maison."""
    vu: dict[str, list[str]] = {}

    def faux_run(cmd, **kwargs):
        vu["cmd"] = cmd
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"(kicad_pcb REMPLI)")
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(kct_route.subprocess, "run", faux_run)

    obtenu = kct_route._fill_zones(b"(kicad_pcb (zone))")

    assert obtenu == b"(kicad_pcb REMPLI)"
    assert "zones" in vu["cmd"] and "fill" in vu["cmd"]


def test_echec_du_remplissage_conserve_le_board_route(monkeypatch):
    """Perdre le routage serait pire que livrer un plan non rempli."""
    def faux_run(cmd, **kwargs):
        return type("P", (), {"returncode": 2, "stdout": "", "stderr": "boom"})()

    monkeypatch.setattr(kct_route.subprocess, "run", faux_run)

    original = b"(kicad_pcb (segment) (zone))"

    assert kct_route._fill_zones(original) == original


def test_exception_du_sous_processus_conserve_le_board(monkeypatch):
    def faux_run(cmd, **kwargs):
        raise OSError("binaire introuvable")

    monkeypatch.setattr(kct_route.subprocess, "run", faux_run)

    original = b"(kicad_pcb (segment))"

    assert kct_route._fill_zones(original) == original

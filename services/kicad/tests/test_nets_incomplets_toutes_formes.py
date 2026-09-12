"""`_nets_incomplets` lit le net entre crochets de TOUT objet du rapport, pas
seulement des `Pad` et `Zone`. carte-08, 2026-09-12 : une paire
« PTH pad 1 [EXT0_1] of J10 <-> Track [EXT0_1] » ne nommait aucun net, le
palier restait a 100 % avec une liaison manquante, et le DRC de la chaine
comptait cette liaison en erreur (« 100 %, 2 erreurs DRC »)."""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


def _rap(*paires):
    return {"unconnected_items": [{"items": [{"description": a}, {"description": b}]} for a, b in paires]}


def test_pth_pad_via_et_track_nomment_leur_net():
    r = _rap(("PTH pad 1 [EXT0_1] of J10", "Track [EXT0_1] on F.Cu, length 0.47 mm"),
             ("Via [GND] on F.Cu - B.Cu", "Via [GND] on F.Cu - B.Cu"),
             ("Track [SWDIO] on B.Cu, length 3 mm", "Zone [SWDIO] on B.Cu, priority 1"))
    assert R._nets_incomplets(r) == {"EXT0_1", "GND", "SWDIO"}


def test_les_formes_historiques_restent_reconnues():
    r = _rap(("Pad 12 [GND] of U1 on F.Cu", "Zone [GND] on F.Cu, priority 0"))
    assert R._nets_incomplets(r) == {"GND"}


def test_un_pourcentage_a_100_avec_une_liaison_manquante_est_impossible(monkeypatch):
    r = _rap(("PTH pad 1 [EXT0_1] of J10", "Track [EXT0_1] on F.Cu, length 0.47 mm"))
    monkeypatch.setattr(R, "_rapport_drc", lambda b: r)
    assert R._percent_verifie(b"board", 100, 49) < 100

"""Replis GND bornés (décision validée le 2026-10-01).

Banc des dix cartes du jour : les finitions font 50 % du temps de routage,
surtout les replis GND — tous refusés (historique : 11 replis, 0 retenu) —
puis la carte monte d'un palier et atteint 100 % en 2 à 5 min.
Avis concordant de Codex et Grok :
- repli GLOBAL seulement au plafond de couches (sous le plafond, l'escalade
  s'en charge) ;
- repli CIBLÉ avec un budget TOTAL de 60 s, pas par tour.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402


class Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_budget_total_du_cible(monkeypatch):
    horloge = Horloge()
    monkeypatch.setattr(R.time, "time", horloge)
    budgets = []

    def cible(etendu, req, budget_s, orphelines, deja_route):
        budgets.append(budget_s)
        horloge.t += 25  # chaque tour consomme 25 s
        return deja_route + b"+"

    monkeypatch.setattr(R, "_router_gnd_cible", cible)
    monkeypatch.setattr(R, "_bilan_drc", lambda b: (0, 10 - len(b)))
    monkeypatch.setattr(R, "_secours_est_meilleur", lambda a, b: True)
    monkeypatch.setattr(R, "_rapport_drc", lambda b: {})
    monkeypatch.setattr(R, "_pads_isolees_du_plan", lambda r, b: ["U1-8"])
    R._repli_gnd_cible_iteratif(b"E", None, 60, ["U1-8"], b"F")
    # 60 s : tour 1 (60 s restants), tour 2 (35 s) ; au tour 3 il reste 10 s < 30.
    assert len(budgets) == 2
    assert budgets[0] == 60 and 30 <= budgets[1] < 60


def test_route_auto_borne_le_cible_et_reserve_le_global_au_plafond():
    src = inspect.getsource(R.route_auto)
    assert "min(restant, _BUDGET_REPLI_CIBLE_S)" in src
    assert R._BUDGET_REPLI_CIBLE_S == 60
    i = src.index("secours = _router_en_incluant_gnd(etendu")
    avant = src[src.rindex("elif", 0, i):i]
    assert "palier >= max(essais)" in avant


def test_un_job_api_arrete_au_budget_est_tue():
    src = inspect.getsource(R._route_with_freerouting_api)
    fin = src.index('raise RuntimeError("Freerouting API timeout")')
    assert "_tuer_la_jvm()" in src[fin - 300:fin]

"""Le budget de routage doit valoir pour l'APPEL, pas pour chaque niveau.

`route_auto` enchaîne jusqu'à quatre routeurs. Chacun recevait `req.timeout_s`
EN ENTIER : un appel pouvait donc valoir plusieurs fois le budget demandé.

Mesuré le 2026-08-20 sur le board STM32, `timeout_s: 1800` : **2547 s** au
total — Niveau 1, puis Freerouting, puis le Niveau 4 qui relance `kct route`
avec les mêmes 1800 s. Le client, lui, calcule son échéance à partir d'UN budget
(`routingAbortMs = budget + marge`) : il raccroche donc pendant que le service
travaille encore, et le travail déjà fait part à la poubelle.

Un budget qui ne borne rien n'est pas un budget. On calcule une échéance UNIQUE
à l'entrée, et chaque niveau reçoit le temps RESTANT.

⚠️ Un niveau ne doit pas être lancé avec des miettes : sous
`_MIN_LEVEL_BUDGET_S`, on passe au suivant plutôt que de démarrer un travail
condamné — un routeur tué en cours ne rend rien, alors qu'un niveau plus rapide
pourrait encore aboutir.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


class TestBudgetRestant:
    def test_le_restant_decroit_avec_le_temps(self):
        assert routing_router._remaining_budget_s(1000.0, now=100.0) == 900
        assert routing_router._remaining_budget_s(1000.0, now=900.0) == 100

    def test_le_restant_ne_devient_jamais_negatif(self):
        # Un budget négatif passé à un sous-processus serait interprété comme
        # « pas de limite » par certains outils : plancher à zéro.
        assert routing_router._remaining_budget_s(1000.0, now=1500.0) == 0

    def test_un_budget_epuise_n_autorise_plus_de_niveau(self):
        assert not routing_router._budget_suffisant(0)
        assert not routing_router._budget_suffisant(5)
        assert routing_router._budget_suffisant(routing_router._MIN_LEVEL_BUDGET_S)


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_aucun_niveau_ne_recoit_le_budget_brut_de_la_requete(self):
        # `req.timeout_s` sert à CALCULER l'échéance, une seule fois. Le passer
        # tel quel à un niveau réintroduit la multiplication du budget.
        code = "\n".join(
            ligne for ligne in self.SOURCE.splitlines()
            if not ligne.lstrip().startswith("#")
        )
        appels_bruts = [
            ligne for ligne in code.splitlines()
            if "req.timeout_s" in ligne and "deadline" not in ligne
        ]
        assert appels_bruts == [], f"budget brut encore passé : {appels_bruts}"

    def test_l_echeance_est_calculee_une_seule_fois(self):
        assert self.SOURCE.count("deadline = _now() + req.timeout_s") == 1

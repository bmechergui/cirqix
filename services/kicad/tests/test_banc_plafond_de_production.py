"""Le banc appelle le routage comme la production : plafond et budget.

D-2026-09-24-f. ⚠️ `run_pipeline.py` prenait `max_layers` = 2 par DÉFAUT, et
1800 s de budget. Dix cartes sur quinze (01 à 06, les trois `driver-*`, et
`carte-07` qui l'écrivait en dur) ne pouvaient donc JAMAIS escalader : la règle
« toute connexion manquante fait monter d'un palier » (D-2026-09-24-e) était
inerte dans le banc. Mesuré le 2026-09-24 sur `carte-07` : 97 % à 2 couches,
seule la masse manquante, le service annonce « le palier suivant sera tenté »…
et rend la main, faute de plafond.

Même famille que « le banc mesurait ce que le produit ne fait pas »
(`auto_size_board`, 2026-09-23). Le plafond n'est pas une consigne : le routeur
part de 2 et ne monte que sur preuve d'échec — une carte qui tient en 2 couches
en garde 2. Le banc joue un client Pro Max ; en production, le plafond reste
celui du plan du client (`handleRouting`).

Le budget suit la formule de production, `routingSearchBudgetS(couches)` dans
`packages/agents/src/engines/routing-budget.ts` : min(600 + 300 × couches, 3600).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
_PIPELINE = _SERVICE / "examples" / "led-blinker-full-pipeline" / "run_pipeline.py"
_BUDGET_TS = _SERVICE.parents[1] / "packages" / "agents" / "src" / "engines" / "routing-budget.ts"


def _source() -> str:
    return _PIPELINE.read_text(encoding="utf-8")


class TestDefautsDuBanc:
    def test_le_plafond_par_defaut_est_celui_du_plan_le_plus_haut(self):
        assert 'schema.get("max_layers", 8)' in _source()

    def test_le_budget_par_defaut_suit_la_formule_de_production(self):
        source = _source()
        assert "600 + 300 * plafond" in source and "3600" in source

    def test_la_formule_du_banc_est_celle_du_client(self):
        """Si la production change sa formule, le banc doit la suivre."""
        if not _BUDGET_TS.is_file():
            return
        ts = _BUDGET_TS.read_text(encoding="utf-8")
        assert re.search(r"600 \+ Math\.max\(0, layers\) \* 300", ts)
        assert "ROUTING_SEARCH_BUDGET_S = 3600" in ts


class TestAucuneCarteNePlafonneA2:
    def test_aucun_schema_du_banc_n_interdit_l_escalade(self):
        fautifs = []
        for schema in sorted((_SERVICE / "examples").glob("*/input/schema.json")):
            try:
                donnees = json.loads(schema.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            plafond = donnees.get("max_layers")
            if plafond is not None and int(plafond) <= 2:
                fautifs.append(schema.parent.parent.name)
        assert not fautifs, "plafond a 2 couches : l escalade y est impossible — %s" % fautifs

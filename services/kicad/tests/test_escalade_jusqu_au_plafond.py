"""Le routage ne s'arrête qu'au résultat — D-2026-09-25-e (validée).

Banc du 2026-09-25 (`docs/mesures/ab-routage-prioritaire-2026-09-25.jsonl`),
carte-08, même placement : trois appels livrent 100 % à 4 couches ; un
quatrième monte 2 → 4 (77 %) → 6 (62 %), s'ARRÊTE sur « deux paliers sans
gain » sans essayer 8 couches, et livre son meilleur board, un 2 couches à
85 %, 7 connexions manquantes, 7 erreurs.

Deux maillons cassés, deux gardes :
1. tant que le meilleur board n'est pas livrable, l'escalade va jusqu'au
   plafond du plan — seul le budget l'arrête ;
2. la réponse dit le plus haut palier ESSAYÉ (`layers_tried`) : l'agrandissement
   de D-2026-09-11-b se déclenchait sur les couches du board LIVRÉ (2), donc
   jamais sur ce cas.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


def _code(fonction) -> str:
    return "\n".join(l.split("#")[0] for l in inspect.getsource(fonction).splitlines())


class TestPasDArretAvantLePlafond:
    def test_la_regle_des_paliers_sans_gain_a_disparu(self):
        assert not hasattr(R, "_escalade_epuisee")
        assert not hasattr(R, "_TOLERANCE_SANS_GAIN")
        assert "sans_gain" not in _code(R.route_auto)

    def test_seuls_le_succes_et_le_budget_arretent_l_escalade(self):
        """Chaque `break` de la boucle des paliers est une sortie : on les
        compte, pour qu'une règle d'arrêt ne revienne pas sans se voir."""
        code = _code(R.route_auto)
        debut = code.index("i_essai = 0")
        boucle = code[debut:code.index("return meilleur", debut)]
        raisons = [l.strip() for l in boucle.splitlines() if l.strip() == "break"]
        # Restent : dernière chance impossible, placement condamné (tous deux
        # rendent la main pour RE-PLACER), board déjà complet, budget épuisé.
        assert "sans gain" not in boucle
        assert len(raisons) == 4, raisons


class TestPalierEssaye:
    def test_la_reponse_porte_le_plus_haut_palier_essaye(self):
        assert "layers_tried" in R.RouteAutoResponse.model_fields
        assert R.RouteAutoResponse(layers=2).layers_tried is None

    def test_route_auto_le_renseigne_avant_de_rendre_le_meilleur(self):
        code = _code(R.route_auto)
        assert "palier_max_essaye = max(palier_max_essaye, palier)" in code
        fin = code.rindex("return meilleur")
        assert "layers_tried" in code[code.rindex("palier_max_essaye", 0, fin) - 400:fin]

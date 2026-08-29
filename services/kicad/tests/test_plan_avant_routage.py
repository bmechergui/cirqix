"""Le plan de masse est coule AVANT le routage, pas apres.

Sequence demandee par l utilisateur, repetee tout au long du 2026-08-27/28 :

    1. couler le plan de masse et raccorder les pattes qu il atteint
    2. router les SIGNAUX
    3. affiner : echappement fine-pitch, vias, couture des ilots

⚠️ La production coulait le plan APRES le routage. Le routeur ne voyait donc
jamais le cuivre de masse : il routait comme si la carte etait vide, puis on
posait le plan par-dessus. Deux consequences mesurees sur la Nucleo, meme
placement :

    plan coule APRES  (production)   68-71 % route
    plan coule AVANT  (4 couches)    94 % route, 4 manquantes

⚠️ La comparaison ci-dessus melangeait deux facteurs — l ordre du plan ET le
nombre de couches force. Elle indique une direction, elle ne la prouve pas
seule. La decision vient de l utilisateur, qui a reaffirme la sequence.

⚠️ `_add_ground_planes` n empile jamais un second plan : il regarde les couches
deja couvertes. L appel qui suivait le routage devient donc inoffensif, et on
le garde comme filet pour les chemins qui ne passent pas par la boucle.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")
BOUCLE = SOURCE[SOURCE.index("essais = _paliers_avec_tirages("):]
BOUCLE = BOUCLE[:BOUCLE.index("return meilleur")]


class TestSequence:
    def test_le_plan_est_coule_avant_l_appel_au_routeur(self):
        i = BOUCLE.index("_add_ground_planes(")
        j = BOUCLE.index("_route_auto_once(")
        assert i < j, (
            "le routeur doit VOIR le plan : coule apres, il route comme si la "
            "carte etait vide")

    def test_le_plan_est_rempli_avant_le_routage(self):
        # Un plan non rempli n est qu un contour : le routeur n en tiendrait
        # aucun compte. Meme defaut que celui trouve le 2026-08-23.
        avant = BOUCLE[:BOUCLE.index("_route_auto_once(")]
        assert "_fill_zones(" in avant

    def test_l_affinage_reste_apres_le_routage(self):
        # Etape 3 de la sequence : echappement, vias, couture — ils reparent ce
        # que le routeur n a pas pu relier, donc ils viennent APRES lui.
        apres = BOUCLE[BOUCLE.index("_route_auto_once("):]
        # ⚠️ `_recoudre_les_zones` est desormais appelee par
        # `_coudre_jusqu_au_bout`, qui la repete tant qu elle progresse.
        for etape in ("_fanout_pads_isolees(", "_recoudre_les_ilots(",
                      "_coudre_jusqu_au_bout("):
            assert etape in apres, "%s doit suivre le routage" % etape


class TestNonRegression:
    def test_le_plan_n_est_jamais_empile_deux_fois(self):
        # `_add_ground_planes` consulte les couches deja couvertes ; l appel
        # qui suit le routage devient inoffensif et sert de filet.
        i = SOURCE.index("def _add_ground_planes")
        assert "_couches_deja_couvertes(" in SOURCE[i:i + 2000]

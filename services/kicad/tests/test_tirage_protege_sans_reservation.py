"""Un tirage PROTÉGÉ ne réserve aucun via neuf : l'acquis porte déjà les siens.

Mesure du 2026-09-25, `carte-07`, placement gelé, passage 2 -> 4 couches, le
board à 97 % protégé (Freerouting CLI, même DSN à un ingrédient près) :

    protégé + liaison GND                 7 s    100 %
    protégé + vias réservés             220 s    100 %   (4 vias au même point)
    production (protégé + liaison + vias) > 240 s  aucune sortie

En production (API), ce même tirage rendait HTTP 500 puis 0 % à CHAQUE
changement de palier (carte-07, nucleo-f401). Le board protégé contient déjà
ses vias d'échappement, posés au palier précédent : en réserver de nouveaux par
dessus n'apporte rien et fait échouer le routeur.
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


class TestLaRegle:
    def test_un_tirage_protege_ne_reserve_rien(self):
        vias = [{"x": 1.0, "y": 2.0, "net": "GND"}]
        assert R._reservations_du_tirage(vias, protege=True) == []

    def test_un_tirage_libre_garde_ses_reservations(self):
        vias = [{"x": 1.0, "y": 2.0, "net": "GND"}]
        assert R._reservations_du_tirage(vias, protege=False) == vias


class TestCablage:
    def test_appliquee_apres_le_calcul_et_avant_la_liaison_gnd(self):
        """Avant la liaison : c'est elle qui ajoute le board placé aux pistes
        protégées — après elle, tout tirage paraîtrait « protégé »."""
        code = _code(R.route_auto)
        i_calcul = code.index("_VIAS_RESERVES = _nommer_les_nets(")
        i_regle = code.index("_reservations_du_tirage(")
        i_liaison = code.index("_relier_gnd_avant_routage(etendu")
        assert i_calcul < i_regle < i_liaison

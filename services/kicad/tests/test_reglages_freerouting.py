"""Freerouting sait faire du fanout ; on le lui laissait eteint.

⚠️ Constat du 2026-08-28. On enfilait les jobs avec `{"session_id": ...}` et
RIEN d autre — donc avec les defauts du serveur. Interroges (`GET /jobs/<id>`),
ils disent :

    fanout.enabled          = false    l echappement natif est ETEINT
    scoring.via_costs       = 50       changer de couche coute 50
    scoring.plane_via_costs = 5

Le fanout est exactement la sequence demandee par l utilisateur : sortir les
broches que le plan n atteint pas par une courte piste et un via. Nous
l implementions APRES coup (`_fanout_pads_isolees`), sur un board deja route,
quand la place manque — alors que le routeur sait le faire PENDANT, quand il
reste de l espace.

⚠️ Le cout de via a 50 explique la repartition mesuree sur la Nucleo :

    F.Cu 243 segments · In1.Cu 49 · B.Cu 42 · In2.Cu 5

Les couches internes sont LIBRES — aucun plan n y est coule — et le routeur ne
s en sert pas, parce qu y aller coute un via. Il prefere entasser sur la face
la plus encombree.

⚠️ Ce fichier garde le CABLAGE, pas un gain chiffre : la mesure comparative des
quatre conditions (temoin, fanout, cout de via abaisse, les deux) etait encore
en cours a l ecriture. Si elle contredit ce choix, c est ce test qu il faudra
changer, avec sa raison.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestReglages:
    def test_le_fanout_est_actif(self):
        assert R._REGLAGES_FREEROUTING["fanout"]["enabled"] is True

    def test_les_reglages_sont_transmis_au_job(self):
        source = (_SERVICE_ROOT / "routers" / "routing.py").read_text(
            encoding="utf-8")
        corps = source[source.index("def _route_with_freerouting_api("):]
        i = corps.index("jobs/enqueue")
        assert "router_settings" in corps[max(0, i - 600):i + 200], (
            "un reglage qui n est pas envoye ne sert a rien")

    def test_on_ne_touche_que_ce_qu_on_a_mesure(self):
        # Les defauts de Freerouting sont le fruit de son propre reglage. On
        # n en change que les clefs dont on peut dire pourquoi.
        assert set(R._REGLAGES_FREEROUTING) <= {"fanout", "scoring"}

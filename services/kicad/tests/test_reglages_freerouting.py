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
    def test_aucun_reglage_de_QUALITE_n_est_impose(self):
        """⚠️ Ce test affirmait l inverse — le fanout devait etre ACTIF.

        La mesure, arrivee apres, ne l a pas soutenu :

            defauts (temoin)      91 %   5 manq   0 err   76 vias
            fanout actif          91 %   5 manq   0 err   84 vias
            via_costs 50->10      ECHEC — expiration en cascade
            fanout + via_costs    86 %   9 manq   0 err   85 vias

        Le fanout n a rien relie de plus et a pose huit vias supplementaires.
        Le cout de via abaisse fait exploser l espace de recherche : le 50 par
        defaut BORNE l exploration, il n est pas arbitraire.

        ⚠️ Depuis le 2026-08-29 la charge n est plus vide : `max_passes` y
        figure. Ce n est PAS un reglage de qualite mais un critere d ARRET —
        Freerouting ne s arrete pas au bout d un temps, il s arrete quand il
        converge, et 84 % de ses passes ne produisent rien (495 jobs mesures).
        L invariant que ce test protege reste donc entier : AUCUN reglage
        touchant la maniere de router n est impose, les defauts ayant battu
        toutes nos variantes. Voir tests/test_plafond_passes_freerouting.py.
        """
        qualite = set(R._REGLAGES_FREEROUTING or {}) - {"max_passes"}
        assert not qualite, f"reglage(s) de qualite non mesure(s) : {qualite}"

    def test_les_reglages_sont_transmis_au_job(self):
        source = (_SERVICE_ROOT / "routers" / "routing.py").read_text(
            encoding="utf-8")
        corps = source[source.index("def _route_with_freerouting_api("):]
        i = corps.index("jobs/enqueue")
        assert "router_settings" in corps[max(0, i - 600):i + 200], (
            "un reglage qui n est pas envoye ne sert a rien")

    def test_le_mecanisme_d_injection_survit(self):
        # Il a permis la mesure ; rien ne dit qu un autre reglage ne la vaudra
        # pas. On retire le reglage, pas le moyen d en essayer un.
        source = (_SERVICE_ROOT / "routers" / "routing.py").read_text(
            encoding="utf-8")
        assert "_REGLAGES_FREEROUTING" in source

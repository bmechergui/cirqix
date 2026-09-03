"""Fanout : sortir les broches que le plan n a pas pu relier.

Sur un boitier fine-pitch, le plan ne peut pas atteindre les pattes (0,5 mm de
pas), et le routeur ne les route pas non plus puisqu il tient GND pour « pris en
charge par le plan ». Le keepout de coulee a fait tomber le compte de 6 a 2,
mais deux broches GND du LQFP-48 resistent :

    Pad 47 [GND] of U2 on F.Cu <-> Zone [GND] on F.Cu, priority 0
    Pad 35 [GND] of U2 on F.Cu <-> Zone [GND] on F.Cu, priority 0

La reponse standard est le FANOUT : une courte piste depuis la patte vers un
via, qui traverse jusqu au plan de l autre face.

⚠️ `kct stitch --escape-distance` fait exactement ce travail, mais refuse d agir
ici — son propre calcul de connectivite repond « No unconnected pads found »,
puisque ces pads tombent geometriquement dans le polygone de la zone. On lui
substitue donc une sortie ciblee, pilotee par ce que le DRC signale REELLEMENT.

La direction de sortie pointe a l OPPOSE du centre du boitier : c est le canal
que le halo d escape du placement a justement reserve.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


RAPPORT_DRC = {
    "unconnected_items": [
        {
            "items": [
                {"description": "Pad 47 [GND] of U2 on F.Cu"},
                {"description": "Zone [GND] on F.Cu, priority 0"},
            ]
        },
        {
            "items": [
                {"description": "Pad 35 [GND] of U2 on F.Cu"},
                {"description": "Zone [GND] on F.Cu, priority 0"},
            ]
        },
        {
            "items": [
                {"description": "Pad 1 [VCC] of R1 on F.Cu"},
                {"description": "Pad 2 [VCC] of C3 on F.Cu"},
            ]
        },
    ]
}


class TestLectureDuRapport:
    def test_extrait_les_broches_orphelines_d_un_plan(self):
        pads = routing_router._pads_isolees_du_plan(RAPPORT_DRC)
        assert sorted(pads) == [("U2", "35"), ("U2", "47")]

    def test_ignore_les_liaisons_entre_deux_pads(self):
        # Deux pads non relies entre eux relevent du ROUTAGE, pas du fanout :
        # y poser un via ne relierait rien du tout.
        pads = routing_router._pads_isolees_du_plan(RAPPORT_DRC)
        assert ("R1", "1") not in pads
        assert ("C3", "2") not in pads

    def test_un_rapport_vide_ne_rend_rien(self):
        assert routing_router._pads_isolees_du_plan({}) == []
        assert routing_router._pads_isolees_du_plan({"unconnected_items": []}) == []

    def test_un_rapport_inattendu_ne_leve_pas(self):
        # Le fanout est une REPARATION : s il ne comprend pas le rapport, il ne
        # fait rien. Il n ajoute jamais une panne a une panne.
        assert routing_router._pads_isolees_du_plan({"unconnected_items": [{}]}) == []
        assert routing_router._pads_isolees_du_plan(
            {"unconnected_items": [{"items": [{"description": "n importe quoi"}]}]}
        ) == []


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_fanout_intervient_APRES_le_routage(self):
        # Avant le routage il ne servirait a rien : le round-trip Specctra
        # supprime toutes les pistes, vias compris. Mesure du 2026-08-21 :
        # 17 vias poses par `kct stitch` avant routage, 4 apres.
        # On regarde le CORPS de l enveloppe, pas le fichier : comparer des
        # positions globales comparerait les DEFINITIONS de fonctions, et le
        # test passerait sans que rien ne soit cable. Erreur deja commise le
        # meme jour sur le test d ordre des niveaux.
        debut = self.SOURCE.index('@router.post("/route/auto"')
        corps = self.SOURCE[debut:]
        pose = corps.index("_fanout_pads_isolees(")
        route = corps.index("res = _route_auto_once(tentative)")
        assert pose > route, "le fanout doit reparer APRES le routage"

    def test_le_runner_expose_l_operation(self):
        runner = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
            encoding="utf-8"
        )
        assert '"escape_pads"' in runner

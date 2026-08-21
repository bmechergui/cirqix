"""La réponse ne disait jamais QUEL routeur avait travaillé.

`RouteAutoResponse` n'avait pas de champ `engine`, et `handlers/routing.ts`
écrivait `engine: 'kicad-tools'` EN DUR, avec une note assortie :

    « Routage kicad-tools 91% — 12 nets, 4 couches. »

Or la cascade a quatre niveaux. Sur un board dense, kicad-tools rend 91 %, sous
le seuil de 95 %, et c'est **Freerouting** qui produit le board livré. L'
orchestrateur et l'utilisateur lisaient pourtant « kicad-tools ».

Ce n'est pas cosmétique : c'est une attribution fausse, et elle envoie chercher
au mauvais endroit. Elle m'a coûté plusieurs heures le 2026-08-20 — j'ai
attribué à Freerouting une perte de netlist qui venait de notre compteur, et à
un serveur mort un 404 qui venait de notre préfixe d'URL.

Mesures du 2026-08-21 sur le board STM32, qui rendent l'attribution décisive :

    Freerouting  ×3 : 0 connexion manquante, 4-5 s,  27-28 violations, 7-8 vias
    kicad-tools  ×2 : 7 connexions manquantes, 568-750 s, 198 violations, 69 vias

Attribuer le premier résultat au second effacerait précisément ce qu'il faut voir.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


class TestChampEngine:
    def test_la_reponse_porte_un_champ_engine(self):
        champs = routing_router.RouteAutoResponse.model_fields
        assert "engine" in champs

    def test_le_defaut_ne_designe_aucun_routeur(self):
        # Une réponse sans board (skipped) ne doit pas s'attribuer un moteur.
        reponse = routing_router.RouteAutoResponse(layers=2)
        assert reponse.engine is None


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_chaque_reponse_livrant_un_board_nomme_son_moteur(self):
        code = "\n".join(
            ligne for ligne in self.SOURCE.splitlines()
            if not ligne.lstrip().startswith("#")
        )
        boards = code.count("kicad_pcb_b64=base64.b64encode(new_pcb)")
        moteurs = code.count("engine=")
        assert moteurs == boards, (
            f"{boards} réponses livrent un board, {moteurs} nomment leur moteur"
        )

    def test_les_quatre_niveaux_sont_distinguables(self):
        # Un nom par niveau : sans quoi « qui a routé ? » reste sans réponse.
        for nom in ('"kicad-tools"', '"freerouting-api"', '"freerouting-cli"'):
            assert nom in self.SOURCE, f"moteur non nommé : {nom}"

"""Le pourcentage final doit refleter ce que le DRC voit sur le board LIVRE.

Banc du 2026-08-26, cinq cartes de 17 a 100 composants passees dans la chaine
complete :

    cas               comp  couches    %   manquantes
    stm32-baseline      17      2    100        1
    esp32-baseline      20      4    100        0
    stm32-30            30      2    100        1
    stm32-60            60      2    100        0
    stm32-100          100      2    100        3

Trois cartes sur cinq annoncees COMPLETES alors qu elles ne le sont pas.

La mesure du moteur n est pas fausse, elle regarde AILLEURS : le board juste
apres le routeur, avant que les plans soient coules et les reparations faites,
et sans les nets confies au plan. Une pastille GND restee orpheline lui est donc
structurellement invisible.

⚠️ L enjeu depasse l affichage. `routed_percent` decide d arreter, de relancer
le placement (`shouldRetryPlacement`) ou d appeler le reasoner
(`shouldRescueRouting`). Un 100 % mensonger arrete la chaine sur une carte
incomplete — et le gate JLCPCB s appuie sur les statuts qui en decoulent.

Le DRC, lui, voit le board livre. C est donc lui qui tranche.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _rapport(paires: list[tuple[str, str]]) -> dict:
    return {"unconnected_items": [
        {"items": [{"description": f"Pad 1 [{a}] of U1 on F.Cu"},
                   {"description": f"Pad 2 [{b}] of U2 on F.Cu"}]}
        for a, b in paires]}


class TestVerdict:
    def test_un_board_sans_manquante_garde_son_pourcentage(self, monkeypatch):
        monkeypatch.setattr(routing_router, "_rapport_drc", lambda _b: _rapport([]))
        assert routing_router._percent_verifie(b"BOARD", 100, routables=4) == 100

    def test_une_manquante_fait_TOMBER_le_pourcentage(self, monkeypatch):
        # Le cas mesure : 100 % annonce sur une carte incomplete.
        monkeypatch.setattr(routing_router, "_rapport_drc",
                            lambda _b: _rapport([("SIG1", "SIG1")]))
        assert routing_router._percent_verifie(b"BOARD", 100, routables=4) == 75

    def test_plusieurs_manquantes_sur_le_MEME_net_comptent_une_fois(self, monkeypatch):
        # Le pourcentage se compte en NETS, pas en paires — sinon il pourrait
        # devenir negatif sur un net tres fragmente.
        monkeypatch.setattr(routing_router, "_rapport_drc",
                            lambda _b: _rapport([("SIG1", "SIG1"), ("SIG1", "SIG1")]))
        assert routing_router._percent_verifie(b"BOARD", 100, routables=4) == 75

    def test_le_pourcentage_ne_REMONTE_jamais(self, monkeypatch):
        # Le DRC corrige a la baisse, jamais a la hausse : si le moteur annonce
        # 50 %, ce n est pas au DRC de le promouvoir.
        monkeypatch.setattr(routing_router, "_rapport_drc", lambda _b: _rapport([]))
        assert routing_router._percent_verifie(b"BOARD", 50, routables=4) == 50

    def test_un_drc_indisponible_ne_change_rien(self, monkeypatch):
        # Sans verdict, on garde celui du moteur : mieux vaut le chiffre du
        # routeur qu un chiffre invente.
        monkeypatch.setattr(routing_router, "_rapport_drc", lambda _b: {})
        assert routing_router._percent_verifie(b"BOARD", 100, routables=4) == 100

    def test_aucun_net_routable_ne_divise_pas_par_zero(self, monkeypatch):
        monkeypatch.setattr(routing_router, "_rapport_drc",
                            lambda _b: _rapport([("GND", "GND")]))
        assert routing_router._percent_verifie(b"BOARD", 100, routables=0) == 100


class TestPlanFragmente:
    """Un plan coupe en ilots est un net INCOMPLET.

    Mesure du 2026-08-26, carte a 100 composants : les 3 « connexions
    manquantes » n etaient pas des pastilles orphelines mais trois paires

        Zone [GND] on F.Cu  <->  Zone [GND] on F.Cu

    — le plan de masse decoupe par les pistes de signal. Ne chercher que des
    pastilles les rendait invisibles, et le pourcentage restait a 100 %.
    """

    def _zones(self, net: str, n: int) -> dict:
        return {"unconnected_items": [
            {"items": [{"description": f"Zone [{net}] on F.Cu, priority 0"},
                       {"description": f"Zone [{net}] on F.Cu, priority 0"}]}
            for _ in range(n)]}

    def test_un_plan_coupe_fait_tomber_le_pourcentage(self, monkeypatch):
        monkeypatch.setattr(routing_router, "_rapport_drc",
                            lambda _b: self._zones("GND", 3))
        assert routing_router._percent_verifie(b"BOARD", 100, routables=8) == 88

    def test_plusieurs_coupures_du_MEME_plan_comptent_une_fois(self, monkeypatch):
        monkeypatch.setattr(routing_router, "_rapport_drc",
                            lambda _b: self._zones("GND", 7))
        assert routing_router._percent_verifie(b"BOARD", 100, routables=8) == 88

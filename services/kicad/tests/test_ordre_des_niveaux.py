"""Freerouting passe en tete de la cascade (decision produit, 2026-08-21).

L'escalade de couches (2 -> 4 -> 6 -> 8 tant que le routage n'est pas complet)
etait **structurellement etouffee** par kicad-tools place devant : mesure du
2026-08-21, le premier palier a consomme **751 s**, la totalite du budget. Il
ne restait rien pour monter, et Freerouting recevait ZERO seconde.

Avec Freerouting en tete, un palier coute 4 a 31 s : les quatre tiennent en
deux minutes, et l'escalade fait enfin ce qu'on attend d'elle.

La qualite va dans le meme sens, mesuree sur le board STM32 (6 tirages, meme
instrument, temoin inclus) :

    Freerouting x3 : 0 connexion manquante, 25 violations (= le temoin), 5-8 vias
    kicad-tools x3 : 7 connexions manquantes, 197-198 violations dont 58 ERREURS
                     de fabricabilite, 69 vias

⚠️ kicad-tools RESTE dans la cascade, en repli. Il n'est pas moins bon en tout :
c'est le seul a savoir ESCALADER les couches lui-meme (`--auto-layers`), et sur
un board que Freerouting echoue a router il reste la derniere chance. On change
l'ordre, on ne supprime rien.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")


def _cascade() -> str:
    """Le CORPS de `_route_auto_once`, pas le fichier entier.

    Comparer des positions dans le fichier comparerait les DEFINITIONS de
    fonctions, pas leur ordre d'appel — le test passerait sans que rien ne
    bouge. Erreur commise en ecrivant ce fichier, corrigee avant de coder.
    """
    debut = SOURCE.index("def _route_auto_once(")
    fin = SOURCE.index('@router.post("/route/auto"', debut)
    return SOURCE[debut:fin]


def _position(marqueur: str) -> int:
    corps = _cascade()
    assert marqueur in corps, f"marqueur introuvable dans la cascade : {marqueur}"
    return corps.index(marqueur)


class TestOrdreDeLaCascade:
    def test_freerouting_api_passe_avant_kicad_tools(self):
        assert _position("_route_with_freerouting_api(") < _position(
            "_route_with_kicad_tools("
        ), "Freerouting doit etre tente en premier — sinon l'escalade est etouffee"

    def test_freerouting_subprocess_passe_aussi_avant(self):
        assert _position("_run_freerouting(paths") < _position(
            "_route_with_kicad_tools("
        )

    def test_kicad_tools_reste_dans_la_cascade(self):
        # On change l'ordre, on ne supprime pas : kicad-tools est le seul a
        # savoir escalader les couches lui-meme, et la derniere chance quand
        # Freerouting echoue.
        assert "_route_with_kicad_tools(" in SOURCE
        assert 'engine="kicad-tools"' in SOURCE

    def test_les_gardes_de_budget_survivent_au_reordonnancement(self):
        for entree in (
            "if api_url is not None and _budget_suffisant(",
            "if paths is not None and _budget_suffisant(",
            "if is_simple and _budget_suffisant(",
        ):
            assert entree in SOURCE, f"garde perdue au reordonnancement : {entree}"

    def test_la_garde_netlist_survit_pour_chaque_moteur(self):
        for source in ('"freerouting-api"', '"freerouting-cli"', '"kicad-tools"'):
            assert f"_guard_netlist_preserved(new_pcb, input_nets, {source})" in SOURCE, (
                f"garde netlist perdue pour {source}"
            )

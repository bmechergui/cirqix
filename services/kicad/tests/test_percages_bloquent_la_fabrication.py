"""Des perçages trop proches BLOQUENT la fabrication — même quand KiCad les
classe en avertissement.

⚠️ Mesuré le 2026-09-23 sur `carte-11-croisements`, board livré :

    mesures.json   drc_clean: true    types_violations: "hole_to_hole:8"

Deux vias GND à 0,340 mm bord à bord, et deux vias dont le perçage RECOUPE
celui d'une broche de connecteur, à -0,050 mm. Aucun fabricant ne perce cela.
Mais KiCad classe `hole_to_hole` en *warning* par défaut, et tous nos juges ne
comptaient que les `error` :

    /drc/auto        drc_clean = aucune violation `error`  ->  DRC_CLEAN
                     et DRC_CLEAN ouvre le gate de commande JLCPCB,
                     comme PCB_LIVRÉ, promu sur le même drc_clean
    routage          _compte_erreurs = severity == "error"
                     -> une réparation qui AJOUTE des perçages recoupés
                        passait la garde « ne peut qu'améliorer »

Le docstring de `_aggrave_le_board` portait la prémisse en toutes lettres :
« une erreur de fabricabilité fait refuser la carte, un avertissement non ».
Pour un perçage, c'est faux — et c'est ce qui a laissé sortir `carte-11`.

## La règle

Une liste NOMMÉE, à UN endroit (`tools/drc.py`), de types qui bloquent la
fabrication quelle que soit leur sévérité, et UN prédicat qui la lit. Les deux
juges passent par lui. Ce dépôt a déjà payé cinq fois la même comparaison
écrite cinq fois (2026-09-07).

⚠️ Ce qui NE change PAS : le SEUIL. KiCad juge `hole_to_hole` à 0,25 mm par
défaut ; nos poseurs de vias visent 0,50 mm. Aligner le juge sur 0,50 serait un
nouveau chiffre qui change le comportement livré — une décision produit, qui
n'est pas prise ici. La promotion de sévérité attrape déjà les perçages qui se
RECOUPENT, et tout ce qui est sous 0,25 mm.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import drc as D  # noqa: E402
from routers import routing as R  # noqa: E402


def _code_seul(fonction) -> str:
    """Le code d'une fonction, SANS docstrings ni commentaires.

    `ast.unparse` ne rend jamais les commentaires ; on retire en plus chaque
    docstring (premier nœud d'un corps, s'il est une chaîne)."""
    import ast
    import textwrap
    arbre = ast.parse(textwrap.dedent(inspect.getsource(fonction)))
    for noeud in ast.walk(arbre):
        corps = getattr(noeud, "body", None)
        if (isinstance(corps, list) and corps and isinstance(corps[0], ast.Expr)
                and isinstance(getattr(corps[0], "value", None), ast.Constant)
                and isinstance(corps[0].value.value, str)):
            noeud.body = corps[1:] or [ast.Pass()]
    return ast.unparse(arbre)


def _rapport(*violations: dict) -> str:
    return json.dumps({"violations": list(violations), "unconnected_items": []})


def _v(type_: str, severity: str) -> dict:
    return {"type": type_, "severity": severity, "description": type_,
            "items": [{"description": "Via [GND]", "pos": {"x": 83.5, "y": 90.02}}]}


class TestLaListeNommee:
    def test_les_percages_sont_bloquants(self):
        assert "hole_to_hole" in D.TYPES_BLOQUANTS_FABRICATION
        assert "holes_co_located" in D.TYPES_BLOQUANTS_FABRICATION

    def test_le_predicat_bloque_un_percage_meme_en_warning(self):
        assert D.est_bloquante({"type": "hole_to_hole", "severity": "warning"}) is True
        assert D.est_bloquante({"type": "holes_co_located", "severity": "warning"}) is True

    def test_une_erreur_reste_bloquante(self):
        assert D.est_bloquante({"type": "clearance", "severity": "error"}) is True

    def test_un_avertissement_cosmetique_ne_bloque_pas(self):
        """La sérigraphie qui chevauche ne fait refuser aucune carte."""
        assert D.est_bloquante({"type": "silk_overlap", "severity": "warning"}) is False
        assert D.est_bloquante({"type": "silk_over_copper", "severity": "warning"}) is False


class TestLeJugeDeLaCommande:
    """`/drc/auto` -> `drc_clean` -> DRC_CLEAN -> gate JLCPCB."""

    def test_parse_drc_report_promeut_le_percage_en_erreur(self):
        out = D.parse_drc_report(_rapport(_v("hole_to_hole", "warning")))
        assert out and all(v["severity"] == "error" for v in out), (
            "un percage recoupe doit sortir en ERREUR : sinon drc_clean est "
            "vrai et le gate JLCPCB s ouvre sur une carte impossible a percer")

    def test_la_serigraphie_reste_un_avertissement(self):
        out = D.parse_drc_report(_rapport(_v("silk_overlap", "warning")))
        assert all(v["severity"] == "warning" for v in out)

    def test_le_verdict_de_la_route_suit_le_predicat(self):
        """`drc_clean` se calcule sur les violations `error` rendues par
        `parse_drc_report` : la promotion suffit à le rendre faux."""
        import routers.drc as RD
        src = inspect.getsource(RD)
        assert "parse_drc_report(" in src
        out = D.parse_drc_report(_rapport(_v("hole_to_hole", "warning")))
        assert [v for v in out if v.get("severity") == "error"], "drc_clean serait vrai"


class TestLeJugeDuRoutage:
    """`_compte_erreurs` alimente `_aggrave_le_board` et `_bilan_drc`."""

    def test_un_percage_recoupe_compte_comme_une_erreur(self):
        rapport = {"violations": [{"type": "hole_to_hole", "severity": "warning"}]}
        assert R._compte_erreurs(rapport) == 1

    def test_la_serigraphie_ne_compte_pas(self):
        rapport = {"violations": [{"type": "silk_overlap", "severity": "warning"}]}
        assert R._compte_erreurs(rapport) == 0

    def test_une_reparation_qui_ajoute_un_percage_recoupe_est_nommee(self):
        """La garde doit DIRE ce qu'elle refuse (leçon du 2026-09-11)."""
        avant = {"violations": []}
        apres = {"violations": [{"type": "hole_to_hole", "severity": "warning"}]}
        assert R._erreurs_ajoutees(avant, apres) == {"hole_to_hole": 1}

    def test_les_deux_juges_lisent_la_MEME_liste(self):
        """⚠️ Une règle vit à UN endroit. Deux listes divergent toujours.

        ⚠️ On lit le CODE SEUL. La première version de cette garde lisait le
        source brut et trouvait `hole_to_hole`… dans le docstring qui explique
        le correctif : elle échouait sur un code correct. Piège déjà inscrit
        dans CLAUDE.md le 2026-09-08, retombé dedans le 2026-09-24.
        """
        code = _code_seul(R._compte_erreurs) + _code_seul(R._erreurs_ajoutees)
        assert "est_bloquante" in code
        assert "hole_to_hole" not in code, (
            "le routage ne doit pas recopier la liste : il lit celle de tools/drc.py")

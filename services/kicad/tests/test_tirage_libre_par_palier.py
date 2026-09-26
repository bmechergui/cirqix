"""Chaque palier d'escalade reçoit au moins UN tirage LIBRE, en plus du tirage
incrémental. Sans cela, une couche de plus peut faire PIRE.

⚠️ Objectif de l'utilisateur, 2026-09-24 : « si tu n'atteins pas 100 % de
routage, tu dois escalader le nombre de couches, et normalement on doit
l'atteindre si on escalade le nombre de couches ». Et : « je veux une solution
générale, tu es en train de bricoler la carte nucleo ».

## Le défaut, mesuré sur `nucleo-f401` (campagne de production du 2026-09-23)

    échelle réelle : [2, 4, 4, 4, 6, 6, 6, 8, 8, 8]
    palier 2 : un seul tirage            ->  96 %
    palier 4 : pistes du 96 % PROTÉGÉES  ->  98 %, 98 %, figé, figé, 96 %
    palier 6 : pistes du 98 % PROTÉGÉES  ->  96 %, figé, 96 %
    arrêt : 7 paliers sans gain

**Six couches ont fait MOINS BIEN que quatre.** L'escalade incrémentale
(D-2026-09-10-b) protège les pistes du meilleur board au changement de palier,
et cette protection restait en place pour TOUS les tirages du palier. Après le
tout premier tirage, plus aucun tirage n'était libre : on ne donnait pas plus
de couches à la carte, on donnait plus de couches au PREMIER tirage pour qu'il
se rapièce. S'il avait enfermé une pastille, rien ne pouvait l'en sortir.

Et sur la même carte, au même placement, un tirage LIBRE a donné **100 % sur
DEUX couches en 98 s** (2026-09-24). Les tirages incrémentaux n'ont jamais
dépassé 98 %.

## La règle

Le PREMIER tirage d'un palier reste incrémental — D-2026-09-10-b, validée par
l'utilisateur le 2026-09-11 (« on garde le routage et on ajoute »), n'est pas
remise en cause : elle est souvent la plus rapide. Les tirages SUIVANTS du même
palier repartent du board placé, sans rien protéger. `_palier_meilleur` garde
déjà le meilleur de tous, jamais le dernier : un tirage libre ne peut donc
rien dégrader, il ne peut qu'offrir une chance que l'incrémental n'avait pas.

Aucun seuil n'est touché, aucun tirage n'est ajouté : c'est la NATURE des
tirages déjà prévus qui change.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


def _code_de(fonction) -> str:
    """Le source SANS commentaires : une garde ne doit jamais s'ancrer sur une
    phrase de sa propre documentation (piège inscrit le 2026-09-08)."""
    return "\n".join(l.split("#")[0] for l in inspect.getsource(fonction).splitlines())


class TestLaDecision:
    def test_le_premier_tirage_d_un_palier_reste_INCREMENTAL(self):
        """D-2026-09-10-b n'est pas remise en cause."""
        assert R._tirage_libre(0) is False

    def test_les_tirages_suivants_du_palier_sont_LIBRES(self):
        assert R._tirage_libre(1) is True
        assert R._tirage_libre(2) is True
        assert R._tirage_libre(5) is True

    def test_desarmable_pour_l_AB(self):
        """Un réglage de banc, relu à chaque appel, comme `escalade_incrementale`."""
        from tools import reglages_banc
        original = reglages_banc.reglage
        try:
            reglages_banc.reglage = (
                lambda nom, defaut=None: False if nom == "tirages_libres_par_palier" else defaut)
            assert R._tirage_libre(1) is False
            assert R._tirage_libre(3) is False
        finally:
            reglages_banc.reglage = original


class TestLeCABLAGE:
    """⚠️ Une règle correcte jamais appelée est indistinguable d'une règle
    absente — c'est ce qui a masqué des semaines durant que le Géomètre ne
    tournait jamais en production."""

    def test_route_auto_consulte_la_regle(self):
        assert "_tirage_libre(" in _code_de(R.route_auto)

    def test_le_rang_repart_a_zero_a_chaque_nouveau_palier(self):
        """Sinon le premier tirage du palier 6 serait compté comme le 4e du
        palier 4, et partirait libre au lieu d'incrémental."""
        code = _code_de(R.route_auto)
        i_entree = code.find("palier_courant, meilleur_du_palier = palier, 0")
        assert i_entree != -1
        fenetre = code[i_entree:i_entree + 200]
        assert "rang_au_palier = 0" in fenetre, (
            "le rang dans le palier doit etre remis a zero a l entree du palier")

    def test_un_tirage_libre_ne_protege_RIEN(self):
        """Le tirage libre doit vider la protection ET les zones libérées."""
        code = _code_de(R.route_auto)
        i = code.find("_tirage_libre(")
        fenetre = code[i:i + 600]
        assert "_PISTES_A_PROTEGER = None" in fenetre
        assert "_ZONES_LIBEREES = []" in fenetre

    def test_la_decision_precede_le_routage(self):
        """Décider après `_expand_stackup` reviendrait à router avec la
        protection du tirage précédent."""
        code = _code_de(R.route_auto)
        i_decision = code.find("_tirage_libre(")
        i_routage = code.find("etendu = _expand_stackup(pcb_bytes, palier)")
        assert i_decision != -1 and i_routage != -1
        assert i_decision < i_routage

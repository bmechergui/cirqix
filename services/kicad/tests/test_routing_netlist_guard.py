"""Garde : `/route/auto` ne renvoie jamais un board vidé de sa netlist.

Régression mesurée le 2026-07-28 (issue #72, run CI 30405002826). Le board entre
au routage avec 30 déclarations de net et en ressort avec **zéro** — pistes
absentes, netlist perdue, fichier réécrit par le repli pcbnew — pendant que le
service rapporte ``routed_percent=100, skipped=False, warning=None``.

Conséquence : les 6 nets du board ressortent non connectés au DRC
(``unconnected_items`` sur VCC, GND, TRIG_THR, DISCH, LED_A, OUT), et comme il
n'y a plus de netlist il n'y a plus de règle à violer — ``violations=0``. Le
board paraît « propre » parce qu'il est vide.

Un board de 31 Ko sans une seule déclaration de net n'est pas un routage réussi.
C'est le même motif de succès fantôme que celui corrigé côté handlers TS
(fail-fast routage/DRC/export), qui avait échappé ici parce qu'il vit côté Python.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _board(nets: int, segments: int = 0) -> bytes:
    """Board minimal portant ``nets`` déclarations et ``segments`` pistes.

    Sans pads : sert aux tests unitaires de COMPTAGE de déclarations. Pour un
    parcours bout-en-bout de ``route_auto``, utiliser ``_board_with_pads`` — un
    board sans pad attribué n'a aucun net routable et est désormais refusé à
    l'entrée (fail closed, 2026-08-12).
    """
    lines = ["(kicad_pcb", '\t(version 20260206)', '\t(generator "test")']
    for i in range(nets):
        lines.append(f'\t(net {i} "NET{i}")')
    for _ in range(segments):
        lines.append('\t(segment (start 1 1) (end 2 2) (width 0.25) (layer "F.Cu") (net 1))')
    lines.append(")")
    return "\n".join(lines).encode("utf-8")


def _board_with_pads(nets: int, segments: int = 0) -> bytes:
    """Board RÉALISTE : chaque net est porté par deux pads, donc routable.

    C'est ce qui distingue un vrai board d'un board vide. ``_board`` ci-dessus
    ne produisait que des déclarations, si bien que ``_count_routable_nets``
    valait 0 — la forme exacte du défaut corrigé le 2026-08-12, où un tel board
    était annoncé « routé à 100 % ».
    """
    lines = ["(kicad_pcb", '\t(version 20260206)', '\t(generator "test")']
    for i in range(nets):
        lines.append(f'\t(net {i} "NET{i}")')
    for i in range(nets):
        lines.append(f'\t(footprint "R_0402" (layer "F.Cu") (at {10 + i} 10)')
        lines.append(f'\t\t(pad "1" smd rect (at -0.5 0) (size 0.6 0.6) (layers "F.Cu") (net {i} "NET{i}"))')
        lines.append(f'\t\t(pad "2" smd rect (at 0.5 0) (size 0.6 0.6) (layers "F.Cu") (net {i} "NET{i}"))')
        lines.append('\t)')
    for _ in range(segments):
        lines.append('\t(segment (start 1 1) (end 2 2) (width 0.25) (layer "F.Cu") (net 1))')
    lines.append(")")
    return "\n".join(lines).encode("utf-8")


class TestNetDeclCount:
    def test_compte_les_declarations_de_net(self):
        assert routing_router._net_decl_count(_board(nets=6)) == 6

    def test_zero_sur_un_board_sans_netlist(self):
        assert routing_router._net_decl_count(_board(nets=0)) == 0

    def test_ignore_les_references_de_net_dans_les_pistes(self):
        # `(net 1)` dans un segment n'est PAS une déclaration : seule la forme
        # `(net N "nom")` en est une. Sans quoi la garde se croirait satisfaite
        # par un board qui n'a que des pistes orphelines.
        board = _board(nets=0, segments=5)
        assert routing_router._net_decl_count(board) == 0


class TestGuardBoardKeepsNetlist:
    def test_laisse_passer_un_board_qui_conserve_ses_nets(self):
        out = _board(nets=6, segments=10)
        # Ne doit pas lever.
        routing_router._guard_netlist_preserved(out, input_nets=6, source="kicad-tools")

    def test_tolere_une_baisse_partielle(self):
        # Le routage peut légitimement fusionner ou renommer des nets ; seule la
        # disparition TOTALE est le symptôme mesuré.
        routing_router._guard_netlist_preserved(_board(nets=3), input_nets=6, source="freerouting")

    def test_refuse_un_board_vide_de_sa_netlist(self):
        with pytest.raises(HTTPException) as exc:
            routing_router._guard_netlist_preserved(
                _board(nets=0, segments=40), input_nets=30, source="freerouting"
            )
        assert exc.value.status_code == 500
        assert "netlist" in str(exc.value.detail).lower()

    def test_n_intervient_pas_si_l_entree_n_avait_deja_pas_de_nets(self):
        # Board d'entrée sans netlist : ce n'est pas au routeur de s'en plaindre,
        # et lever ici masquerait la vraie cause en amont.
        routing_router._guard_netlist_preserved(_board(nets=0), input_nets=0, source="kicad-tools")


class TestRouteAutoEndToEnd:
    def test_route_auto_ne_livre_jamais_un_board_vide_comme_succes(self, monkeypatch):
        """Le cas mesuré : routage annoncé « 100 % » sur un board vidé de ses nets.

        La garde lève, mais `route_auto` rattrape et laisse sa chance au routeur
        suivant — c'est voulu : un routeur défaillant ne doit pas condamner
        l'endpoint. Ce qui compte est le résultat FINAL : aucun board livré, et
        surtout pas un `routed_percent=100` mensonger. Le repli `skipped=True`
        est ensuite traité en fail-fast par `handleRouting` côté TS.
        """
        entree = _board_with_pads(nets=30, segments=0)
        sortie_vide = _board(nets=0, segments=0)

        monkeypatch.setattr(
            routing_router, "_route_with_kicad_tools",
            lambda *a, **k: (sortie_vide, 100),
        )
        # Pas de Freerouting disponible dans le test → on va jusqu'au repli.
        monkeypatch.setattr(routing_router, "_find_freerouting_api", lambda: None)
        # ⚠️ Ces boards sont SYNTHETIQUES : sans piste reelle, un vrai DRC les
        # declare tous incomplets et `_percent_verifie` ramenerait le
        # pourcentage a 3 %. Ce test mesure la GARDE NETLIST, pas le verdict
        # DRC — on neutralise donc ce dernier plutot que de deformer ce que
        # le test cherche a prouver.
        monkeypatch.setattr(routing_router, "_rapport_drc", lambda _b: {})
        monkeypatch.setattr(routing_router, "_find_freerouting", lambda: None)

        req = routing_router.RouteAutoRequest(
            kicad_pcb_b64=base64.b64encode(entree).decode("ascii"), layers=2
        )
        res = routing_router.route_auto(req)

        assert res.routed_percent != 100, "un board vide ne peut pas être annoncé routé à 100%"
        assert res.skipped is True
        assert res.kicad_pcb_b64 is None, "aucun board ne doit être livré"

    def test_route_auto_reussit_quand_la_netlist_survit(self, monkeypatch):
        entree = _board_with_pads(nets=30)
        # ⚠️ Board SYNTHETIQUE : sans piste reelle, un vrai DRC le declare
        # incomplet et `_percent_verifie` ramenerait le pourcentage a 3 %.
        # Ce test mesure la garde NETLIST, pas le verdict DRC.
        monkeypatch.setattr(routing_router, "_rapport_drc", lambda _b: {})
        sortie = _board_with_pads(nets=30, segments=12)

        monkeypatch.setattr(
            routing_router, "_route_with_kicad_tools",
            lambda *a, **k: (sortie, 100),
        )

        req = routing_router.RouteAutoRequest(
            kicad_pcb_b64=base64.b64encode(entree).decode("ascii"), layers=2
        )
        res = routing_router.route_auto(req)
        assert res.routed_percent == 100
        assert res.skipped is False


class TestFreeroutingEchecNeJettePasLeTravailDejaFait:
    """Un echec de Freerouting ne doit pas effacer le routage partiel de kicad-tools.

    Mesure du 2026-08-20, board STM32 reel : `kct route` rend un routage sous
    `_MIN_ROUTED_PCT`, la chaine bascule sur Freerouting, dont le round-trip
    Specctra renvoie un board **sans netlist** (99 nets en entree, 0 en sortie).
    La garde refuse ce board -- a raison -- mais le Niveau 3 levait alors un 500
    qui court-circuitait le Niveau 4, lequel aurait rendu le `kt_partial` deja
    obtenu : un routage partiel REEL, qui passe sa propre garde.

    Un resultat valide etait donc jete parce qu'un AUTRE routeur avait echoue.
    Le commentaire du Niveau 4 annonce pourtant cette reutilisation ; elle etait
    inatteignable des que Freerouting etait present et defaillant.

    Symetrie attendue : Freerouting ABSENT et Freerouting DEFAILLANT doivent
    conduire au meme repli.
    """

    @staticmethod
    def _freerouting_qui_perd_la_netlist(monkeypatch, sortie_vide: bytes) -> None:
        monkeypatch.setattr(routing_router, "_find_freerouting_api", lambda: None)
        # ⚠️ Ces boards sont SYNTHETIQUES : sans piste reelle, un vrai DRC les
        # declare tous incomplets et `_percent_verifie` ramenerait le
        # pourcentage a 3 %. Ce test mesure la GARDE NETLIST, pas le verdict
        # DRC — on neutralise donc ce dernier plutot que de deformer ce que
        # le test cherche a prouver.
        monkeypatch.setattr(routing_router, "_rapport_drc", lambda _b: {})
        monkeypatch.setattr(routing_router, "_find_freerouting", lambda: ("java", "fr.jar"))
        monkeypatch.setattr(routing_router, "_export_specctra", lambda *a, **k: None)
        monkeypatch.setattr(routing_router, "_run_freerouting", lambda *a, **k: None)
        monkeypatch.setattr(routing_router, "_specctra_roundtrip", lambda *a, **k: sortie_vide)

    def test_le_partiel_de_kicad_tools_est_livre_quand_freerouting_perd_la_netlist(
        self, monkeypatch
    ):
        entree = _board_with_pads(nets=30)
        partiel = _board_with_pads(nets=30, segments=6)

        monkeypatch.setattr(
            routing_router, "_route_with_kicad_tools",
            lambda *a, **k: (partiel, 60),  # < _MIN_ROUTED_PCT -> garde en reserve
        )
        self._freerouting_qui_perd_la_netlist(monkeypatch, _board(nets=0, segments=40))

        req = routing_router.RouteAutoRequest(
            kicad_pcb_b64=base64.b64encode(entree).decode("ascii"), layers=2
        )
        res = routing_router.route_auto(req)

        assert res.kicad_pcb_b64 is not None, "le routage partiel reel ne doit pas etre jete"
        assert res.routed_percent == 60
        assert res.skipped is False

    def test_aucun_routeur_utilisable_reste_un_echec_franc(self, monkeypatch):
        """Sans partiel a sauver, l'echec doit rester un echec -- jamais un faux succes."""
        entree = _board_with_pads(nets=30)

        def _kicad_tools_indisponible(*_a, **_k):
            raise RuntimeError("kct absent")

        monkeypatch.setattr(
            routing_router, "_route_with_kicad_tools", _kicad_tools_indisponible
        )
        self._freerouting_qui_perd_la_netlist(monkeypatch, _board(nets=0, segments=40))

        req = routing_router.RouteAutoRequest(
            kicad_pcb_b64=base64.b64encode(entree).decode("ascii"), layers=2
        )
        res = routing_router.route_auto(req)

        assert res.skipped is True
        assert res.kicad_pcb_b64 is None
        assert res.routed_percent == 0


class TestLeMessageDitLaquelleDesDeuxCausesSEstProduite:
    """« indisponible ou defaillant » ne dit pas laquelle -- et les deux se soignent
    differemment.

    ABSENT se lit dans le deploiement : le binaire ou la JVM manquent, c'est un
    probleme d'image. DEFAILLANT se lit dans les donnees : Freerouting a tourne
    et a rendu quelque chose d'inutilisable -- lors de la mesure du 2026-08-20,
    un board sans netlist. Confondre les deux envoie chercher au mauvais endroit.
    """

    @staticmethod
    def _kicad_tools_rend_un_partiel(monkeypatch, partiel: bytes) -> None:
        monkeypatch.setattr(
            routing_router, "_route_with_kicad_tools", lambda *a, **k: (partiel, 60)
        )
        monkeypatch.setattr(routing_router, "_find_freerouting_api", lambda: None)
        # ⚠️ Ces boards sont SYNTHETIQUES : sans piste reelle, un vrai DRC les
        # declare tous incomplets et `_percent_verifie` ramenerait le
        # pourcentage a 3 %. Ce test mesure la GARDE NETLIST, pas le verdict
        # DRC — on neutralise donc ce dernier plutot que de deformer ce que
        # le test cherche a prouver.
        monkeypatch.setattr(routing_router, "_rapport_drc", lambda _b: {})

    def _route(self, entree: bytes):
        req = routing_router.RouteAutoRequest(
            kicad_pcb_b64=base64.b64encode(entree).decode("ascii"), layers=2
        )
        return routing_router.route_auto(req)

    def test_freerouting_absent_le_dit(self, monkeypatch):
        entree = _board_with_pads(nets=30)
        self._kicad_tools_rend_un_partiel(monkeypatch, _board_with_pads(nets=30, segments=6))
        monkeypatch.setattr(routing_router, "_find_freerouting", lambda: None)

        warning = self._route(entree).warning or ""
        assert "absent" in warning.lower()
        assert "défaillant" not in warning.lower()

    def test_freerouting_defaillant_le_dit(self, monkeypatch):
        entree = _board_with_pads(nets=30)
        self._kicad_tools_rend_un_partiel(monkeypatch, _board_with_pads(nets=30, segments=6))
        monkeypatch.setattr(routing_router, "_find_freerouting", lambda: ("java", "fr.jar"))
        monkeypatch.setattr(routing_router, "_export_specctra", lambda *a, **k: None)
        monkeypatch.setattr(routing_router, "_run_freerouting", lambda *a, **k: None)
        monkeypatch.setattr(
            routing_router, "_specctra_roundtrip", lambda *a, **k: _board(nets=0, segments=40)
        )

        warning = self._route(entree).warning or ""
        assert "défaillant" in warning.lower()
        assert "absent" not in warning.lower()

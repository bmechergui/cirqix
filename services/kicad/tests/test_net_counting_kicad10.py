"""Le compteur de nets était aveugle à l'écriture de KiCad 10.

Deux écritures coexistent pour la même information :

    (net 3 "TRIG_THR")   ← kicad-tools, et KiCad <= 9
    (net "TRIG_THR")     ← pcbnew de KiCad 10 (`generator_version "10.0"`)

`_NET_DECL_RE` n'acceptait QUE la première. Tout board réécrit par pcbnew 10 —
c'est-à-dire tout board sorti du round-trip Specctra, donc de Freerouting —
comptait **zéro net**, et `_guard_netlist_preserved` le refusait.

Mesuré le 2026-08-20 sur `examples/led-blinker-full-pipeline/output/5_placed`
routé par l'API Freerouting :

    entrée : 30 occurrences `(net <num> "nom")`, 0 nommée
    sortie : 78 occurrences `(net "nom")`,       0 numérotée
    kicad-cli pcb drc  ->  rc=0, « Found 0 unconnected items »

Le board était donc **valide, routé et entièrement connecté**. Le message
« 99 nets en entrée, 0 en sortie » n'était pas une perte de netlist : c'était un
FAUX POSITIF du compteur, et il bloquait Freerouting en entier.

⚠️ La garde elle-même reste juste et nécessaire (issue #72 : un board réellement
vidé était annoncé « routé à 100 % »). C'est sa MESURE qui était fausse. On
corrige la mesure, on ne retire pas la garde.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _board_numerote(nets: int, pads_par_net: int = 2) -> bytes:
    """Écriture kicad-tools / KiCad <= 9 : déclaration en tête + pads numérotés."""
    lignes = ["(kicad_pcb", '\t(version 20260206)', '\t(generator "test")']
    for i in range(nets):
        lignes.append(f'\t(net {i} "NET{i}")')
    for i in range(nets):
        for _ in range(pads_par_net):
            lignes.append(f'\t\t(pad "1" smd rect (net {i} "NET{i}"))')
    lignes.append(")")
    return "\n".join(lignes).encode("utf-8")


def _board_nomme(nets: int, pads_par_net: int = 2) -> bytes:
    """Écriture pcbnew KiCad 10 : pas de table numérotée, nets nommés sur les pads."""
    lignes = ["(kicad_pcb", '\t(version 20260206)', '\t(generator "pcbnew")',
              '\t(generator_version "10.0")']
    for i in range(nets):
        for _ in range(pads_par_net):
            lignes.append(f'\t\t(pad "1" smd rect (net "NET{i}"))')
    lignes.append(")")
    return "\n".join(lignes).encode("utf-8")


class TestFormeNumerotee:
    """Régression : l'ancien format doit continuer d'être compté à l'identique."""

    def test_les_declarations_sont_comptees(self):
        # 5 déclarations + 5 x 2 pads = 15 occurrences porteuses d'un nom.
        assert routing_router._net_decl_count(_board_numerote(5)) == 15

    def test_les_nets_routables_exigent_deux_pads(self):
        assert routing_router._count_routable_nets(_board_numerote(5)) == 5
        # Un seul pad = rien à router (broche non connectée).
        assert routing_router._count_routable_nets(_board_numerote(5, pads_par_net=1)) == 0


class TestFormeNommeeKicad10:
    def test_les_nets_nommes_sont_vus(self):
        assert routing_router._net_decl_count(_board_nomme(5)) == 10

    def test_les_nets_routables_sont_comptes_sans_declaration(self):
        # Sans table en tête, deux pads suffisent : le seuil n'est plus le même.
        assert routing_router._count_routable_nets(_board_nomme(5)) == 5
        assert routing_router._count_routable_nets(_board_nomme(5, pads_par_net=1)) == 0

    def test_la_garde_accepte_un_board_ecrit_par_kicad_10(self):
        # LE faux positif : ce board est valide et routé, il ne doit plus être
        # refusé sous prétexte qu'il ne porte pas de numéros de net.
        routing_router._guard_netlist_preserved(
            _board_nomme(30), input_nets=30, source="freerouting-api"
        )


class TestFailClosedPreserve:
    """Corriger la mesure ne doit pas désarmer la garde."""

    def test_un_board_reellement_vide_est_toujours_refuse(self):
        vide = b'(kicad_pcb\n\t(version 20260206)\n\t(generator "test")\n)'
        with pytest.raises(HTTPException) as exc:
            routing_router._guard_netlist_preserved(vide, input_nets=30, source="test")
        assert exc.value.status_code == 500
        assert "netlist" in str(exc.value.detail).lower()

    def test_un_board_sans_net_ne_compte_aucun_net_routable(self):
        vide = b'(kicad_pcb\n\t(version 20260206)\n)'
        assert routing_router._count_routable_nets(vide) == 0
        assert routing_router._net_decl_count(vide) == 0

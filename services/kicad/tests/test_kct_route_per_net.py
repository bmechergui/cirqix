"""Routage d'un net isolé — `--nets` de kicad-tools, exposé côté Cirqix.

Le lab RL (PR #99) consomme `route_kct_net` pour router un net à la fois et
mesurer la progression net par net. La fonction n'existait dans AUCUN commit du
dépôt : la PR livrait des tests et un module appelant une API jamais écrite.

`kct route --nets NET[,NET…]` existe bien en amont (kicad-tools, issue #4322) :
route exclusivement les nets listés, tous les autres devenant des obstacles.
C'est l'inverse de `--skip-nets`, et c'est exactement ce qu'il faut pour du RL
par net.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.kct_route import _build_route_cmd, route_kct_net


class TestBuildRouteCmdOnlyNets:
    def test_traduit_only_nets_en_option_nets(self) -> None:
        cmd = _build_route_cmd(
            Path("in.kicad_pcb"),
            Path("out.kicad_pcb"),
            60,
            only_nets=["SIG", "GND"],
        )

        assert "--nets" in cmd
        assert cmd[cmd.index("--nets") + 1] == "SIG,GND"

    def test_un_seul_net_ne_produit_pas_de_virgule(self) -> None:
        cmd = _build_route_cmd(Path("i"), Path("o"), 60, only_nets=["SIG"])

        assert cmd[cmd.index("--nets") + 1] == "SIG"

    def test_absent_par_defaut(self) -> None:
        """Le routage complet ne doit surtout pas se restreindre à un net."""
        assert "--nets" not in _build_route_cmd(Path("i"), Path("o"), 60)

    def test_active_preserve_existing(self) -> None:
        """Indissociable du routage par net : sans lui, router le net B
        repartirait d'un board vierge et effacerait le cuivre du net A."""
        cmd = _build_route_cmd(Path("i"), Path("o"), 60, only_nets=["SIG"])

        assert "--preserve-existing" in cmd

    def test_preserve_existing_absent_en_routage_complet(self) -> None:
        """Mesuré le 2026-08-06 : sur l'escalade incrémentale 2→4→6 couches,
        `--preserve-existing` perd la moitié du cuivre reçu pour un résultat
        final identique. Il reste donc cantonné au mode par net."""
        assert "--preserve-existing" not in _build_route_cmd(Path("i"), Path("o"), 60)

    def test_liste_vide_traitee_comme_absente(self) -> None:
        """`--nets` avec une valeur vide serait une erreur côté kicad-tools."""
        assert "--nets" not in _build_route_cmd(Path("i"), Path("o"), 60, only_nets=[])

    def test_espaces_superflus_supprimes(self) -> None:
        # kicad-tools trime déjà, mais un nom vide passerait et serait « unknown
        # net » — erreur à l'exécution plutôt qu'ici.
        cmd = _build_route_cmd(Path("i"), Path("o"), 60, only_nets=[" SIG ", "GND"])

        assert cmd[cmd.index("--nets") + 1] == "SIG,GND"

    def test_coexiste_avec_le_reste_de_la_ligne(self) -> None:
        cmd = _build_route_cmd(Path("i"), Path("o"), 60, only_nets=["SIG"])

        assert "--strategy" in cmd and cmd[cmd.index("--strategy") + 1] == "negotiated"
        assert "--auto-layers" in cmd


class TestRouteKctNet:
    def test_refuse_un_nom_de_net_vide(self) -> None:
        with pytest.raises(ValueError, match="net"):
            route_kct_net(b"(kicad_pcb)", "")

    def test_transmet_le_net_au_routage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Le net demandé doit arriver jusqu'à `_route_once`, seul et intact."""
        vus: dict[str, object] = {}

        def faux_route_once(pcb_bytes, timeout_s, vcc_as_traces, only_nets=None):
            vus["only_nets"] = only_nets
            vus["vcc_as_traces"] = vcc_as_traces
            return b"(routed)", 100, ""

        import tools.kct_route as mod

        monkeypatch.setattr(mod, "_route_once", faux_route_once)

        out, pct, analysis = route_kct_net(b"(kicad_pcb)", "SIG", timeout_s=42)

        assert vus["only_nets"] == ["SIG"]
        assert out == b"(routed)"
        assert pct == 100
        assert analysis == ""

    def test_ne_declenche_pas_le_repli_plans_power(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`route_kct` re-route en plans quand seuls des rails power manquent.

        Hors sujet pour un net isolé : le RL demande CE net, pas le meilleur
        board global. Un second passage fausserait la mesure de progression.
        """
        appels: list[object] = []

        def faux_route_once(pcb_bytes, timeout_s, vcc_as_traces, only_nets=None):
            appels.append(only_nets)
            return b"(partial)", 0, "net +3V3 partiellement routé"

        import tools.kct_route as mod

        monkeypatch.setattr(mod, "_route_once", faux_route_once)

        _, pct, _ = route_kct_net(b"(kicad_pcb)", "+3V3")

        assert len(appels) == 1
        assert pct == 0

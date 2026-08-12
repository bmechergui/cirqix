"""La simulation ne doit JAMAIS fabriquer de mesures (audit du 2026-08-12).

Le handler TypeScript a ete rendu fail-closed la veille (PR #130), mais le
service Python EN DESSOUS renvoyait `status: "ok"` dans TOUS les cas :

  1. kicad-cli absent      -> netlist STUB, un circuit RC sans aucun rapport
                              avec le schema de l'utilisateur ;
  2. ngspice absent        -> `_demo_vectors` ;
  3. ngspice en echec      -> `_demo_vectors` ;
  4. sortie non parsable   -> `_demo_vectors`.

Le client TS n'echoue que si `status != 'ok'` : un service qui repond 200 avec
des donnees inventees passait donc integralement, et le handler « fail-closed »
les presentait comme une simulation reelle.

Le cas 1 est le plus grave : avec ngspice fonctionnel, il simule CORRECTEMENT un
AUTRE circuit. La sortie est authentique, les chiffres sont plausibles, et ils
ne decrivent pas le produit du client. Une decision de conception prise
la-dessus est prise sur une mesure inventee.

Pourquoi personne ne l'avait vu : AUCUN test ne touchait `tools/simulation.py`.
La campagne fail-closed avait couvert l'export, le DRC et l'ERC cote Python
(test_export_fail_closed.py, test_fail_closed_drc_erc.py), jamais la simulation.
Et le test TypeScript mockait entierement `runSimulation` — la fabrication
vivait sous le mock.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from tools import simulation

SCH = '(kicad_sch (symbol (lib_id "Device:R") (property "Value" "1k")))'


@pytest.fixture(autouse=True)
def _no_demo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le mode demo doit etre un choix EXPLICITE, jamais l'etat par defaut."""
    monkeypatch.delenv("CIRQIX_SIMULATION_DEMO", raising=False)


def _boom(*_a, **_k):
    raise FileNotFoundError("ngspice")


def test_kicad_cli_absent_ne_substitue_pas_un_autre_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LE cas le plus grave : sans kicad-cli, le service simulait un circuit RC
    de demonstration a la place du schema recu — et renvoyait `ok`."""
    monkeypatch.setattr(subprocess, "run", _boom)

    out = simulation.run_simulation_from_content(SCH, "transient")

    assert out["status"] == "error"
    assert not out.get("vectors")


def test_ngspice_absent_echoue(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_run(cmd, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:  # kicad-cli reussit
            with open(cmd[cmd.index("--output") + 1], "w", encoding="utf-8") as f:
                f.write("* netlist\nR1 A B 1k\n.end\n")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise FileNotFoundError("ngspice")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out = simulation.run_simulation_from_content(SCH, "transient")

    assert out["status"] == "error"
    assert not out.get("vectors")


def test_le_message_distingue_le_service_du_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """« Notre service est indisponible » et « votre circuit ne se simule pas »
    appellent des actions opposees."""
    monkeypatch.setattr(subprocess, "run", _boom)

    out = simulation.run_simulation_from_content(SCH, "transient")

    assert "reason" in out and out["reason"]


def test_mode_demo_uniquement_sur_demande_explicite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le mode demo garde son utilite en local — comme choix affiche."""
    monkeypatch.setenv("CIRQIX_SIMULATION_DEMO", "1")
    monkeypatch.setattr(subprocess, "run", _boom)

    out = simulation.run_simulation_from_content(SCH, "transient")

    assert out["status"] == "ok"
    assert out.get("engine") == "demo"
    assert out["vectors"]


def test_une_valeur_vide_n_arme_pas_le_mode_demo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIRQIX_SIMULATION_DEMO", "")
    monkeypatch.setattr(subprocess, "run", _boom)

    assert simulation.run_simulation_from_content(SCH, "transient")["status"] == "error"


def test_sortie_non_parsable_echoue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une sortie ngspice sans tableau ne prouve aucune mesure : le parseur
    renvoyait les vecteurs de demonstration."""
    calls = {"n": 0}

    def fake_run(cmd, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            with open(cmd[cmd.index("--output") + 1], "w", encoding="utf-8") as f:
                f.write("* netlist\nR1 A B 1k\n.end\n")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "aucun tableau ici", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out = simulation.run_simulation_from_content(SCH, "transient")

    assert out["status"] == "error"


def test_un_succes_reel_reste_un_succes(monkeypatch: pytest.MonkeyPatch) -> None:
    """La protection ne doit pas rendre le service inutilisable."""
    calls = {"n": 0}
    table = "Index   time    v(out)\n0   0.000e+00   0.000e+00\n1   1.000e-06   1.234e+00\n"

    def fake_run(cmd, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            with open(cmd[cmd.index("--output") + 1], "w", encoding="utf-8") as f:
                f.write("* netlist\nR1 A B 1k\n.end\n")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, table, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out = simulation.run_simulation_from_content(SCH, "transient")

    assert out["status"] == "ok"
    assert out["vectors"]
    assert out.get("engine") != "demo"

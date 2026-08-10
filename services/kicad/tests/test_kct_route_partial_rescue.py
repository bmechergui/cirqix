"""Un routage partiel doit atteindre le reasoner, pas être jeté.

Défaut mesuré le 2026-07-31, Docker backend C++, sur un placement pourtant sain
(0 conflit, 0 composant hors carte) de `examples/stm32-validation` :

    Result: Best result on 4 layers (44% completion)
    Nets routed:  4/9
    Unrouted:     3/9 -- no segments at all
    Result: No tier in jlcpcb -> jlcpcb-tier1 achieved routing success.

``kct route`` sort alors en ``rc=1`` **sans écrire aucun fichier** : quand
aucun tier n'atteint ``--min-completion 1.0``, le meilleur board est perdu.
``route_kct`` levait donc une ``RuntimeError``.

Conséquence : le reasoner (agent ⑥b), dont tout l'objet est de reprendre un
routage incomplet, ne reçoit jamais le triplet ``(board, pourcentage, analyse)``
qu'il attend — ``rescue_with_placement_feedback`` n'est jamais appelé. C'est du
code mort en production exactement dans le cas pour lequel il a été écrit.

La récupération est **conditionnelle et honnête** : on ne retente que si le
routeur annonce explicitement un résultat partiel, et le pourcentage rendu est
celui de la passe d'origine — jamais un 100 par défaut.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kicad-tools" / "src"))

import pytest  # noqa: E402

from tools import kct_route  # noqa: E402

_STDOUT_PARTIEL = (
    "Result: Best result on 4 layers (44% completion)\n"
    "  Nets routed:     4/9\n"
    "  Unrouted:        3/9 -- no segments at all\n"
    "PARTIAL: Best result 44% on 4 layers\n"
    "Unrouted nets:\n"
    "  NRST: Path blocked by component or trace\n"
)

_BOARD = b"(kicad_pcb (segment) (zone))"


def test_reconnait_un_resultat_partiel():
    assert kct_route._has_partial_result(_STDOUT_PARTIEL)
    assert kct_route._has_partial_result("PARTIAL: Best result 12% on 2 layers")


def test_ne_reconnait_rien_dans_un_stdout_muet():
    """Sans annonce explicite, aucune récupération — on lève plutôt que deviner."""
    assert not kct_route._has_partial_result("")
    assert not kct_route._has_partial_result("Segmentation fault")
    assert not kct_route._has_partial_result(None)


def test_la_passe_de_secours_abaisse_le_seuil():
    cmd = kct_route._build_route_cmd(Path("in.kicad_pcb"), Path("out.kicad_pcb"),
                                     300, min_completion=kct_route._MIN_COMPLETION_RESCUE)

    assert cmd[cmd.index("--min-completion") + 1] == kct_route._MIN_COMPLETION_RESCUE
    assert float(kct_route._MIN_COMPLETION_RESCUE) < float(kct_route._MIN_COMPLETION)


def test_le_seuil_normal_reste_la_cible_par_defaut():
    """La passe de secours ne doit pas contaminer le routage nominal."""
    cmd = kct_route._build_route_cmd(Path("in.kicad_pcb"), Path("out.kicad_pcb"), 300)

    assert cmd[cmd.index("--min-completion") + 1] == kct_route._MIN_COMPLETION


def test_board_partiel_recupere_avec_le_pourcentage_REEL(monkeypatch, tmp_path):
    """Le cas mesuré : 44 % récupérés au lieu d'une RuntimeError."""
    appels: list[str | None] = []

    def faux_run(src, dst, timeout_s, fine_pitch=False, min_completion=None, **_kwargs):
        appels.append(min_completion)
        if min_completion is not None:  # passe de secours : écrit enfin
            Path(dst).write_bytes(_BOARD)
        return SimpleNamespace(returncode=1, stdout=_STDOUT_PARTIEL, stderr="")

    monkeypatch.setattr(kct_route, "_run_kct_route", faux_run)

    board, pct, analyse = kct_route.route_kct(_BOARD, timeout_s=10)

    assert pct == 44, "le pourcentage doit être le RÉEL, jamais un 100 par défaut"
    assert board
    assert "NRST" in analyse
    assert appels == [None, kct_route._MIN_COMPLETION_RESCUE]


def test_sans_resultat_partiel_on_leve_toujours(monkeypatch):
    """Un échec muet reste un échec : ne jamais rendre un board inconnu."""
    def faux_run(src, dst, timeout_s, fine_pitch=False, min_completion=None, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="boom", stderr="crash")

    monkeypatch.setattr(kct_route, "_run_kct_route", faux_run)

    with pytest.raises(RuntimeError, match="produced no output"):
        kct_route.route_kct(_BOARD, timeout_s=10)

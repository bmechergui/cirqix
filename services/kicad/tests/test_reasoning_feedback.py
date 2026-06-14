"""Tests — boucle placement-feedback du reasoner (TDD).

Principe validé sur examples/stm32-validation : le LLM ne route JAMAIS lui-même.
Il déplace des composants (place_component), puis le VRAI routeur négocié
(route_fn = kct route) reroute. Max N itérations, garde anti-régression
(on rend toujours le meilleur board rencontré).

Leçon debug 2026-06-10 : kct route ne sait pas ripper le routage existant
(anciennes pistes/vias/zones = obstacles durs → 33% avec, 89% sans sur le même
placement). La boucle doit donc DÉ-ROUTER complètement le board avant chaque
passe route_fn.

Aucun réseau ni Docker : route_fn et decide sont des stubs déterministes ;
le board est la fixture committée examples/stm32-validation/expected/.
"""
from __future__ import annotations

import re

import pytest

from tools.reasoning import _strip_routing, rescue_with_placement_feedback


def _route_fn_improving(script: list[int]):
    """route_fn factice : renvoie les pourcentages scriptés, dans l'ordre.

    Signature contractuelle : (pcb_bytes) -> (routed_bytes, pct, failure_analysis).
    """
    calls: list[bytes] = []

    def route_fn(pcb_bytes: bytes):
        calls.append(pcb_bytes)
        pct = script[min(len(calls), len(script)) - 1]
        analysis = (
            "" if pct >= 100 else
            "Unrouted nets:\n  SWO: Path blocked by component\n"
            "Suggestion: Move D1 north to create routing channel"
        )
        return pcb_bytes, pct, analysis

    route_fn.calls = calls  # type: ignore[attr-defined]
    return route_fn


def _decide_move_d1(prompt: str) -> dict:
    """Décideur factice : déplace toujours D1 (commande autorisée)."""
    return {"type": "place_component", "ref": "D1", "at": [145.4, 112.4]}


# ---------------------------------------------------------------------------
# Boucle nominale
# ---------------------------------------------------------------------------

def test_stops_when_routing_complete(stm32_board_bytes):
    """40% → déplacement → 100% : la boucle s'arrête, pct final = 100."""
    route_fn = _route_fn_improving([40, 100])

    out, pct, steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn,
        max_iterations=3, decide=_decide_move_d1,
    )

    assert pct == 100
    assert len(route_fn.calls) == 2          # pas de 3e routage inutile
    assert isinstance(out, bytes) and len(out) > 0
    assert any("100" in s for s in steps)


def test_full_route_first_pass_no_llm_call(stm32_board_bytes):
    """Si le premier routage atteint 100%, le LLM n'est jamais consulté."""
    route_fn = _route_fn_improving([100])
    llm_calls = []

    def decide(prompt):
        llm_calls.append(prompt)
        return _decide_move_d1(prompt)

    _out, pct, _steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn, max_iterations=3, decide=decide,
    )

    assert pct == 100
    assert llm_calls == []


def test_max_iterations_bound(stm32_board_bytes):
    """route_fn n'améliore jamais : la boucle s'arrête à max_iterations routages."""
    route_fn = _route_fn_improving([40, 40, 40, 40, 40])

    _out, pct, _steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn,
        max_iterations=3, decide=_decide_move_d1,
    )

    assert pct == 40
    assert len(route_fn.calls) == 3


# ---------------------------------------------------------------------------
# Garde anti-régression
# ---------------------------------------------------------------------------

def test_returns_best_board_not_last(stm32_board_bytes):
    """60% puis 35% : on rend le board à 60% (jamais pire que le meilleur vu)."""
    best_marker = b"BEST"

    calls = []

    def route_fn(pcb_bytes: bytes):
        calls.append(1)
        if len(calls) == 1:
            return best_marker, 60, "Unrouted nets:\n  NRST"
        return b"WORSE", 35, "Unrouted nets:\n  NRST\n  SWO"

    out, pct, _steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn,
        max_iterations=2, decide=_decide_move_d1,
    )

    assert pct == 60
    assert out == best_marker


# ---------------------------------------------------------------------------
# Vocabulaire restreint : le LLM ne route JAMAIS
# ---------------------------------------------------------------------------

def test_route_net_command_is_rejected(stm32_board_bytes):
    """Une commande route_net du LLM est refusée (jamais exécutée) et loggée."""
    route_fn = _route_fn_improving([40, 40])

    def decide(prompt):
        return {"type": "route_net", "net": "SWO"}

    _out, _pct, steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn,
        max_iterations=2, decide=decide,
    )

    assert any("route_net" in s and ("interdit" in s or "refus" in s) for s in steps)


def test_failure_analysis_is_in_llm_prompt(stm32_board_bytes):
    """Le prompt envoyé au LLM contient l'analyse d'échec du routeur."""
    route_fn = _route_fn_improving([40, 100])
    prompts: list[str] = []

    def decide(prompt):
        prompts.append(prompt)
        return _decide_move_d1(prompt)

    rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn, max_iterations=2, decide=decide,
    )

    assert prompts, "le LLM devait être consulté"
    assert "Move D1 north" in prompts[0]


# ---------------------------------------------------------------------------
# Robustesse decide
# ---------------------------------------------------------------------------

def test_decide_exception_returns_best_so_far(stm32_board_bytes):
    """decide crashe : arrêt propre, on rend le meilleur board déjà routé."""
    route_fn = _route_fn_improving([40])

    def decide(prompt):
        raise RuntimeError("API down")

    out, pct, steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn, max_iterations=3, decide=decide,
    )

    assert pct == 40
    assert isinstance(out, bytes) and len(out) > 0
    assert len(route_fn.calls) == 1          # pas de re-routage sans déplacement


def test_decide_none_stops_iteration(stm32_board_bytes):
    """decide renvoie None (pas de commande exploitable) : arrêt propre."""
    route_fn = _route_fn_improving([40, 40, 40])

    _out, pct, _steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn, max_iterations=3, decide=lambda p: None,
    )

    assert pct == 40
    assert len(route_fn.calls) == 1


# ---------------------------------------------------------------------------
# Dé-routage complet avant chaque passe du routeur
# ---------------------------------------------------------------------------

def _assert_no_routing(pcb_bytes: bytes) -> None:
    """Le board ne contient plus aucun bloc top-level segment/via/zone."""
    text = pcb_bytes.decode("utf-8", errors="replace")
    for kind in ("segment", "via", "zone"):
        assert re.search(rf'\n\s*\({kind}[\s\n]', text) is None, f"bloc ({kind} restant"


def test_strip_routing_removes_all_copper(stm32_board_bytes):
    """_strip_routing retire segments + vias + zones et préserve les footprints."""
    stripped, counts = _strip_routing(stm32_board_bytes)

    _assert_no_routing(stripped)
    # La fixture est un board routé : il y avait bien du cuivre à retirer
    assert counts["segment"] > 0 and counts["via"] > 0 and counts["zone"] > 0
    # Les 17 footprints du STM32 devboard sont intacts
    assert stripped.count(b"(footprint") == stm32_board_bytes.count(b"(footprint")
    # Idempotent et immuable (nouvel objet, entrée non modifiée)
    assert _strip_routing(stripped)[1] == {"segment": 0, "via": 0, "zone": 0}


def test_strip_routing_malformed_board_raises(stm32_board_bytes):
    """Board tronqué au milieu d'un bloc segment → ValueError explicite
    (jamais d'IndexError opaque ; l'endpoint retombe sur la voie heuristique)."""
    text = stm32_board_bytes.decode("utf-8")
    m = re.search(r'\n\s*\(segment[\s\n]', text)
    assert m is not None
    truncated = text[: m.end()].encode("utf-8")

    with pytest.raises(ValueError, match="équilibrées"):
        _strip_routing(truncated)


def test_strip_routing_preserves_parseable_board(stm32_board_bytes, tmp_path):
    """Le board dé-routé reste chargeable par le reasoner (S-expr valide)."""
    from kicad_tools.reasoning import PCBReasoningAgent

    stripped, _counts = _strip_routing(stm32_board_bytes)
    board = tmp_path / "stripped.kicad_pcb"
    board.write_bytes(stripped)

    agent = PCBReasoningAgent.from_pcb(str(board))
    assert len(agent.state.components) == 17


def test_route_fn_receives_unrouted_board(stm32_board_bytes):
    """kct route ne rippe pas le routage existant (anciennes pistes = obstacles
    durs) : CHAQUE passe route_fn doit recevoir un board sans segment/via/zone,
    y compris la première (le board d'entrée arrive partiellement routé)."""
    route_fn = _route_fn_improving([40, 100])

    rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn,
        max_iterations=2, decide=_decide_move_d1,
    )

    assert len(route_fn.calls) == 2
    for pcb in route_fn.calls:
        _assert_no_routing(pcb)


def test_strip_is_logged_in_steps(stm32_board_bytes):
    """Le dé-routage est loggé (affichage ChatRail : l'utilisateur voit pourquoi
    les pistes disparaissent avant le re-routage)."""
    route_fn = _route_fn_improving([40, 100])

    _out, _pct, steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn,
        max_iterations=2, decide=_decide_move_d1,
    )

    assert any("dé-rout" in s.lower() for s in steps), steps

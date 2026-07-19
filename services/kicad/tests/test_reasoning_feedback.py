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

from tools.reasoning import (
    _select_applicable_moves,
    _strip_routing,
    parse_router_moves,
    rescue_with_placement_feedback,
)


def _route_fn_improving(script: list[int], suggestion: bool = True):
    """route_fn factice : renvoie les pourcentages scriptés, dans l'ordre.

    Signature contractuelle : (pcb_bytes) -> (routed_bytes, pct, failure_analysis).
    ``suggestion=False`` produit une analyse SANS « Move … » parsable — la boucle
    doit alors retomber sur le décideur LLM.
    """
    calls: list[bytes] = []

    def route_fn(pcb_bytes: bytes):
        calls.append(pcb_bytes)
        pct = script[min(len(calls), len(script)) - 1]
        if pct >= 100:
            analysis = ""
        elif suggestion:
            analysis = ("Unrouted nets:\n  SWO: Path blocked by component\n"
                        "Suggestion: Move D1 north to create routing channel")
        else:
            analysis = "Unrouted nets:\n  SWO: Path blocked by component"
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
    # suggestion=False → pas de « Move … » parsable → le LLM est consulté.
    route_fn = _route_fn_improving([40, 40], suggestion=False)

    def decide(prompt):
        return {"type": "route_net", "net": "SWO"}

    _out, _pct, steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn,
        max_iterations=2, decide=decide,
    )

    assert any("route_net" in s and ("interdit" in s or "refus" in s) for s in steps)


def test_failure_analysis_is_in_llm_prompt(stm32_board_bytes):
    """Le prompt envoyé au LLM contient l'analyse d'échec du routeur.

    (suggestion=False : sans « Move … » parsable, c'est le LLM qui décide —
    il doit recevoir l'analyse complète du routeur.)"""
    route_fn = _route_fn_improving([40, 100], suggestion=False)
    prompts: list[str] = []

    def decide(prompt):
        prompts.append(prompt)
        return _decide_move_d1(prompt)

    rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn, max_iterations=2, decide=decide,
    )

    assert prompts, "le LLM devait être consulté"
    assert "SWO: Path blocked" in prompts[0]


# ---------------------------------------------------------------------------
# Suiveur de suggestions déterministe (industrialisation 2026-07-13)
# ---------------------------------------------------------------------------
#
# Le routeur kct émet des suggestions machine-parsables (« Move D1 north to
# create routing channel », « Move C1, J1, U2 east »). Mesuré 2026-07-12 :
# suivre EXACTEMENT ces suggestions est le seul levier qui marche (déplacer
# autre chose dégrade 91%→73%). On les applique donc en DÉTERMINISTE, sans
# LLM — zéro coût, zéro dépendance clé API. Le LLM ne décide que s'il n'y a
# AUCUNE suggestion parsable.

def test_parse_router_moves_single_ref():
    analysis = ("Unrouted nets:\n  NRST: Path blocked\n"
                "            Suggestion: Move D1 north to create routing channel")
    assert parse_router_moves(analysis) == [("D1", "north")]


def test_parse_router_moves_multi_refs():
    analysis = "Suggestion: Move C1, J1, U2 east"
    assert parse_router_moves(analysis) == [("C1", "east"), ("J1", "east"), ("U2", "east")]


def test_parse_router_moves_tolerates_more_suffix():
    # Format réel observé (run monte-carlo 2026-07-13) : le routeur tronque la
    # liste avec « (+N more) » — il ne doit pas faire perdre toute la suggestion.
    analysis = "Suggestion: Move D1, J1, R1 (+1 more) north to create routing channel"
    assert parse_router_moves(analysis) == [
        ("D1", "north"), ("J1", "north"), ("R1", "north")]


def test_parse_router_moves_dedup_and_empty():
    assert parse_router_moves("") == []
    assert parse_router_moves(None) == []
    twice = "Move D1 north ... Move D1 north"
    assert parse_router_moves(twice) == [("D1", "north")]


def test_router_suggestions_applied_without_llm(stm32_board_bytes):
    """Suggestion parsable → déplacements déterministes, LLM JAMAIS consulté."""
    route_fn = _route_fn_improving([40, 100], suggestion=True)
    llm_calls: list[str] = []

    def decide(prompt):
        llm_calls.append(prompt)
        return None

    _out, pct, steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn, max_iterations=2, decide=decide,
    )

    assert pct == 100
    assert llm_calls == []                       # zéro appel LLM
    assert any("uggestion" in s and "D1" in s for s in steps), steps


def test_llm_fallback_when_no_parseable_suggestion(stm32_board_bytes):
    """Pas de « Move … » parsable → le LLM reprend la main (comportement actuel)."""
    route_fn = _route_fn_improving([40, 100], suggestion=False)
    llm_calls: list[str] = []

    def decide(prompt):
        llm_calls.append(prompt)
        return _decide_move_d1(prompt)

    _out, pct, _steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn, max_iterations=2, decide=decide,
    )

    assert pct == 100
    assert llm_calls, "le LLM devait être consulté en fallback"


def test_suggestion_for_unknown_ref_falls_back_to_llm(stm32_board_bytes):
    """Suggestion visant une ref absente du board → aucun déplacement
    déterministe possible → fallback LLM."""
    def route_fn(pcb_bytes: bytes):
        return pcb_bytes, 40, "Suggestion: Move Z99 north to create routing channel"

    llm_calls: list[str] = []

    def decide(prompt):
        llm_calls.append(prompt)
        return None

    rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn, max_iterations=2, decide=decide,
    )

    assert llm_calls, "ref inconnue : le LLM devait être consulté"


# ---------------------------------------------------------------------------
# Dédup anti-oscillation des suggestions (inter-itérations, 2026-07-19)
# ---------------------------------------------------------------------------
#
# Cas mesuré (STM32, 2026-07-14) : itération 1 = 91% + « Move U2 east » →
# itération 2 = 82% + « Move U2 west » (inverse exacte, pas fixe 3mm) →
# retour au placement initial → itération 3 re-route un board identique.
# La garde anti-régression sauvait le résultat, mais une itération de routage
# (la plus coûteuse) était brûlée pour rien. Règles : une suggestion inverse
# d'un déplacement déjà appliqué est rejetée ; une même suggestion est plafonnée
# à _MAX_SAME_MOVE applications ; l'état est LOCAL à un appel (4 workers
# uvicorn + retry placement orchestrateur = historique caduc entre appels).


def _route_fn_scripted(script: list[tuple[int, str]]):
    """route_fn factice : échoe le board reçu, (pct, analysis) scriptés par appel.

    Échoer le board réel est indispensable : la boucle recharge le board routé
    dans PCBReasoningAgent — un marqueur opaque n'aurait aucun composant.
    """
    calls: list[bytes] = []

    def route_fn(pcb_bytes: bytes):
        calls.append(pcb_bytes)
        pct, analysis = script[min(len(calls), len(script)) - 1]
        return pcb_bytes, pct, analysis

    route_fn.calls = calls  # type: ignore[attr-defined]
    return route_fn


def _component_position(stm32_board_bytes, tmp_path, ref: str) -> tuple[float, float]:
    """Position (x, y) d'une ref dans la fixture, via le reasoner lui-même."""
    from kicad_tools.reasoning import PCBReasoningAgent

    board = tmp_path / "probe.kicad_pcb"
    board.write_bytes(stm32_board_bytes)
    x, y = PCBReasoningAgent.from_pcb(str(board)).state.components[ref].position
    return float(x), float(y)


def test_inverse_suggestion_rejected_stops_oscillation(stm32_board_bytes):
    """Suggestion inverse (east puis west) → rejetée, pas de 3e routage inutile."""
    route_fn = _route_fn_scripted([
        (91, "Suggestion: Move D1 east to create routing channel"),
        (82, "Suggestion: Move D1 west to create routing channel"),
        (82, "Suggestion: Move D1 west to create routing channel"),
    ])

    _out, pct, steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn,
        max_iterations=3, decide=lambda p: None,
    )

    assert pct == 91
    assert len(route_fn.calls) == 2          # le board revenu à l'identique n'est pas re-routé
    assert any("oscillation" in s or "inverse" in s for s in steps), steps


def test_inverse_rejected_falls_back_to_llm(stm32_board_bytes, tmp_path):
    """Toutes les suggestions filtrées → la voie 2 (LLM) reprend la main."""
    route_fn = _route_fn_scripted([
        (91, "Suggestion: Move D1 east to create routing channel"),
        (82, "Suggestion: Move D1 west to create routing channel"),
        (82, ""),
    ])
    x_r1, y_r1 = _component_position(stm32_board_bytes, tmp_path, "R1")
    llm_calls: list[str] = []

    def decide(prompt):
        llm_calls.append(prompt)
        return {"type": "place_component", "ref": "R1", "at": [x_r1 + 2.0, y_r1]}

    rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn, max_iterations=3, decide=decide,
    )

    assert llm_calls, "suggestions filtrées : le LLM devait être consulté"
    assert len(route_fn.calls) == 3          # le déplacement LLM relance un routage


def test_same_suggestion_allowed_up_to_cap(stm32_board_bytes):
    """La même suggestion est ré-applicable (mur persistant) mais plafonnée à 2×."""
    analysis = "Suggestion: Move D1 north to create routing channel"
    route_fn = _route_fn_scripted([(40, analysis)] * 4)

    _out, _pct, steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn,
        max_iterations=4, decide=lambda p: None,
    )

    applied = [s for s in steps if "Suggestion du routeur appliquée : D1" in s]
    assert len(applied) == 2                 # _MAX_SAME_MOVE
    assert len(route_fn.calls) == 3          # 3e itération : rejet → arrêt propre


def test_select_applicable_moves_pure():
    """Fonction pure : inverse rejetée, répétition sous plafond acceptée, ordre préservé."""
    history = {("R5", "north"): 1}
    moves = [("R5", "south"), ("R5", "north"), ("C2", "west")]

    applicable, rejected = _select_applicable_moves(moves, history)

    assert applicable == [("R5", "north"), ("C2", "west")]
    assert len(rejected) == 1 and "R5" in rejected[0]

    # Plafond atteint → rejet de la répétition aussi
    applicable2, rejected2 = _select_applicable_moves(
        [("R5", "north")], {("R5", "north"): 2})
    assert applicable2 == []
    assert len(rejected2) == 1


def test_filtered_moves_do_not_consume_budget(stm32_board_bytes):
    """Le filtre précède la coupe max_moves_per_iter : une suggestion rejetée
    ne consomme pas le budget de déplacements de l'itération."""
    route_fn = _route_fn_scripted([
        (40, "Suggestion: Move D1 east to create routing channel"),
        (40, ("Suggestion: Move D1 west to create routing channel\n"
              "Suggestion: Move R1 north to create routing channel")),
        (40, ""),
    ])

    _out, _pct, steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn,
        max_iterations=3, max_moves_per_iter=1, decide=lambda p: None,
    )

    # Si la coupe passait avant le filtre, [D1 west] serait pris puis rejeté
    # → aucun déplacement → arrêt à 2 routages. Avec filtre d'abord, R1 passe.
    assert any("R1" in s and "appliquée" in s for s in steps), steps
    assert len(route_fn.calls) == 3


def test_dedup_state_is_per_call(stm32_board_bytes):
    """L'historique de dédup ne fuit pas entre deux appels (stateless service)."""
    def make_route_fn():
        return _route_fn_scripted([
            (40, "Suggestion: Move D1 east to create routing channel"),
            (40, ""),
        ])

    for _ in range(2):
        _out, _pct, steps = rescue_with_placement_feedback(
            stm32_board_bytes, route_fn=make_route_fn(),
            max_iterations=2, decide=lambda p: None,
        )
        assert any("Suggestion du routeur appliquée : D1" in s for s in steps), steps


def test_llm_move_to_visited_position_rejected(stm32_board_bytes, tmp_path):
    """Voie 2 : un place_component qui ramène une ref sur une position déjà
    occupée est rejeté (anti-oscillation LLM)."""
    x0, y0 = _component_position(stm32_board_bytes, tmp_path, "D1")

    route_fn = _route_fn_scripted([
        (40, "Unrouted nets:\n  SWO: Path blocked"),
        (40, "Unrouted nets:\n  SWO: Path blocked"),
    ])
    decisions = iter([
        {"type": "place_component", "ref": "D1", "at": [x0 + 5.0, y0]},
        {"type": "place_component", "ref": "D1", "at": [x0, y0]},   # retour → rejet
        None,
    ])

    _out, _pct, steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn,
        max_iterations=2, decide=lambda p: next(decisions),
    )

    assert any("déjà essayée" in s for s in steps), steps


def test_best_board_preserved_when_all_suggestions_filtered(stm32_board_bytes):
    """Garde anti-régression intacte : arrêt anticipé par la dédup → on rend
    toujours le meilleur board rencontré."""
    route_fn = _route_fn_scripted([
        (60, "Suggestion: Move C3 south to create routing channel"),
        (35, "Suggestion: Move C3 north to create routing channel"),
    ])

    out, pct, _steps = rescue_with_placement_feedback(
        stm32_board_bytes, route_fn=route_fn,
        max_iterations=3, decide=lambda p: None,
    )

    assert pct == 60
    assert out == route_fn.calls[0]          # le board de la 1re passe (60%), pas la 2e


# ---------------------------------------------------------------------------
# Robustesse decide
# ---------------------------------------------------------------------------

def test_decide_exception_returns_best_so_far(stm32_board_bytes):
    """decide crashe : arrêt propre, on rend le meilleur board déjà routé."""
    route_fn = _route_fn_improving([40], suggestion=False)

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
    route_fn = _route_fn_improving([40, 40, 40], suggestion=False)

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

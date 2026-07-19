"""Tests — alignement des règles DRC sur le tier fabricant escaladé (piste 4).

Problème : quand ``kct route --auto-mfr-tier`` escalade (ex. jlcpcb →
jlcpcb-tier1, via-in-pad autorisé), le juge ``kicad-cli pcb drc`` évalue
toujours le board avec les règles PAR DÉFAUT de KiCad (plus strictes que la
géométrie du tier) → violations résiduelles copper_edge / annular_width
garanties, sans défaut réel de fabricabilité.

Solution (100 % native kicad-tools) :
1. ``parse_retained_tier`` lit le tier réellement retenu dans le stdout de
   l'escalade ;
2. ``route_kct`` estampille le board (``(property "cirqix_mfr_tier" …)``,
   marqueur in-band — aucun changement de contrat d'API entre les étapes) ;
3. le router DRC lit le marqueur, le retire (kicad-cli ne le voit jamais) et
   écrit un sidecar ``.kicad_pro`` avec les règles du profil fabricant
   (``get_profile().get_design_rules()`` + ``apply_manufacturer_rules``) —
   kicad-cli charge le projet adjacent et juge aux règles du tier.

Générique : aucun nom de tier en dur hors échelle par défaut ; no-op complet
quand aucune escalade n'a eu lieu (pas de marqueur → pas de sidecar).
"""
from __future__ import annotations

import json
from pathlib import Path

from tools.kct_route import (
    _MFR_TIER_LADDER,
    extract_mfr_tier,
    parse_retained_tier,
    stamp_mfr_tier,
    strip_mfr_tier,
)
from tools.drc import copper_layer_count, write_mfr_project_sidecar
from tools.reasoning import _strip_routing


# ---------------------------------------------------------------------------
# parse_retained_tier — lecture du stdout de route_with_mfr_tier_escalation
# ---------------------------------------------------------------------------

def test_parse_retained_tier_success_line_wins():
    stdout = (
        "Tier ladder:     jlcpcb -> jlcpcb-tier1\n"
        "Tier 1/2: jlcpcb\n"
        "  Escalating to jlcpcb-tier1: via-in-pad needed\n"
        "Tier 2/2: jlcpcb-tier1\n"
        "  Tier jlcpcb-tier1 achieved routing success; stopping tier escalation.\n"
    )
    assert parse_retained_tier(stdout) == "jlcpcb-tier1"


def test_parse_retained_tier_recommendation_fallback():
    stdout = "...\nRecommendation: order from pcbway. Vias remplis requis.\n"
    assert parse_retained_tier(stdout) == "pcbway"


def test_parse_retained_tier_last_attempt_fallback():
    stdout = "Tier 1/2: jlcpcb\nTier 2/2: jlcpcb-tier1\n(no success line)"
    assert parse_retained_tier(stdout) == "jlcpcb-tier1"


def test_parse_retained_tier_none_when_no_escalation_output():
    assert parse_retained_tier("Nets routed: 9/9") is None
    assert parse_retained_tier("") is None


def test_parse_retained_tier_first_tier_success():
    """Succès dès le premier barreau : le tier retenu est le premier —
    l'appelant décide alors que c'est un no-op (pas d'escalade réelle)."""
    stdout = (
        "Tier 1/2: jlcpcb\n"
        "  Tier jlcpcb achieved routing success; stopping tier escalation.\n"
    )
    assert parse_retained_tier(stdout) == "jlcpcb"
    assert _MFR_TIER_LADDER.split(",")[0] == "jlcpcb"


# ---------------------------------------------------------------------------
# Marqueur in-band dans le .kicad_pcb
# ---------------------------------------------------------------------------

def test_stamp_extract_strip_roundtrip(stm32_board_bytes):
    stamped = stamp_mfr_tier(stm32_board_bytes, "jlcpcb-tier1")

    assert extract_mfr_tier(stamped) == "jlcpcb-tier1"
    assert extract_mfr_tier(stm32_board_bytes) is None

    stripped = strip_mfr_tier(stamped)
    assert extract_mfr_tier(stripped) is None
    # Parenthèses équilibrées conservées (S-expr valide)
    assert stripped.count(b"(") == stripped.count(b")")


def test_stamp_is_idempotent(stm32_board_bytes):
    """Re-stamper (ex. re-route après rescue) remplace, n'empile pas."""
    stamped = stamp_mfr_tier(stm32_board_bytes, "jlcpcb-tier1")
    restamped = stamp_mfr_tier(stamped, "pcbway")

    assert extract_mfr_tier(restamped) == "pcbway"
    assert restamped.count(b"cirqix_mfr_tier") == 1


def test_stamped_board_still_parseable_by_reasoner(stm32_board_bytes, tmp_path):
    """Le marqueur ne casse pas le parseur kicad-tools (rescue re-parse le
    board routé) — c'est LA condition de viabilité du marqueur in-band."""
    from kicad_tools.reasoning import PCBReasoningAgent

    stamped = stamp_mfr_tier(stm32_board_bytes, "jlcpcb-tier1")
    board = tmp_path / "stamped.kicad_pcb"
    board.write_bytes(stamped)

    agent = PCBReasoningAgent.from_pcb(str(board))
    assert len(agent.state.components) == 17


def test_stamped_board_survives_strip_routing(stm32_board_bytes):
    """_strip_routing (dé-routage du rescue) préserve le marqueur."""
    stamped = stamp_mfr_tier(stm32_board_bytes, "jlcpcb-tier1")
    stripped, _counts = _strip_routing(stamped)
    assert extract_mfr_tier(stripped) == "jlcpcb-tier1"


# ---------------------------------------------------------------------------
# Sidecar .kicad_pro — règles du profil fabricant pour kicad-cli
# ---------------------------------------------------------------------------

def test_copper_layer_count_synthetic():
    two = '(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user))'
    four = ('(layers (0 "F.Cu" signal) (1 "In1.Cu" power) '
            '(2 "In2.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user))')
    assert copper_layer_count(two) == 2
    assert copper_layer_count(four) == 4


def test_copper_layer_count_defaults_to_two_when_unparseable():
    assert copper_layer_count("(kicad_pcb)") == 2


def test_write_mfr_project_sidecar_matches_profile(tmp_path):
    from kicad_tools.manufacturers import get_profile

    pcb_path = tmp_path / "board.kicad_pcb"
    pcb_path.write_bytes(b"(kicad_pcb)")

    pro_path = write_mfr_project_sidecar(pcb_path, "jlcpcb-tier1", layers=4)

    assert pro_path == tmp_path / "board.kicad_pro"
    data = json.loads(Path(pro_path).read_text(encoding="utf-8"))
    rules = data["board"]["design_settings"]["rules"]
    expected = get_profile("jlcpcb-tier1").get_design_rules(4, 1.0)

    assert rules["min_copper_edge_clearance"] == expected.min_copper_to_edge_mm
    assert rules["min_via_annular_width"] == expected.min_annular_ring_mm
    assert rules["min_clearance"] == expected.min_clearance_mm
    assert rules["min_track_width"] == expected.min_trace_width_mm
    assert data["meta"]["manufacturer"] == "jlcpcb-tier1"


def test_write_mfr_project_sidecar_unknown_tier_raises(tmp_path):
    """Un tier inconnu lève (ValueError de get_profile) — l'appelant (router
    DRC) l'attrape et continue aux règles par défaut, jamais de crash 500."""
    import pytest

    pcb_path = tmp_path / "board.kicad_pcb"
    pcb_path.write_bytes(b"(kicad_pcb)")

    with pytest.raises(ValueError):
        write_mfr_project_sidecar(pcb_path, "fabricant-inexistant", layers=2)

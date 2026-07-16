"""Tests parse_routed_pct — le parser du % de routage natif kct route.

Régression : sur le board STM32 réel, kct route émet « Nets routed: 5/9 (56%) »
mais l'ancien parser attrapait le PREMIER « (NN%) » du stdout (une ligne de
progression intermédiaire, ex. 11%/22%) → routed_percent largement sous-évalué.
Conséquence prod : routers/routing.py compare routed_pct à _MIN_ROUTED_PCT pour
accepter/rejeter le résultat kicad-tools → un bon routage à 56% pouvait être
rejeté à tort comme 11%.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

_SERVICE_ROOT = Path(__file__).resolve().parents[1]  # services/kicad
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import kct_route  # noqa: E402
from tools.kct_route import parse_routed_pct  # noqa: E402


# stdout réel (extrait) de `kct route --strategy negotiated` sur 3_final.kicad_pcb.
# Contient des lignes de progression (11%, 22%) AVANT le résultat final 56%.
_PARTIAL_STDOUT = """\
Routing attempt 1 ... (11%)
Routing attempt 2 ... (22%)
Best result so far: 2L with 5/9 (56%)
Result: Best result on 2 layers (56% completion)
  Nets routed:     5/9
PARTIAL: Best result 56% on 2 layers
Routing Incomplete (56% connected)
  Nets routed: 5/9 (56%)
  Partial routes: 3/9 (33%) -- have segments, not all pads connected
  Unrouted: 1/9 (11%) -- no segments at all
"""

_COMPLETE_STDOUT = """\
Routing attempt 1 ... (40%)
Routing Complete
  Nets routed: 9/9 (100%)
"""

# Aucun net à router : tous les power nets coulés en zones cuivre.
_NO_ROUTE_STDOUT = "All power nets poured as copper zones. Nothing to route.\n"

# Ancien format historique de kct route (back-compat).
_OLD_FORMAT_STDOUT = "Routed: 8/8 nets (success)\n"


def test_parse_partial_uses_final_tally_not_progress_percent():
    # 5/9 = 56%, PAS 11% (ligne de progression) ni 11% (Unrouted: 1/9).
    assert parse_routed_pct(_PARTIAL_STDOUT) == 56


def test_parse_complete():
    assert parse_routed_pct(_COMPLETE_STDOUT) == 100


def test_parse_no_route_defaults_to_complete():
    assert parse_routed_pct(_NO_ROUTE_STDOUT) == 100


def test_parse_old_format_backcompat():
    assert parse_routed_pct(_OLD_FORMAT_STDOUT) == 100


def test_unrouted_line_is_not_mistaken_for_tally():
    # « Unrouted: 1/9 » contient le sous-mot "routed" mais ne doit jamais être
    # lu comme le compte de nets routés.
    assert parse_routed_pct("  Nets routed: 7/9 (78%)\n  Unrouted: 2/9\n") == 78


# ===========================================================================
# Politique routage Cirqix : VCC en PISTES + plan GND sur les 2 faces
# ===========================================================================
#
# kct route classe +5V/+3.3V comme nets « power » par leur NOM → les coule en
# plan et les exclut du routage. On les renomme en noms non-power AVANT le
# routage (→ pistes), restaure APRÈS, et garantit le plan GND sur F.Cu ET B.Cu.

_BOARD = (
    '(kicad_pcb\n'
    '  (net 1 "+5V")\n'
    '  (net 2 "+3.3V")\n'
    '  (net 3 "GND")\n'
    '  (footprint "R"\n'
    '    (pad "1" smd rect (net 1 "+5V"))\n'
    '    (pad "2" smd rect (net 3 "GND"))\n'
    '  )\n'
    ')\n'
)


def test_rename_nets_roundtrip():
    fwd = kct_route._rename_nets(_BOARD, kct_route._VCC_RENAME)
    assert '"+5V"' not in fwd and '"P5V0"' in fwd
    assert '"+3.3V"' not in fwd and '"P3V3"' in fwd
    back = kct_route._rename_nets(fwd, {v: k for k, v in kct_route._VCC_RENAME.items()})
    assert back == _BOARD  # renommage réversible, connectivité (numéros) intacte


def test_rename_nets_targets_only_net_declarations():
    # Un texte de propriété « +5V » (valeur/silk) ne doit PAS être renommé —
    # seules les déclarations (net N "…") le sont.
    txt = '(property "Value" "+5V")\n(net 1 "+5V")'
    out = kct_route._rename_nets(txt, kct_route._VCC_RENAME)
    assert '(property "Value" "+5V")' in out
    assert '(net 1 "P5V0")' in out


def test_gnd_zone_layers_native_format():
    # Format KiCad natif : (net N) + (net_name "GND") séparés.
    txt = '(zone\n\t(net 3)\n\t(net_name "GND")\n\t(layer "B.Cu")\n)'
    assert kct_route._gnd_zone_layers(txt) == {"B.Cu"}


def test_gnd_zone_layers_cli_format():
    # Format post-kicad-cli : (net "GND") inline.
    txt = '(zone\n\t(net "GND")\n\t(layer "F.Cu")\n)'
    assert kct_route._gnd_zone_layers(txt) == {"F.Cu"}


def test_gnd_zone_layers_ignores_non_gnd():
    txt = '(zone (net_name "+5V") (layer "F.Cu")) (zone (net_name "GND") (layer "B.Cu"))'
    assert kct_route._gnd_zone_layers(txt) == {"B.Cu"}


def test_ensure_gnd_both_planes_adds_missing_face(stm32_board_bytes):
    # Le board STM32 réel a GND sur B.Cu seulement → après, GND sur F.Cu + B.Cu.
    out = kct_route._ensure_gnd_both_planes(stm32_board_bytes)
    layers = kct_route._gnd_zone_layers(out.decode("utf-8", errors="replace"))
    assert {"F.Cu", "B.Cu"}.issubset(layers)


# ===========================================================================
# extract_failure_analysis — sections COMPLÈTES (bug troncature 2026-07-12)
# ===========================================================================
#
# kct route émet « Header\n====…\ncontenu » : l'en-tête est immédiatement suivi
# d'une ligne séparatrice ====. L'ancien code coupait au premier « \n==== » du
# chunk → il ne restait QUE l'en-tête : le reasoner ⑥b ne voyait JAMAIS les
# « Routing Suggestions » du routeur (« Move U2 north… ») et déplaçait à
# l'aveugle. Diagnostiqué sur le board STM32 (NRST blocked_path à tous les
# tiers --adaptive-rules, log complet B_adaptive.stdout.txt du 2026-07-12).

_SEP = "=" * 60

_FAILED_ROUTE_STDOUT = f"""\
PARTIAL: Best result 91% at 2 layers, tier 3

{_SEP}
Routing Incomplete (91% connected)
  Nets routed: 10/11 (91%)
{_SEP}

Unrouted nets:
  NRST: Path blocked by component or trace

{_SEP}
Failure Summary by Cause
{_SEP}
  BLOCKED_PATH: 1 net (100%)

{_SEP}
Routing Suggestions
{_SEP}

Based on failure analysis:

1. COMPONENT BLOCKING (1 net affected)
   Direct paths are blocked by component keepouts.
   Try: Reposition components or use vias to route around
   Suggestion: Move U2 north to create routing channel

{_SEP}
"""


def test_extract_failure_analysis_sections_not_truncated():
    out = kct_route.extract_failure_analysis(_FAILED_ROUTE_STDOUT)
    assert "NRST: Path blocked by component or trace" in out
    assert "BLOCKED_PATH: 1 net (100%)" in out       # Failure Summary complet
    assert "Reposition components" in out            # corps des Suggestions
    assert "Move U2 north" in out                    # la suggestion par net


def test_extract_failure_analysis_survives_header_glued_separator():
    minimal = "Routing Suggestions\n" + "=" * 60 + "\n\ncontenu utile\n"
    out = kct_route.extract_failure_analysis(minimal)
    assert "contenu utile" in out


def test_extract_failure_analysis_still_cuts_at_next_section():
    # La coupe au séparateur SUIVANT reste active : une section ne doit pas
    # avaler le bloc d'après.
    txt = ("Unrouted nets:\n  SWDIO: Path blocked\n\n"
           + _SEP + "\nBLOC SUIVANT NON PERTINENT\n")
    out = kct_route.extract_failure_analysis(txt)
    assert "SWDIO: Path blocked" in out
    assert "BLOC SUIVANT NON PERTINENT" not in out


# ===========================================================================
# _ensure_gnd_both_planes — marge bord (124 copper_edge_clearance mesurées
# le 2026-07-12 : zones GND collées à l'Edge.Cuts → DRC officiel rouge)
# ===========================================================================

def _zone_polygon_points(text: str, layer: str) -> list[tuple[float, float]]:
    """Points (xy …) des polygones de zones GND sur une couche donnée."""
    import re as _re
    pts: list[tuple[float, float]] = []
    starts = [m.start() for m in _re.finditer(r"\(zone\b", text)]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        blk = text[start:end]
        if f'(layer "{layer}")' not in blk or '"GND"' not in blk:
            continue
        for xy in _re.finditer(r"\(xy\s+([-\d.]+)\s+([-\d.]+)\)", blk):
            pts.append((float(xy.group(1)), float(xy.group(2))))
    return pts


def test_ensure_gnd_zone_respects_edge_clearance(stm32_board_bytes):
    # La zone GND ajoutée (F.Cu manquant sur le board de référence) doit être
    # en retrait d'au moins _ZONE_EDGE_CLEARANCE_MM du contour Edge.Cuts.
    import re as _re
    src = stm32_board_bytes.decode("utf-8", errors="replace")
    out = kct_route._ensure_gnd_both_planes(stm32_board_bytes)
    text = out.decode("utf-8", errors="replace")

    # bbox du contour Edge.Cuts (gr_rect ou gr_line, format multi-lignes KiCad 9)
    xs: list[float] = []
    ys: list[float] = []
    for m in _re.finditer(r"\(gr_(?:rect|line)\b", text):
        blk = text[m.start():m.start() + 300]
        if '(layer "Edge.Cuts")' not in blk:
            continue
        s = _re.search(r"\(start\s+([-\d.]+)\s+([-\d.]+)\)", blk)
        e = _re.search(r"\(end\s+([-\d.]+)\s+([-\d.]+)\)", blk)
        if s and e:
            xs += [float(s.group(1)), float(e.group(1))]
            ys += [float(s.group(2)), float(e.group(2))]
    assert xs and ys, "Edge.Cuts introuvable dans le board de référence"

    pts = _zone_polygon_points(text, "F.Cu")
    assert pts, "zone GND F.Cu non ajoutée"
    margin = kct_route._ZONE_EDGE_CLEARANCE_MM - 0.05  # tolérance arrondi
    for x, y in pts:
        assert min(xs) + margin <= x <= max(xs) - margin, f"x={x} trop près du bord"
        assert min(ys) + margin <= y <= max(ys) - margin, f"y={y} trop près du bord"


def _fake_route(stdout: str):
    """side_effect : écho src→dst, renvoie un CompletedProcess avec ce stdout."""
    def _run(src, dst, timeout_s):
        Path(dst).write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return _run


def test_route_kct_renames_vcc_before_routing(monkeypatch):
    captured: dict[str, str] = {}

    def fake_run(src, dst, timeout_s):
        captured["src"] = Path(src).read_text(encoding="utf-8")
        Path(dst).write_text(captured["src"], encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="Nets routed: 5/9 (56%)", stderr="")

    monkeypatch.setattr(kct_route, "_run_kct_route", fake_run)
    monkeypatch.setattr(kct_route, "_ensure_gnd_both_planes", lambda b: b)
    kct_route.route_kct(_BOARD.encode(), vcc_as_traces=True)
    # Le board passé AU routeur a les VCC renommés → routés en pistes.
    assert '"+5V"' not in captured["src"] and '"P5V0"' in captured["src"]
    assert '"+3.3V"' not in captured["src"] and '"P3V3"' in captured["src"]


def test_route_kct_restores_vcc_names_in_output(monkeypatch):
    def fake_run(src, dst, timeout_s):
        # Le routeur renvoie un board avec les noms renommés (comme le vrai kct).
        Path(dst).write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="Nets routed: 9/9 (100%)", stderr="")

    monkeypatch.setattr(kct_route, "_run_kct_route", fake_run)
    monkeypatch.setattr(kct_route, "_ensure_gnd_both_planes", lambda b: b)
    out, pct, _ = kct_route.route_kct(_BOARD.encode(), vcc_as_traces=True)
    text = out.decode("utf-8")
    assert '"+5V"' in text and '"P5V0"' not in text
    assert '"+3.3V"' in text and '"P3V3"' not in text
    assert pct == 100


def test_route_kct_ensures_gnd_both_planes(monkeypatch):
    called: dict[str, bytes] = {}

    def fake_gnd(b):
        called["bytes"] = b
        return b

    monkeypatch.setattr(kct_route, "_run_kct_route", _fake_route("Nets routed: 5/9 (56%)"))
    monkeypatch.setattr(kct_route, "_ensure_gnd_both_planes", fake_gnd)
    kct_route.route_kct(_BOARD.encode(), vcc_as_traces=True)
    assert "bytes" in called  # le plan GND 2 faces est bien appliqué


def test_run_kct_route_escalates_layers_until_100pct(monkeypatch):
    # negotiated + auto-layers + min-completion 1.0 → escalade automatique des
    # couches jusqu'à 100% routé (le défaut lib min-completion 0.95 s'arrête à
    # 95%). PAS de --max-layers : on laisse le défaut (escalade sans plafond fixé).
    captured: dict[str, list[str]] = {}

    def fake_subprocess_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(kct_route.subprocess, "run", fake_subprocess_run)
    kct_route._run_kct_route(Path("in.kicad_pcb"), Path("out.kicad_pcb"), 60)
    cmd = captured["cmd"]
    assert "--auto-layers" in cmd
    assert "--min-completion" in cmd
    assert cmd[cmd.index("--min-completion") + 1] == "1.0"
    assert "--max-layers" not in cmd  # pas de plafond fixé (auto-layers seul)
    assert "--strategy" in cmd and cmd[cmd.index("--strategy") + 1] == "negotiated"


def test_run_kct_route_uses_pro_clearance(monkeypatch):
    # Recette pro validée 2026-07-06 (board STM32 LQFP-48, DRC officiel juge) :
    # --clearance 0.2 aligne le routeur sur les règles DRC par défaut de KiCad.
    # Mesuré : 0.15 (défaut lib) → 6 courts + 112 copper_edge ; 0.2 → 0 court,
    # 6 edge, même complétion (82%) ; 0.25 → propre mais complétion 64%.
    captured: dict[str, list[str]] = {}

    def fake_subprocess_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(kct_route.subprocess, "run", fake_subprocess_run)
    kct_route._run_kct_route(Path("in.kicad_pcb"), Path("out.kicad_pcb"), 60)
    cmd = captured["cmd"]
    assert "--clearance" in cmd
    assert cmd[cmd.index("--clearance") + 1] == kct_route._CLEARANCE_MM == "0.2"


def test_run_kct_route_uses_mfr_tier_escalation(monkeypatch):
    # Benchmark 2026-07-14 (board STM32 placé, baseline negotiated 91%) :
    # --auto-mfr-tier jlcpcb→jlcpcb-tier1 (via-in-pad autorisé) = seul levier
    # natif qui atteint 100% (202s). L'escalade ne se déclenche QUE sur échec
    # → aucun surcoût fabricant sur les boards qui routent déjà en tier std.
    captured: dict[str, list[str]] = {}

    def fake_subprocess_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(kct_route.subprocess, "run", fake_subprocess_run)
    kct_route._run_kct_route(Path("in.kicad_pcb"), Path("out.kicad_pcb"), 60)
    cmd = captured["cmd"]
    assert "--auto-mfr-tier" in cmd
    assert cmd[cmd.index("--mfr-tier-ladder") + 1] == kct_route._MFR_TIER_LADDER \
        == "jlcpcb,jlcpcb-tier1"


def test_route_kct_replaces_kct_zones_with_edge_margin_zones(
        monkeypatch, stm32_board_bytes):
    # kct route auto-coule GND collé à l'Edge.Cuts (122 copper_edge_clearance
    # mesurées 2026-07-14 sur la variante 100%) : route_kct doit REMPLACER les
    # zones du routeur par nos plans GND en retrait _ZONE_EDGE_CLEARANCE_MM.
    def fake_run(src, dst, timeout_s):
        # Le routeur renvoie le board de référence (zones GND à 0.3mm du bord).
        Path(dst).write_bytes(stm32_board_bytes)
        return SimpleNamespace(returncode=0, stdout="Nets routed: 11/11 (100%)",
                               stderr="")

    monkeypatch.setattr(kct_route, "_run_kct_route", fake_run)
    out, pct, _ = kct_route.route_kct(stm32_board_bytes, vcc_as_traces=True)
    assert pct == 100
    text = out.decode("utf-8", errors="replace")
    margin = kct_route._ZONE_EDGE_CLEARANCE_MM - 0.05
    for layer in ("F.Cu", "B.Cu"):
        pts = _zone_polygon_points(text, layer)
        assert pts, f"plan GND {layer} manquant"
        for x, y in pts:
            assert 100.0 + margin <= x <= 160.0 - margin, f"{layer} x={x} au bord"
            assert 100.0 + margin <= y <= 140.0 - margin, f"{layer} y={y} au bord"


def test_route_kct_flag_off_keeps_vcc_names(monkeypatch):
    captured: dict[str, str] = {}

    def fake_run(src, dst, timeout_s):
        captured["src"] = Path(src).read_text(encoding="utf-8")
        Path(dst).write_text(captured["src"], encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="Nets routed: 5/5", stderr="")

    gnd_called = {"v": False}
    monkeypatch.setattr(kct_route, "_run_kct_route", fake_run)
    monkeypatch.setattr(
        kct_route, "_ensure_gnd_both_planes",
        lambda b: gnd_called.__setitem__("v", True) or b,
    )
    kct_route.route_kct(_BOARD.encode(), vcc_as_traces=False)
    # Flag off → comportement historique : pas de renommage, pas de plan forcé.
    assert '"+5V"' in captured["src"] and '"P5V0"' not in captured["src"]
    assert gnd_called["v"] is False

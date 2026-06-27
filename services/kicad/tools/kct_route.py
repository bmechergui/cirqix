"""Cirqix — routeur officiel kct route, partagé routers/routing + reasoner.

Extrait de routers/routing.py pour que la boucle placement-feedback du reasoner
(tools/reasoning.py) puisse rerouter avec le VRAI routeur négocié entre deux
batches de déplacements — sans dépendre du module FastAPI.

`route_kct` renvoie aussi le texte d'analyse d'échec du routeur (sections
« Unrouted nets / Partially connected / Routing Suggestions » du stdout) :
c'est l'entrée du LLM pour décider QUEL composant déplacer.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Budget de routage par défaut. 600s = budget « 8 couches » (cf. guide
# kicad-tools : ~90s simple / 300s 4 couches / 600s 8 couches) : route_kct
# escalade jusqu'à 6-8 couches (--auto-layers) en visant 100% (--min-completion
# 1.0), il faut donc laisser le temps aux tentatives multicouches de tourner.
# Mesuré sur STM32 LQFP-48 (3_final) : 60s→9%, 300s→36%, 600s→55% (converge
# en 431s). C'est un PLAFOND, pas une attente fixe : kct route rend la main dès
# 100% atteint. ⚠ Production : 600s = 10 min par appel route ; la boucle du
# reasoner (≤3 appels) peut atteindre 30 min — à arbitrer vs coût cible 0,12€.
_ROUTE_TIMEOUT_S: int = 600

# Escalade de couches : --auto-layers active l'escalade automatique ; on NE fixe
# PAS --max-layers (plafond) → le routeur utilise son défaut (4 couches, l'outil
# ne supporte que 2/4/6, pas d'« illimité »). --min-completion fixe la CIBLE de
# l'escalade : défaut lib = 0.95 (s'arrête à 95%, trop tôt) → on vise 100% du
# routable, donc le routeur escalade jusqu'à la couche minimale qui route tout
# (board simple reste en 2 couches, dense monte à 4).
_MIN_COMPLETION: str = "1.0"

_SERVICE_ROOT = Path(__file__).resolve().parents[1]  # services/kicad
_KCT_SRC = _SERVICE_ROOT / "kicad-tools" / "src"

# Politique routage Cirqix (vcc_as_traces) : kct route classe +5V/+3.3V comme
# nets « power » par leur NOM (kicad_tools.router.net_class) → auto_pour les
# coule en plan AVANT le routage et le routeur les EXCLUT du pathfinding. Aucun
# flag CLI ne désactive ce comportement. On contourne en renommant +5V/+3.3V en
# noms NON-power le temps du routage → traités comme signaux → routés en PISTES,
# puis on restaure les noms. GND reste le seul net coulé ; on garantit ensuite
# le plan GND sur les DEUX faces (F.Cu + B.Cu). Connectivité préservée : les
# pads référencent le net par NUMÉRO, seul le label change.
_VCC_RENAME: dict[str, str] = {"+5V": "P5V0", "+3.3V": "P3V3"}


def parse_routed_pct(stdout: str) -> int:
    """Parse routing completion % from kct route/reason output.

    kct route emits a definitive final tally ``Nets routed: N/M`` (the last
    occurrence is the best/final result; earlier ones are per-attempt
    progress). We anchor on that rather than on a bare ``(P%)`` token, because
    the stdout is full of intermediate progress percentages — grabbing the
    first ``(NN%)`` under-reported a 56% routing as 11%/22% and could make
    routers/routing.py reject a good result below ``_MIN_ROUTED_PCT``.

    Order of preference:
      1. last ``Nets routed: N/M`` (current kct wording)
      2. last ``Routed: N/M nets`` (older kct wording, back-compat)
      3. ``Best result NN%`` / ``(NN% connected|completion)`` summary
      4. default 100 when nothing needed routing (all power poured as zones)

    Note: ``Unrouted: 1/9`` contains the substring "routed" — the explicit
    ``Nets routed`` / ``Routed: ... nets`` anchors avoid matching it.
    """
    tally = re.findall(r'Nets routed:\s*(\d+)\s*/\s*(\d+)', stdout)
    if not tally:
        tally = re.findall(r'Routed:\s*(\d+)\s*/\s*(\d+)\s+nets', stdout)
    if tally:
        done, total = tally[-1]
        return round(int(done) / int(total) * 100) if int(total) > 0 else 100

    m = re.search(r'Best result\s+(\d+)%', stdout)
    if m:
        return int(m.group(1))
    m = re.search(r'\((\d+)%\s*(?:connected|completion)\)', stdout)
    if m:
        return int(m.group(1))
    return 100


def extract_failure_analysis(stdout: str) -> str:
    """Isole les sections d'analyse d'échec du stdout de kct route.

    Le routeur émet déjà un diagnostic structuré par net bloqué
    (« SWO: Path blocked by component — Suggestion: Move D1 north … ») :
    on le transmet tel quel au LLM plutôt que de le re-parser fragilement.
    """
    sections: list[str] = []
    for header in ("Unrouted nets:", "Partially connected nets",
                   "Failure Summary by Cause", "Routing Suggestions"):
        idx = stdout.rfind(header)
        if idx == -1:
            continue
        # Coupe au prochain double saut de ligne suivi d'un séparateur ====
        chunk = stdout[idx:idx + 1500]
        sections.append(chunk.split("\n====", 1)[0].strip())
    return "\n\n".join(sections)


def _kct_src_needed() -> bool:
    """True si le sous-process a besoin de ``kicad-tools/src`` sur le PYTHONPATH
    (local/CI où la lib n'est PAS pip-installée).

    En Docker prod ``kicad_tools`` est pip-installé (editable, avec le backend
    C++ ``router_cpp.so`` compilé par ``kct build-native``). Y AJOUTER notre
    copie vendorée masquerait ce backend → routeur Python pur 10-100× plus lent.
    On n'ajoute donc le PYTHONPATH QUE si le ``kicad_tools`` importable provient
    de notre src vendorée (cas local/CI via conftest), pas de site-packages.
    """
    if not _KCT_SRC.is_dir():
        return False
    try:
        import kicad_tools
        return _KCT_SRC in Path(kicad_tools.__file__).resolve().parents
    except Exception:
        return True  # pas importable → le sous-process en a besoin


def _kct_env() -> dict[str, str]:
    """Env des sous-process kct : UTF-8 forcé (logs emoji ⚠ ✓ → crash charmap
    sur console Windows cp1252) + kicad-tools/src sur le PYTHONPATH seulement en
    local/CI (cf. ``_kct_src_needed`` — jamais en Docker, pour ne pas masquer le
    backend C++ pip-installé)."""
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    if _kct_src_needed():
        prev = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(_KCT_SRC) + (os.pathsep + prev if prev else "")
    return env


def _rename_nets(text: str, mapping: dict[str, str]) -> str:
    """Renomme les déclarations ``(net N "old")`` → ``(net N "new")``.

    Cible UNIQUEMENT les déclarations/refs de net (pas les valeurs/silk) ; les
    pads référencent le net par NUMÉRO donc la connectivité est intacte.
    """
    for old, new in mapping.items():
        text = re.sub(rf'\(net (\d+) "{re.escape(old)}"\)', rf'(net \1 "{new}")', text)
    return text


def _gnd_zone_layers(text: str) -> set[str]:
    """Couches cuivre portant une zone du net GND. Gère les deux formats de net
    de zone : natif KiCad ``(net N) (net_name "GND")`` et post-cli ``(net "GND")``."""
    layers: set[str] = set()
    for m in re.finditer(r"\(zone\b", text):
        blk = text[m.start():m.start() + 400]
        name = re.search(r'\(net_name\s+"([^"]*)"', blk) or \
            re.search(r'\(net\s+(?:\d+\s+)?"([^"]*)"', blk)
        layer = re.search(r'\(layer\s+"([^"]+)"', blk)
        if name and layer and name.group(1) == "GND":
            layers.add(layer.group(1))
    return layers


def _ensure_gnd_both_planes(pcb_bytes: bytes) -> bytes:
    """Garantit un plan de masse GND sur F.Cu ET B.Cu : ajoute la zone GND sur
    la/les face(s) manquante(s) via ``kct zones add`` (ZoneGenerator pur Python,
    sans kicad-cli). Idempotent — si les deux faces ont déjà GND, no-op."""
    text = pcb_bytes.decode("utf-8", errors="replace")
    missing = [layer for layer in ("F.Cu", "B.Cu") if layer not in _gnd_zone_layers(text)]
    if not missing:
        return pcb_bytes
    with tempfile.TemporaryDirectory() as tmp:
        board = Path(tmp) / "board.kicad_pcb"
        board.write_bytes(pcb_bytes)
        for layer in missing:
            out = Path(tmp) / f"gnd_{layer.replace('.', '_')}.kicad_pcb"
            cmd = [
                sys.executable, "-m", "kicad_tools.cli", "zones", "add",
                str(board), "--net", "GND", "--layer", layer,
                "--priority", "0", "-o", str(out),
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", env=_kct_env(), check=False, timeout=60,
            )
            if out.exists():
                board = out
            else:
                logger.warning("zones add GND %s échoué: %s", layer,
                               (result.stderr or result.stdout)[-160:])
        return board.read_bytes()


def _run_kct_route(src: Path, dst: Path, timeout_s: int) -> subprocess.CompletedProcess[str]:
    """Lance ``kct route`` : stratégie ``negotiated`` + escalade de couches
    automatique jusqu'à 100% routé (``--auto-layers`` + ``--min-completion 1.0``,
    sans plafond ``--max-layers`` → défaut 4), auto-fix DRC, seed déterministe."""
    cmd = [
        sys.executable, "-m", "kicad_tools.cli", "route",
        str(src), "-o", str(dst),
        "--strategy", "negotiated",
        "--auto-layers",
        "--min-completion", _MIN_COMPLETION,
        "--auto-fix",
        "--seed", "42",
        "--timeout", str(timeout_s),
    ]
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout_s + 60, check=False, env=_kct_env(),
    )


def route_kct(
    pcb_bytes: bytes,
    timeout_s: int = _ROUTE_TIMEOUT_S,
    vcc_as_traces: bool = True,
) -> tuple[bytes, int, str]:
    """Route via the official ``kct route`` CLI (negotiated, auto-layers, auto-fix).

    Delegates routing to kicad-tools. By default applies the Cirqix routing
    policy (``vcc_as_traces=True``): +5V/+3.3V routed as TRACES (not poured as
    planes) and a GND plane guaranteed on BOTH faces (F.Cu + B.Cu). Set
    ``vcc_as_traces=False`` for the historical behaviour (kct auto-pours every
    power net). See ``_VCC_RENAME`` for the why.

    Assumes a PLACED board input (no pre-existing power zones) — the production
    flow (placement → routing) and the reasoner reroute loop both satisfy this.
    A board that already carries a +5V/+3.3V copper zone would keep it (only
    pad/net-declaration names are renamed, not zone ``net_name`` blocks).

    Returns (routed_pcb_bytes, routed_percent, failure_analysis).
    ``failure_analysis`` is "" when routing is complete.
    Raises RuntimeError on failure.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.kicad_pcb"
        dst = Path(tmp) / "output.kicad_pcb"

        # VCC en pistes : renomme +5V/+3.3V en noms non-power AVANT le routage.
        src_text = pcb_bytes.decode("utf-8", errors="replace")
        if vcc_as_traces:
            src_text = _rename_nets(src_text, _VCC_RENAME)
        src.write_text(src_text, encoding="utf-8")

        result = _run_kct_route(src, dst, timeout_s)

        if not dst.exists():
            raise RuntimeError(
                f"kct route produced no output (rc={result.returncode}): "
                f"{result.stderr[:200] or result.stdout[-200:]}"
            )

        routed_pct = parse_routed_pct(result.stdout)
        analysis = "" if routed_pct >= 100 else extract_failure_analysis(result.stdout)

        routed = dst.read_bytes()
        if vcc_as_traces:
            # Restaure les noms VCC, puis garantit le plan GND sur les 2 faces.
            restored = _rename_nets(
                routed.decode("utf-8", errors="replace"),
                {new: old for old, new in _VCC_RENAME.items()},
            )
            routed = _ensure_gnd_both_planes(restored.encode("utf-8"))

        routed_text = routed.decode("utf-8", errors="replace")
        seg_count = len(re.findall(r'\(segment[\s\n]', routed_text))
        zone_count = len(re.findall(r'\(zone[\s\n]', routed_text))
        logger.info("kct route: %d segments, %d zones (%d%%)",
                    seg_count, zone_count, routed_pct)
        return routed, routed_pct, analysis

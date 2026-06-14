"""Layrix — routeur officiel kct route, partagé routers/routing + reasoner.

Extrait de routers/routing.py pour que la boucle placement-feedback du reasoner
(tools/reasoning.py) puisse rerouter avec le VRAI routeur négocié entre deux
batches de déplacements — sans dépendre du module FastAPI.

`route_kct` renvoie aussi le texte d'analyse d'échec du routeur (sections
« Unrouted nets / Partially connected / Routing Suggestions » du stdout) :
c'est l'entrée du LLM pour décider QUEL composant déplacer.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_ROUTE_TIMEOUT_S: int = 60


def parse_routed_pct(stdout: str) -> int:
    """Parse routing completion % from kct route/reason output.

    Looks for the last "Routed: N/M nets" or "(P%)" line; defaults to 100 when
    no net needed routing (all power nets poured as zones).
    """
    pct = 100
    matches = re.findall(r'Routed:\s*(\d+)\s*/\s*(\d+)\s+nets', stdout)
    if matches:
        done, total = matches[-1]
        if int(total) > 0:
            pct = round(int(done) / int(total) * 100)
    else:
        m = re.search(r'\((\d+)%\s*\)', stdout)
        if m:
            pct = int(m.group(1))
    return pct


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


def route_kct(pcb_bytes: bytes, timeout_s: int = _ROUTE_TIMEOUT_S) -> tuple[bytes, int, str]:
    """Route via the official ``kct route`` CLI (negotiated, auto-layers, auto-fix).

    Delegates entirely to kicad-tools — it routes signal nets and pours power
    nets as copper zones itself. Output is returned as-is (no custom S-expr
    post-processing).

    Returns (routed_pcb_bytes, routed_percent, failure_analysis).
    ``failure_analysis`` is "" when routing is complete.
    Raises RuntimeError on failure.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.kicad_pcb"
        dst = Path(tmp) / "output.kicad_pcb"
        src.write_bytes(pcb_bytes)

        # Official kicad-tools recipe: let kct route auto-pour power nets
        # (GND→B.Cu, VCC→F.Cu) and route signal nets, escalating layers and
        # auto-fixing DRC. --seed makes it deterministic.
        cmd = [
            sys.executable, "-m", "kicad_tools.cli", "route",
            str(src), "-o", str(dst),
            "--strategy", "negotiated",
            "--auto-layers", "--auto-fix",
            "--seed", "42",
            "--timeout", str(timeout_s),
        ]
        # Force UTF-8 stdout dans l'ENFANT kct : ses logs contiennent des emojis
        # (⚠ ✓ …). Sur une console Windows cp1252, l'enfant crashe en plein
        # routage (`'charmap' codec can't encode '⚠'`) → attempts coupés à ~66%.
        # PYTHONUTF8=1 dans l'env subprocess règle ça durablement, sans patcher
        # la lib vendorée (re-perdu à chaque update). Inoffensif en Docker/Linux.
        import os as _os
        _env = {**_os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s + 60, check=False, env=_env,
        )

        if not dst.exists():
            raise RuntimeError(
                f"kct route produced no output (rc={result.returncode}): "
                f"{result.stderr[:200] or result.stdout[-200:]}"
            )

        routed_pct = parse_routed_pct(result.stdout)
        analysis = "" if routed_pct >= 100 else extract_failure_analysis(result.stdout)

        routed = dst.read_bytes()
        routed_text = routed.decode("utf-8", errors="replace")
        seg_count = len(re.findall(r'\(segment[\s\n]', routed_text))
        zone_count = len(re.findall(r'\(zone[\s\n]', routed_text))
        logger.info("kct route: %d segments, %d zones (%d%%)",
                    seg_count, zone_count, routed_pct)
        return routed, routed_pct, analysis

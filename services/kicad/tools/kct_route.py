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
#
# Piste testée et REJETÉE (benchmark stm32-validation 2026-07-04) :
# --starting-layers 4 + --targeted-ripup sur boards denses (LQFP-48, ~80 pads).
# Résultat : 55% identique au baseline (seeds 42/7/123, 300/600s), aucun gain
# de temps (509s vs ~431s), 23 unconnected identiques. Ne pas re-tester.
#
# ⚠ Le « plafond 55% » observé sur backend PYTHON n'est PAS structurel : la
# variance inter-run est énorme (45-73% mesurés ensuite sur le MÊME board,
# même seed — deadline wall-clock, issues upstream #2673/#2802). Le vrai
# levier mesuré (2026-07-04) est le backend C++ : `kct build-native` (Docker ;
# en local Windows : clang-cl requis, MSVC 2019 trop vieux pour nanobind) →
# le MÊME kct route passe de 55-73% / 431-600s à 100% routé en 121s sur le
# board STM32 LQFP-48 de référence. Sans le .pyd compilé, la lib retombe en
# silence sur l'A* Python pur 10-100× plus lent — vérifier
# `kct build-native --check` avant tout benchmark de routage.
_MIN_COMPLETION: str = "1.0"

# Clearance de routage — recette pro validée 2026-07-06 sur le board STM32
# LQFP-48 de référence (juge = kicad-cli pcb drc, jamais le DRC interne) :
# le défaut lib 0.15mm est INFÉRIEUR aux règles DRC par défaut de KiCad
# (0.2mm) → violations garanties. Mesuré : 0.15 → 6 courts + 112
# copper_edge ; 0.2 → 0 court + 6 edge, même complétion (82%) ; 0.25 →
# 0 court + 0 edge mais complétion 64%. 0.2 = point d'équilibre.
# Prérequis : patches Cirqix #6/#8 de la lib (angles + signe rotation pads,
# cf. DEPENDENCIES.md) — sans eux, courts fantômes quels que soient les flags.
_CLEARANCE_MM: str = "0.2"

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

# Escalade de tier fabricant — benchmark 2026-07-14 (board STM32 placé,
# baseline negotiated 91%, juge kicad-cli pcb drc) : le net restant échouait
# sur l'échappement du pad LQFP 0.5mm (« via-in-pad non supporté par le profil
# jlcpcb », issue upstream #2880). --auto-mfr-tier escalade vers jlcpcb-tier1
# (via-in-pad autorisé) UNIQUEMENT si le routage échoue au tier standard →
# 100% routé en 202s (vs 91%). Variantes rejetées au même benchmark :
# seed 7 = 91% · --starting-layers 4 = 91% · tier+4L = 82% · monte-carlo = 64%.
# Impact fabricant : tier1 = vias remplis (coût +), déclenché seulement quand
# nécessaire — les boards simples restent au tier standard.
_MFR_TIER_LADDER: str = "jlcpcb,jlcpcb-tier1"

# Piste 4 (2026-07-19) — alignement DRC sur le tier escaladé. Quand l'escalade
# retient un tier plus fin (via-in-pad…), le juge kicad-cli doit évaluer le
# board avec les règles de CE tier, pas les défauts KiCad (plus stricts →
# résiduels copper_edge/annular_width garantis). Le tier retenu est parsé du
# stdout de route_with_mfr_tier_escalation puis transporté IN-BAND dans le
# board (property racine KiCad) — aucun changement de contrat entre les étapes
# routage → DRC. Le router DRC retire le marqueur avant kicad-cli et écrit un
# sidecar .kicad_pro aux règles du profil (tools/drc.write_mfr_project_sidecar).
_MFR_TIER_PROPERTY = "cirqix_mfr_tier"
_TIER_SUCCESS_RE = re.compile(r"Tier (\S+) achieved routing success")
_TIER_RECO_RE = re.compile(r"Recommendation: order from (\S+?)\.")
_TIER_ATTEMPT_RE = re.compile(r"Tier \d+/\d+: (\S+)")
_MFR_TIER_MARKER_RE = re.compile(
    r'\n?[ \t]*\(property "' + _MFR_TIER_PROPERTY + r'" "([^"]+)"\)')


def parse_retained_tier(stdout: str) -> str | None:
    """Tier fabricant réellement retenu par l'escalade, depuis le stdout kct.

    Ordre de préférence (messages réels de route_with_mfr_tier_escalation) :
      1. dernière ligne « Tier X achieved routing success » (définitif) ;
      2. « Recommendation: order from X. » (résumé final) ;
      3. dernière tentative « Tier i/n: X » (best-effort, routage partiel) ;
      4. None — aucun mode escalade dans la sortie.
    """
    matches = _TIER_SUCCESS_RE.findall(stdout or "")
    if matches:
        return matches[-1]
    m = _TIER_RECO_RE.search(stdout or "")
    if m:
        return m.group(1)
    attempts = _TIER_ATTEMPT_RE.findall(stdout or "")
    if attempts:
        return attempts[-1]
    return None


def strip_mfr_tier(pcb_bytes: bytes) -> bytes:
    """Retire le marqueur de tier du board (kicad-cli ne doit jamais le voir)."""
    text = pcb_bytes.decode("utf-8", errors="replace")
    return _MFR_TIER_MARKER_RE.sub("", text).encode("utf-8")


def extract_mfr_tier(pcb_bytes: bytes) -> str | None:
    """Tier fabricant estampillé dans le board, ou None (pas d'escalade)."""
    m = _MFR_TIER_MARKER_RE.search(pcb_bytes.decode("utf-8", errors="replace"))
    return m.group(1) if m else None


def stamp_mfr_tier(pcb_bytes: bytes, tier: str) -> bytes:
    """Estampille le tier retenu dans le board (property racine KiCad).

    Idempotent : un marqueur existant est remplacé, jamais empilé (le rescue
    re-route le même board plusieurs fois). Insertion avant la parenthèse
    fermante racine — S-expr équilibrée garantie.
    """
    text = strip_mfr_tier(pcb_bytes).decode("utf-8", errors="replace").rstrip()
    if not text.endswith(")"):
        raise ValueError("stamp_mfr_tier: .kicad_pcb malformé (pas de ')' final)")
    return (text[:-1].rstrip()
            + f'\n  (property "{_MFR_TIER_PROPERTY}" "{tier}")\n)\n').encode("utf-8")


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

    Format kct : « Header\\n====…\\ncontenu » — l'en-tête est immédiatement
    suivi d'une ligne séparatrice ====. Il faut SAUTER ce séparateur collé
    avant de couper à la prochaine ligne ====, sinon la section revient vide
    (bug corrigé 2026-07-12 : le reasoner ⑥b ne recevait jamais les
    « Routing Suggestions » du routeur et déplaçait les composants à l'aveugle).
    """
    sections: list[str] = []
    for header in ("Unrouted nets:", "Partially connected nets",
                   "Failure Summary by Cause", "Routing Suggestions"):
        idx = stdout.rfind(header)
        if idx == -1:
            continue
        body = stdout[idx + len(header):idx + len(header) + 1500]
        sep = re.match(r"\s*\n=+\n", body)
        if sep:
            body = body[sep.end():]
        body = body.split("\n====", 1)[0]
        sections.append((header + "\n" + body).strip())
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


# Retrait des zones GND vs Edge.Cuts. La règle DRC KiCad par défaut
# (copper-to-edge) est 0.5mm : des zones collées au bord = violations
# copper_edge_clearance garanties (124 mesurées le 2026-07-12 sur le board
# STM32 de référence, kicad-cli pcb drc juge). ``kct zones add`` (CLI)
# n'expose pas ce retrait → on passe par l'API native ZoneGenerator
# (edge_clearance = inset natif du contour, shapely buffer(-c)).
_ZONE_EDGE_CLEARANCE_MM: float = 0.5


def _ensure_gnd_both_planes(pcb_bytes: bytes) -> bytes:
    """Garantit un plan de masse GND sur F.Cu ET B.Cu : ajoute la zone GND sur
    la/les face(s) manquante(s) via l'API native ``ZoneGenerator`` (pur Python,
    sans kicad-cli), avec retrait ``_ZONE_EDGE_CLEARANCE_MM`` du bord de carte.
    Idempotent — si les deux faces ont déjà GND, no-op."""
    text = pcb_bytes.decode("utf-8", errors="replace")
    missing = [layer for layer in ("F.Cu", "B.Cu") if layer not in _gnd_zone_layers(text)]
    if not missing:
        return pcb_bytes
    try:
        from kicad_tools.zones import ZoneGenerator
    except ImportError:
        if _KCT_SRC.is_dir():
            sys.path.insert(0, str(_KCT_SRC))
            from kicad_tools.zones import ZoneGenerator
        else:
            raise
    with tempfile.TemporaryDirectory() as tmp:
        board = Path(tmp) / "board.kicad_pcb"
        board.write_bytes(pcb_bytes)
        # Best-effort PAR FACE (comme l'ancien chemin CLI) : un échec sur une
        # face ne doit pas perdre la zone déjà posée sur l'autre.
        for layer in missing:
            out = Path(tmp) / f"gnd_{layer.replace('.', '_')}.kicad_pcb"
            try:
                gen = ZoneGenerator.from_pcb(board, edge_clearance=_ZONE_EDGE_CLEARANCE_MM)
                gen.add_zone(net="GND", layer=layer, priority=0)
                gen.save(out)
                board = out
            except Exception:
                # ERROR + traceback : la garantie « plan GND double face »
                # (docstring + route_kct) n'est PAS respectée sur cette face —
                # impact fabricabilité, doit être visible en prod.
                logger.exception(
                    "zones GND %s échoué — garantie plan GND double face non respectée",
                    layer)
        return board.read_bytes()


_ZONE_BLOCK_RE = re.compile(r"\n\s*\(zone[\s\n]")


def _strip_zone_blocks(text: str) -> str:
    """Retire tous les blocs top-level ``(zone …)`` d'un .kicad_pcb.

    kct route auto-coule le net GND en zones COLLÉES à l'Edge.Cuts (122
    copper_edge_clearance mesurées 2026-07-14 au DRC officiel) : on retire ses
    zones après routage et ``_ensure_gnd_both_planes`` repose les plans GND
    avec la marge bord. Pistes/vias intacts — seule la provenance des zones
    change. Scan à parenthèses équilibrées, insensible aux parenthèses dans
    les chaînes quotées (même technique que reasoning._strip_routing).
    """
    out: list[str] = []
    i = 0
    while True:
        m = _ZONE_BLOCK_RE.search(text, i)
        if not m:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:m.start()])
        j = text.index("(", m.start())
        depth, in_str = 0, False
        while True:
            if j >= len(text):
                raise ValueError(
                    "_strip_zone_blocks: parenthèses non équilibrées "
                    f"(zone à l'offset {m.start()}) — .kicad_pcb malformé")
            c = text[j]
            if in_str:
                if c == "\\":
                    j += 1
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        i = j + 1


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
        "--clearance", _CLEARANCE_MM,
        "--auto-mfr-tier",
        "--mfr-tier-ladder", _MFR_TIER_LADDER,
        "--seed", "42",
        "--timeout", str(timeout_s),
    ]
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout_s + 60, check=False, env=_kct_env(),
    )


def _missing_nets(analysis: str | None) -> list[str]:
    """Noms des nets listés dans les sections « Unrouted nets » et
    « Partially connected nets » d'une analyse d'échec du routeur.

    Parsing scopé par section — les lignes « Suggestion: … », les compteurs
    « (N): » et les causes « BLOCKED_PATH: … » ne sont jamais pris pour des
    nets (ils partagent le format ``mot:``)."""
    nets: list[str] = []
    section: str | None = None
    for line in (analysis or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("Unrouted nets"):
            section = "unrouted"
            continue
        if s.startswith("Partially connected nets"):
            section = "partial"
            continue
        if s.startswith(("Failure Summary", "Routing Suggestions", "Based on")):
            section = None
            continue
        if section and ":" in s:
            name = s.split(":", 1)[0].strip()
            if name and " " not in name and not name.startswith(("Suggestion", "(")):
                nets.append(name)
    return nets


def _only_power_nets_missing(analysis: str | None) -> bool:
    """True si TOUS les nets manquants sont des rails power (et qu'il y en a).

    Détection native ``kicad_tools.explain.mistakes.is_power_net`` après
    re-mapping des noms renommés par la politique vcc_as_traces (P3V3 → +3.3V).
    C'est la condition de déclenchement du fallback plans power : un signal
    manquant ne serait PAS résolu par un plan — inutile de re-router."""
    nets = _missing_nets(analysis)
    if not nets:
        return False
    try:
        from kicad_tools.explain.mistakes import is_power_net
    except ImportError:
        return False  # kicad-tools absent → pas de fallback (comportement inchangé)
    reverse = {new: old for old, new in _VCC_RENAME.items()}
    return all(is_power_net(reverse.get(n, n)) for n in nets)


def route_kct(
    pcb_bytes: bytes,
    timeout_s: int = _ROUTE_TIMEOUT_S,
    vcc_as_traces: bool = True,
) -> tuple[bytes, int, str]:
    """Route via kct (negotiated, auto-layers, auto-mfr-tier) + fallback plans power.

    Politique Cirqix d'abord (``vcc_as_traces=True`` : +5V/+3.3V en PISTES,
    plan GND garanti double face). **Fallback industriel (2026-07-19)** : si le
    routage pistes laisse UNIQUEMENT des rails power partiels (cas mesuré board
    STM32 : tous signaux routés, P3V3 10/15 pads SANS suggestion → plancher
    91 % indépassable par le rescue), re-route une fois avec
    ``vcc_as_traces=False`` — kct coule les rails en plans cuivre (pratique
    standard multi-couches) → 100 % mesuré sur le même placement. Le meilleur
    des deux résultats est rendu (jamais de régression). Coût pire cas : 2×
    ``timeout_s``.

    Returns (routed_pcb_bytes, routed_percent, failure_analysis).
    ``failure_analysis`` is "" when routing is complete.
    Raises RuntimeError on failure.
    """
    routed, pct, analysis = _route_once(pcb_bytes, timeout_s, vcc_as_traces)
    if pct >= 100 or not vcc_as_traces or not _only_power_nets_missing(analysis):
        return routed, pct, analysis

    logger.info(
        "route_kct: seuls des rails power restent partiels (%s) → re-route en "
        "plans power (fallback industriel)", ", ".join(_missing_nets(analysis)))
    routed_planes, pct_planes, analysis_planes = _route_once(
        pcb_bytes, timeout_s, False)
    if pct_planes > pct:
        return routed_planes, pct_planes, analysis_planes
    return routed, pct, analysis


def _route_once(
    pcb_bytes: bytes,
    timeout_s: int,
    vcc_as_traces: bool,
) -> tuple[bytes, int, str]:
    """Une passe de routage kct complète (rename VCC, route, post-process).

    ``vcc_as_traces=True`` : +5V/+3.3V renommés → routés en pistes, zones kct
    remplacées par nos plans GND en retrait. ``False`` : comportement kct
    historique (rails power coulés en plans par le routeur lui-même).

    Assumes a PLACED board input (no pre-existing power zones) — the production
    flow (placement → routing) and the reasoner reroute loop both satisfy this.
    A board that already carries a +5V/+3.3V copper zone would keep it (only
    pad/net-declaration names are renamed, not zone ``net_name`` blocks).
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
            # Restaure les noms VCC, remplace les zones kct (collées au bord)
            # par nos plans GND en retrait, sur les 2 faces.
            restored = _rename_nets(
                routed.decode("utf-8", errors="replace"),
                {new: old for old, new in _VCC_RENAME.items()},
            )
            restored = _strip_zone_blocks(restored)
            routed = _ensure_gnd_both_planes(restored.encode("utf-8"))

        # Piste 4 : estampille le tier retenu SI l'escalade a dépassé le
        # premier barreau — le router DRC alignera ses règles dessus. No-op
        # (aucun marqueur) quand le board route au tier standard.
        retained_tier = parse_retained_tier(result.stdout)
        if retained_tier and retained_tier != _MFR_TIER_LADDER.split(",")[0]:
            routed = stamp_mfr_tier(routed, retained_tier)
            logger.info("kct route: tier fabricant escaladé retenu = %s", retained_tier)

        routed_text = routed.decode("utf-8", errors="replace")
        seg_count = len(re.findall(r'\(segment[\s\n]', routed_text))
        zone_count = len(re.findall(r'\(zone[\s\n]', routed_text))
        logger.info("kct route: %d segments, %d zones (%d%%)",
                    seg_count, zone_count, routed_pct)
        return routed, routed_pct, analysis

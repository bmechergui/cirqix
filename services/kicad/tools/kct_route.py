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
from functools import lru_cache
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

# ⚠ 2026-07-30 — `_CLEARANCE_MM` n'est plus la valeur passée au routeur, mais
# seulement le REPLI si le profil fabricant est indisponible.
#
# La recette 0.2 ci-dessus est datée : elle a été calibrée le 2026-07-06 quand
# `kicad-cli pcb drc` jugeait avec les DÉFAUTS KiCad (0,2 mm), faute de sidecar
# projet. Le chantier DRC-clean du 2026-07-19 a aligné le juge sur le profil
# fabricant (`drc.write_mfr_project_sidecar` → `get_design_rules`) : jlcpcb vaut
# 0,127 mm à 2 couches et 0,1016 mm à 4. La constante du routeur n'a pas suivi,
# si bien que le routeur s'interdisait ~2× ce que le fabricant autorise ET ce
# que le juge accepte — sans le moindre gain de fabricabilité, un court-circuit
# étant un CONTACT cuivre, insensible à la clearance.
#
# Coût géométrique mesurable sur LQFP-48 (pas 0,5 mm, pads 0,3 mm → gap
# inter-pads 0,2 mm) : la piste maximale passant entre deux pads vaut
# `(0,5 - 2 × clearance)`, soit 0,1 mm à 0,2 mm de clearance — SOUS le minimum
# fabricant, donc aucun échappement de surface n'est possible. À 0,1016 mm, une
# piste de 0,127 mm passe. C'est la cause géométrique du plafond de routage
# observé sur ce boîtier depuis juillet.
_CLEARANCE_FALLBACK_MM: str = _CLEARANCE_MM

# Marge ajoutée au plancher du profil avant transmission au routeur.
#
# Le plancher fabricant est une valeur EXACTE que le juge applique à la
# décimale près, alors que le routeur arrondit à sa grille interne. Mesuré le
# 2026-07-30 (board STM32 rerouté à 100 %) : en transmettant 0,1016 mm (4 mil)
# tel quel, le routeur a posé une piste à 0,1000 mm et le juge a levé
# « clearance (requise 0.1016 ; réelle 0.1000) » — une erreur DRC pour 1,6 µm.
# 10 µm de marge absorbent la troncature sans coût mesurable de complétion.
_CLEARANCE_SAFETY_MARGIN_MM: float = 0.01


def _profile_clearance_mm(fine_pitch: bool, pcb_text: str) -> str:
    """Clearance de routage dérivée du profil fabricant, jamais codée en dur.

    Même source de vérité que le juge (`drc.write_mfr_project_sidecar` appelle
    `get_profile(tier).get_design_rules(layers, 1.0)`) : routeur et DRC doivent
    appliquer le MÊME règlement, sinon on recrée le motif « 100 % routé, jamais
    fabricable » — le routeur travaillant sous des règles que le juge ignore.

    Tier retenu = premier barreau de `_MFR_TIER_LADDER`. `--auto-mfr-tier` ne
    peut qu'escalader vers plus permissif : partir du barreau de base est donc
    le choix conservateur.

    `fine_pitch` impose de raisonner à 4 couches, en cohérence avec le
    `--starting-layers 4` que `_build_route_cmd` ajoute dans ce cas.

    Repli sur `_CLEARANCE_FALLBACK_MM` si le profil est indisponible : une
    dépendance manquante ne doit jamais faire échouer un routage.
    """
    try:
        from kicad_tools.manufacturers import get_profile

        from tools.drc import copper_layer_count

        layers = 4 if fine_pitch else copper_layer_count(pcb_text)
        tier = _MFR_TIER_LADDER.split(",")[0].strip()
        rules = get_profile(tier).get_design_rules(layers, 1.0)
        return f"{rules.min_clearance_mm + _CLEARANCE_SAFETY_MARGIN_MM:g}"
    except Exception as exc:  # profil absent, API changée, import cassé…
        logger.warning(
            "route: profil fabricant indisponible (%s) — clearance de repli %s mm",
            exc, _CLEARANCE_FALLBACK_MM)
        return _CLEARANCE_FALLBACK_MM

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

# Noms de masse : les SEULS nets qu'on laisse couler en plan (cf. politique
# ci-dessus). Tout autre rail power doit être routé en pistes.
_GROUND_NAMES: frozenset[str] = frozenset({"GND", "AGND", "DGND", "PGND", "VSS", "EARTH"})

# Préfixe des noms neutres. Doit échapper à TOUTES les regex POWER de
# kicad_tools.router.net_class (ancrées en ^) — d'où un préfixe qui ne commence
# ni par V, ni par +, ni par PWR/POWER.
_NEUTRAL_NET_PREFIX: str = "CIRQIX_NET_"


def _is_ground_net(name: str) -> bool:
    upper = name.upper()
    return upper in _GROUND_NAMES or upper.startswith("GND")


def _power_rename_map(text: str) -> dict[str, str]:
    """``{nom_power: nom_neutre}`` pour TOUS les rails power du board sauf la masse.

    La table statique ``_VCC_RENAME`` ne couvrait que ``+5V``/``+3.3V``. Or le
    routeur classe POWER par regex — ``^(VCC|VDD|VBUS|VIN|VOUT|PWR|POWER|AVDD|
    DVDD)…`` — et EXCLUT du pathfinding tout net ainsi classé, en supposant qu'il
    sera coulé en plan. Notre flux ne coule que GND : un rail nommé ``VCC``
    ressortait donc sans le moindre segment ni zone (non connecté), pendant que
    ``kct route`` annonçait 100 % puisqu'il ne compte pas les nets power. Mesuré
    le 2026-07-27 sur ``examples/led-blinker-full-pipeline`` : 4 pads VCC
    orphelins vus par kicad-cli, DRC jamais clean.

    La map est donc dérivée du board plutôt que codée en dur : elle suit la liste
    de la lib au lieu d'en dupliquer un extrait. ``+5V``/``+3.3V`` conservent
    leurs noms historiques pour ne pas invalider les mesures antérieures.

    Oracle : ``router.net_class.classify_from_name`` — celui que le routeur
    utilise RÉELLEMENT pour exclure un net. Ne pas confondre avec
    ``explain.mistakes.is_power_net``, qui travaille par sous-chaîne et diverge
    dans les deux sens : il rate ``VBUS`` (que le routeur, lui, exclut) et
    classe ``P5V0`` comme power (alors que le routeur le voit comme un signal —
    c'est précisément ce qui fait marcher le renommage historique).
    """
    try:
        from kicad_tools.router.net_class import NetClass, classify_from_name
    except ImportError:
        return dict(_VCC_RENAME)  # kicad-tools absent → comportement inchangé

    names = sorted({m.group(2) for m in re.finditer(r'\(net (\d+) "([^"]+)"\)', text)})
    mapping: dict[str, str] = {}
    for index, name in enumerate(names):
        if _is_ground_net(name) or classify_from_name(name) is not NetClass.POWER:
            continue
        mapping[name] = _VCC_RENAME.get(name, f"{_NEUTRAL_NET_PREFIX}{index}")
    return mapping

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
    # Patch Cirqix #7 — mode « géométrie sûre » pour le SOUS-PROCESSUS kct.
    # `DEPENDENCIES.md` le documente depuis le 2026-07-06, mais la variable
    # n'était fixée NULLE PART dans le code : le patch était écrit, jamais
    # appliqué. Les passes de l'optimiseur qui déplacent la géométrie tournaient
    # donc à chaque routage de production, avec le dégât mesuré — 204 erreurs
    # DRC sur un board routé le 2026-07-31 (107 clearance, 84 solder_mask_bridge,
    # 13 courts), contre 3 courts avec l'optimiseur neutralisé.
    #
    # Les coins à 45° sont réintroduits APRÈS, par `convert_corners_45_drc_aware`,
    # qui les annule net par net dès qu'une violation apparaît. On obtient ainsi
    # des angles pro SANS payer les courts.
    #
    # La variable ne vise que le sous-processus : le nôtre garde un environnement
    # propre, sinon `OptimizationConfig.__post_init__` désactiverait aussi la
    # passe 45° de la post-conversion.
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "KCT_SAFE_OPTIMIZE": "1"}
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


# ---------------------------------------------------------------------------
# Pads NC stricts (chantier DRC-clean 2026-07-19)
# ---------------------------------------------------------------------------
# kicad-tools exempte les pads ``(net 0 "")`` de son validateur de clearance
# (arbitrage upstream #3281) → le routeur peut TRAVERSER un pad NC. Mesuré sur
# les boards routés 100 % (runs 7/9 stm32-validation) : 9 shorting_items +
# 9 solder_mask_bridge, tous contre les pads 33/43 du LQFP-48 — des broches
# silicium inutilisées, donc des courts RÉELS. On assigne un net unique à
# chaque pad sans net AVANT le routage (obstacle normal), retiré APRÈS : le
# board final garde son contrat (pads NC = ``(net 0 "")``).
# Coût mesuré (scripts/strict_nc_route.py, backend C++) : complétion brute
# 100→82 % (run 7) / 82→73 % (run 8) — compensé par rescue + retry placement.
_NC_NET_PREFIX = "CIRQIX_NC_"
_NC_NET_DECL_RE = re.compile(r'\n[ \t]*\(net \d+ "' + _NC_NET_PREFIX + r'\d+"\)')
_NC_NET_REF_RE = re.compile(r'\(net \d+ "' + _NC_NET_PREFIX + r'\d+"\)')


def assign_nc_nets(text: str) -> tuple[str, int]:
    """Donne un net unique ``CIRQIX_NC_<n>`` à chaque pad ``(net 0 "")``.

    Seules les références de pad (après le premier ``(footprint``) sont
    converties — la déclaration racine ``(net 0 "")`` reste intacte. Les
    déclarations des nouveaux nets sont insérées après la dernière déclaration
    existante (un net référencé mais non déclaré rendrait le board invalide).
    Renvoie (board modifié, nombre de pads convertis) ; no-op → (text, 0).
    """
    fp = text.find("(footprint")
    if fp == -1:
        return text, 0
    head, body = text[:fp], text[fp:]

    next_net = max([int(n) for n in re.findall(r"\(net (\d+)", text)] or [0]) + 1
    declarations: list[str] = []

    def _assign(_m: re.Match) -> str:
        nonlocal next_net
        n = next_net
        next_net += 1
        declarations.append(f'  (net {n} "{_NC_NET_PREFIX}{n}")')
        return f'(net {n} "{_NC_NET_PREFIX}{n}")'

    body = re.sub(r'\(net 0 ""\)', _assign, body)
    if not declarations:
        return text, 0

    last = None
    for m in re.finditer(r'\n[ \t]*\(net \d+ "[^"]*"\)', head):
        last = m
    if last is None:
        return text, 0  # pas de section nets identifiable → no-op prudent
    idx = last.end()
    head = head[:idx] + "\n" + "\n".join(declarations) + head[idx:]
    return head + body, len(declarations)


def strip_nc_nets(text: str) -> str:
    """Retire les nets temporaires ``CIRQIX_NC_*`` (inverse d'assign_nc_nets).

    Robuste à une re-numérotation par le routeur : le marqueur est le NOM,
    jamais le numéro. Déclarations (avant le premier footprint) supprimées,
    références de pad restaurées en ``(net 0 "")``.
    """
    fp = text.find("(footprint")
    if fp == -1:
        return text
    head, body = text[:fp], text[fp:]
    head = _NC_NET_DECL_RE.sub("", head)
    body = _NC_NET_REF_RE.sub('(net 0 "")', body)
    return head + body


_SEG_VIA_BLOCK_RE = re.compile(r"\n[ \t]*\((segment|via)[\s\n]")


def strip_nc_escape_stubs(text: str) -> tuple[str, int]:
    """Retire les tracks/vias d'escape laissés sur les pads NC.

    Le routeur échappe les pads NC (rendus obstacles par :func:`assign_nc_nets`
    via des nets ``CIRQIX_NC_*``) avec des segments/vias qui ne transportent
    **aucun signal**. Une fois :func:`strip_nc_nets` passé, ces stubs deviennent
    des pistes ``<no net>`` qui court-circuitent les pads NC (shorting_items +
    solder_mask_bridge : 20 + 20 → 0 mesuré sur STM32 LQFP-48 en iso-prod).
    On les retire **avant** ``strip_nc_nets``, tant qu'ils sont encore
    étiquetés ``CIRQIX_NC_*``.

    **Détection par code** : KiCad sérialise les nets des segments/vias par
    **code seul** ``(net N)``, jamais par nom. On déduit donc les codes des
    nets NC depuis leurs déclarations ``(net N "CIRQIX_NC_N")`` puis on retire
    tout bloc segment/via référençant l'un de ces codes.

    Board-agnostique : tout pad NC générera un stub ``CIRQIX_NC_*``, donc la
    transformation s'applique à n'importe quelle carte. Scan à parenthèses
    équilibrées, insensible aux parenthèses dans les chaînes quotées (même
    technique que :func:`_strip_zone_blocks`).

    Args:
        text: Contenu sérialisé du ``.kicad_pcb`` routé (avant strip_nc_nets).

    Returns:
        ``(text_nettoyé, nombre_de_stubs_retirés)``. No-op → ``(text, 0)``.
    """
    nc_codes = set(re.findall(
        r'\(net\s+(\d+)\s+"' + re.escape(_NC_NET_PREFIX) + r'\d+"\)', text))
    if not nc_codes:
        return text, 0

    out: list[str] = []
    removed = 0
    i = 0
    while True:
        m = _SEG_VIA_BLOCK_RE.search(text, i)
        if not m:
            out.append(text[i:])
            return "".join(out), removed
        paren = text.index("(", m.start())
        depth, in_str = 0, False
        j = paren
        while j < len(text):
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
        if depth != 0:
            # .kicad_pcb malformé — on garde le bloc intact et on rend la main.
            out.append(text[i:])
            return "".join(out), removed
        block = text[paren:j + 1]
        # Codes nets référencés par ce segment/via (format KiCad code-only ou nommé).
        block_codes = set(re.findall(r'\(net\s+(\d+)', block))
        if block_codes & nc_codes:
            # Stub d'escape NC : on retire le \n+indentation qui précèdent aussi.
            out.append(text[i:m.start()])
            removed += 1
        else:
            out.append(text[i:j + 1])
        i = j + 1


def _solid_connect_zones(text: str) -> str:
    """Zones en connexion solid (``connect_pads yes``) — idempotent.

    Les zones du flux Cirqix sont toutes des plans power (GND posé par
    ``_ensure_gnd_both_planes``, rails coulés par kct en mode plans) : le
    frein thermique par défaut y est infaisable entre les pistes d'escape
    fine-pitch (starved_thermal + pads orphelins mesurés runs 7/9 — éliminés
    par la connexion solid). ``ZoneConfig``/``zone_node`` (kicad-tools)
    n'exposent pas le mode de connexion → transformation texte du bloc
    ``(connect_pads …)`` sérialisé.
    """
    return text.replace("(connect_pads (clearance", "(connect_pads yes (clearance")


_ZONE_BLOCK_RE = re.compile(r"\n\s*\(zone[\s\n]")


def _fill_zones(pcb_bytes: bytes) -> bytes:
    """Remplit les zones du board (``kct zones fill``) avant livraison.

    ``ZoneGenerator.add_zone`` (cf. :func:`_ensure_gnd_both_planes`) déclare le
    CONTOUR d'une zone mais ne la remplit pas : le board sortait avec
    ``filled_polygon`` absent, c'est-à-dire des plans sans le moindre cuivre.

    Deux conséquences mesurées le 2026-07-30 sur le board STM32 :

    - **DRC** — 12 des 17 « connexions manquantes » GND étaient un pur artefact
      du non-remplissage : passer ``kicad-cli pcb drc --refill-zones`` les fait
      disparaître (17 → 5). Le juge remplissait pour lui-même ce que le board
      livré ne contenait pas.
    - **Fabrication** — bien plus grave : une zone non remplie ne produit AUCUN
      cuivre à l'export Gerber. La carte livrée n'avait pas de plan de masse.

    Le remplissage est donc persisté ici, dans le board rendu. Best-effort : un
    échec laisse le board tel quel plutôt que de perdre le routage.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.kicad_pcb"
        dst = Path(tmp) / "filled.kicad_pcb"
        src.write_bytes(pcb_bytes)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "kicad_tools.cli", "zones", "fill",
                 str(src), "-o", str(dst)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300, check=False, env=_kct_env(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("zones fill: échec (%s) — board livré non rempli", exc)
            return pcb_bytes
        if proc.returncode != 0 or not dst.exists():
            logger.warning(
                "zones fill: rc=%s — board livré NON REMPLI (plans sans cuivre "
                "à l'export Gerber) : %s",
                proc.returncode, (proc.stderr or proc.stdout or "")[-200:])
            return pcb_bytes
        return dst.read_bytes()


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


# Protections escape fine-pitch (Brique 2) — activées SEULEMENT si le board
# contient un boîtier dense (≥16 pads). Mesuré 2026-07-22 : sans elles, le
# routeur pose des vias in-pad qui frôlent les pads voisins d'un autre net sur
# QFP/QFN fin → courts réels (kicad-cli). Avec elles + canal d'escape dégagé au
# placement (Brique 1) : routage propre (0 court). Elles coûtent de la complétion
# si appliquées sans nécessité → gating strict.
#   --strict-in-pad-clearance (#3033/#3062) : refuse un via in-pad qui clipperait
#       un pad voisin d'un net étranger.
#   --micro-via-in-pad-fallback (#3118) : réessaie avec un micro-via plus petit.
#   --fine-pitch-clearance : clearance d'escape entre broches < 0,8 mm de pas.
_FINE_PITCH_CLEARANCE_MM: str = "0.08"


def _has_dense_footprint(text: str) -> bool:
    """True si le board contient un boîtier dense (≥ seuil pads) → déclenche les
    protections escape fine-pitch. Seuil partagé avec le placement
    (``tools.placement._DENSE_PAD_COUNT`` = ``_dense_package_count`` kicad-tools).

    Comptage par bloc footprint (texte) — pas de chargement PCB (``route_kct``
    est appelé en boucle par le reasoner). Les segments/vias/zones en fin de
    fichier ne portent pas de ``(pad `` : le comptage reste fidèle.
    """
    from tools.placement import _DENSE_PAD_COUNT
    for block in text.split("(footprint")[1:]:
        if block.count("(pad ") >= _DENSE_PAD_COUNT:
            return True
    return False


@lru_cache(maxsize=8)
def _route_supports(flag: str) -> bool:
    """``kct route`` accepte-t-il ce flag dans la révision installée ?

    L'image Docker installe kicad-tools depuis ``/opt/kicad-tools``, qui peut
    être ANTÉRIEUR au gitlink du dépôt : mesuré le 2026-07-30, l'image
    ``cirqix-kicad:latest`` ignorait ``--stitch-power-planes`` (rc=2, usage
    error) alors que le sous-module épinglé le définit. Passer un flag inconnu
    fait échouer tout le routage — on sonde donc plutôt que de supposer.

    Sondage unique par flag (``lru_cache``) ; en cas d'échec du sondage on
    répond False, le routage restant fonctionnel sans l'option.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "kicad_tools.cli", "route", "--help"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, check=False, env=_kct_env(),
        )
        return flag in (proc.stdout or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("route: sondage du flag %s impossible (%s)", flag, exc)
        return False


def _build_route_cmd(src: Path, dst: Path, timeout_s: int,
                     fine_pitch: bool = False,
                     clearance_mm: str | None = None,
                     min_completion: str | None = None) -> list[str]:
    """Construit la ligne de commande ``kct route`` (extrait pour testabilité).

    Base : ``negotiated`` + ``--auto-layers`` + ``--min-completion 1.0`` +
    auto-fix + auto-mfr-tier + seed déterministe. Sur un board **fine-pitch**
    (``fine_pitch=True``) : ajoute les protections escape ET force
    ``--starting-layers 4`` — ``--strict-in-pad-clearance`` désactivant
    l'escalade ``--auto-layers`` (nets refusés proprement ≠ « échec »), on
    démarre à 4 couches (un LQFP dense requiert de toute façon 4 couches ; il
    n'est jamais 2 couches DRC-clean).
    """
    cmd = [
        sys.executable, "-m", "kicad_tools.cli", "route",
        str(src), "-o", str(dst),
        "--strategy", "negotiated",
        "--auto-layers",
        "--min-completion", min_completion or _MIN_COMPLETION,
        "--auto-fix",
        "--clearance", clearance_mm or _CLEARANCE_FALLBACK_MM,
    ]
    if fine_pitch:
        cmd += [
            "--fine-pitch-clearance", _FINE_PITCH_CLEARANCE_MM,
            "--strict-in-pad-clearance",
            "--micro-via-in-pad-fallback",
            "--starting-layers", "4",
        ]
    # Couture des plans : sans elle, la zone de masse n'est reliée à AUCUN pad.
    # Mesuré le 2026-07-30 sur le board STM32 rerouté à 100 % — les 17 connexions
    # manquantes restantes étaient TOUTES sur GND, la zone étant présente mais
    # orpheline. Le flag pose les vias pad → plan. Conditionnel : absent des
    # révisions kicad-tools antérieures, où il ferait échouer le routage (rc=2).
    if _route_supports("--stitch-power-planes"):
        cmd.append("--stitch-power-planes")
    cmd += [
        "--auto-mfr-tier",
        "--mfr-tier-ladder", _MFR_TIER_LADDER,
        "--seed", "42",
        "--timeout", str(timeout_s),
    ]
    return cmd


# Seuil permissif de la passe de secours : on ne cherche plus à atteindre une
# cible, seulement à ce que `kct route` accepte d'ÉCRIRE son meilleur résultat.
_MIN_COMPLETION_RESCUE: str = "0.0"

# Le routeur n'a produit un résultat partiel que s'il l'annonce explicitement.
# Sans cette marque, on ne tente aucune récupération : mieux vaut lever que
# rendre un board dont on ne sait rien.
_PARTIAL_RE = re.compile(r"PARTIAL:\s*Best result\s+\d+%|Nets routed:\s*\d+\s*/\s*\d+")


# Refus explicite du routeur : la grille autorisee par le budget memoire est
# plus grossiere que clearance/2, donc router produirait des courts.
_GRID_REFUS_RE = re.compile(
    r"Auto-grid selected [\d.]+mm > clearance/2|"
    r"router's own safety rule rejects this grid")


def _grid_too_coarse_for_clearance(stderr: str | None) -> bool:
    """Le routeur a-t-il refuse de router faute de grille assez fine ?"""
    return bool(_GRID_REFUS_RE.search(stderr or ""))


def convert_corners_45_drc_aware(pcb_bytes: bytes, tier: str, layers: int) -> bytes:
    """Convertit les coins à 90° en 45°, en annulant net par net si le DRC empire.

    Un routage professionnel n'a pas de coin droit : les pistes tournent à 45°.
    kicad-tools sait le faire (``convert_45_corners``), mais **Patch Cirqix #7**
    a dû neutraliser cette passe : en déplaçant la géométrie, elle taille des
    diagonales dans le cuivre des pads voisins, et le collision checker par
    cellules ne voit pas ces coupes continues (issue upstream #750). Mesuré :
    27 ``shorting_items`` avec l'optimiseur actif contre 3 sans.

    La réconciliation est native : ``OptimizationConfig(drc_aware=True)`` fait
    tourner un DRC avant/après et **restaure les segments d'origine de tout net
    dont l'optimisation augmente les violations** — avec une garde par catégorie
    (issue #3138) qui refuse aussi l'échange d'une violation contre une autre à
    total constant. Les nets où le 45° passe le gardent ; ceux où il couperait un
    pad restent orthogonaux.

    Générale par construction : la décision est prise **par net**, à partir du
    DRC réel du profil fabricant. Aucun réglage propre à une carte, aucune
    hypothèse sur la topologie. Le placement n'est jamais touché.

    Cette voie passe par l'API Python de kicad-tools plutôt que par le CLI, car
    ``kct route`` n'expose pas ``drc_aware`` — le mode existe, il n'est
    simplement pas câblé côté ligne de commande.

    Best-effort : tout échec rend le board d'entrée inchangé. Une amélioration
    esthétique ne doit jamais faire perdre un routage.
    """
    try:
        from kicad_tools.router import OptimizationConfig, TraceOptimizer
        from kicad_tools.router.optimizer.pcb import optimize_pcb
    except ImportError as exc:
        logger.warning("45°: optimiseur kicad-tools indisponible (%s)", exc)
        return pcb_bytes

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.kicad_pcb"
        dst = Path(tmp) / "out.kicad_pcb"
        src.write_bytes(pcb_bytes)
        try:
            config = OptimizationConfig(
                # Seules les passes utiles aux angles : on ne réactive PAS
                # compress_staircase / pull_tight / eliminate_zigzags, dont
                # Patch #7 a mesuré qu'elles coupent aussi le cuivre.
                merge_collinear=True,
                convert_45_corners=True,
                eliminate_zigzags=False,
                compress_staircase=False,
                pull_tight=False,
                drc_aware=True,
                drc_manufacturer=tier,
                drc_layers=layers,
            )
            if not config.convert_45_corners:
                # KCT_SAFE_OPTIMIZE fuite dans notre propre environnement :
                # la post-conversion serait un no-op silencieux.
                logger.warning(
                    "45°: passe désactivée par KCT_SAFE_OPTIMIZE dans le "
                    "processus courant — conversion ignorée")
                return pcb_bytes
            stats = optimize_pcb(str(src), str(dst),
                                 TraceOptimizer(config).optimize_segments, config)
        except Exception as exc:  # noqa: BLE001
            logger.warning("45°: conversion impossible (%s) — board inchangé", exc)
            return pcb_bytes

        if not dst.exists():
            return pcb_bytes
        avant = getattr(stats, "drc_errors_before", None)
        apres = getattr(stats, "drc_errors_after", None)
        logger.info(
            "45°: coins convertis (%s → %s coins), DRC %s → %s",
            getattr(stats, "corners_before", "?"), getattr(stats, "corners_after", "?"),
            avant, apres)
        return dst.read_bytes()


def _has_partial_result(stdout: str | None) -> bool:
    """Le routeur annonce-t-il un résultat partiel exploitable ?"""
    return bool(_PARTIAL_RE.search(stdout or ""))


def _run_kct_route(src: Path, dst: Path, timeout_s: int,
                   fine_pitch: bool = False,
                   min_completion: str | None = None,
                   clearance_mm: str | None = None,
                   ) -> subprocess.CompletedProcess[str]:
    """Lance ``kct route`` (cf. ``_build_route_cmd``) ; ``fine_pitch`` active les
    protections escape + départ 4 couches sur les boards à boîtier dense.

    La clearance vient du profil fabricant (`_profile_clearance_mm`), pas d'une
    constante : c'est ce qui garantit que le routeur et le juge DRC appliquent
    le même règlement.
    """
    try:
        pcb_text = src.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pcb_text = ""  # le comptage de couches retombe sur son défaut (2)
    clearance = clearance_mm or _profile_clearance_mm(fine_pitch, pcb_text)
    cmd = _build_route_cmd(src, dst, timeout_s, fine_pitch, clearance_mm=clearance,
                           min_completion=min_completion)
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
        # Détection fine-pitch AVANT toute transformation (rename/assign ne
        # touchent pas au nombre de pads) → active les protections escape.
        fine_pitch = _has_dense_footprint(src_text)
        if fine_pitch:
            logger.info("kct route: boîtier dense détecté → protections escape "
                        "fine-pitch + départ 4 couches")
        power_rename = _power_rename_map(src_text) if vcc_as_traces else {}
        if power_rename:
            logger.info("kct route: rails power routés en pistes — %s",
                        ", ".join(sorted(power_rename)))
            src_text = _rename_nets(src_text, power_rename)
        # Pads NC → obstacles réels le temps du routage (cf. _NC_NET_PREFIX).
        src_text, nc_count = assign_nc_nets(src_text)
        if nc_count:
            logger.info("kct route: %d pad(s) NC convertis en obstacles stricts",
                        nc_count)
        src.write_text(src_text, encoding="utf-8")

        result = _run_kct_route(src, dst, timeout_s, fine_pitch=fine_pitch)

        if not dst.exists() and _grid_too_coarse_for_clearance(result.stderr):
            # Le routeur REFUSE de router : la grille que le budget mémoire
            # autorise (0,1 mm) est plus grossière que `clearance / 2`, et il
            # préfère ne rien produire plutôt que des courts — « An unrouted net
            # is strictly safer than a short ». Sa propre règle, qu'on partage.
            #
            # C'est l'effet de bord de la clearance dérivée du profil fabricant
            # (0,1116 mm → grille requise 0,0558 mm) : elle débloque
            # l'échappement des boîtiers fine-pitch, mais sur un board dense
            # elle dépasse le budget de cellules. `max_cells` n'est réglable ni
            # en CLI ni par variable d'environnement (paramètre interne de
            # `router/io.py`), et `--force` est exclu par principe.
            #
            # On dégrade donc vers la clearance de repli — la valeur validée de
            # juillet — plutôt que de ne rien rendre. La finesse reste acquise
            # sur les boards où la grille la supporte.
            logger.warning(
                "kct route: grille trop grossière pour la clearance %s mm "
                "(budget mémoire) — nouvelle tentative à %s mm",
                _profile_clearance_mm(fine_pitch, src_text),
                _CLEARANCE_FALLBACK_MM)
            result = _run_kct_route(src, dst, timeout_s, fine_pitch=fine_pitch,
                                    clearance_mm=_CLEARANCE_FALLBACK_MM)

        if not dst.exists() and _has_partial_result(result.stdout):
            # `kct route` n'écrit AUCUN fichier quand aucun tier n'atteint
            # `--min-completion` : l'escalade rend un code ≠ 0 et le meilleur
            # board est perdu. Mesuré le 2026-07-31 sur un placement pourtant
            # sain — 44 % de complétion, 4 nets sur 9, et rien en sortie.
            #
            # Conséquence : le reasoner (agent ⑥b), dont TOUT l'objet est de
            # reprendre un routage incomplet, ne reçoit jamais le triplet
            # (board, pourcentage, analyse) qu'il attend. Il est du code mort
            # en production exactement dans le cas pour lequel il existe.
            #
            # On redemande donc explicitement le meilleur résultat, avec un
            # seuil permissif. Le pourcentage rendu reste le RÉEL, lu dans le
            # stdout de la passe d'origine.
            logger.warning(
                "kct route: aucun tier n'a atteint %s de complétion — "
                "récupération du meilleur board partiel pour le reasoner",
                _MIN_COMPLETION)
            secours = _run_kct_route(src, dst, timeout_s, fine_pitch=fine_pitch,
                                     min_completion=_MIN_COMPLETION_RESCUE)
            if dst.exists():
                pct_reel = parse_routed_pct(result.stdout)
                logger.warning(
                    "kct route: board partiel récupéré à %d%% (le routage "
                    "complet a échoué) — transmis au sauvetage", pct_reel)
                return dst.read_bytes(), pct_reel, extract_failure_analysis(
                    result.stdout) or extract_failure_analysis(secours.stdout)

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
                {new: old for old, new in power_rename.items()},
            )
            restored = _strip_zone_blocks(restored)
            routed = _ensure_gnd_both_planes(restored.encode("utf-8"))

        # Post-traitements communs aux deux modes : retrait des stubs
        # d'escape NC (courts/solder-mask sur pads NC), des nets NC
        # temporaires, et zones en connexion solid (chantier DRC-clean).
        routed_text = routed.decode("utf-8", errors="replace")
        routed_text, stub_n = strip_nc_escape_stubs(routed_text)
        if stub_n:
            logger.info(
                "kct route: %d stub(s) d'escape NC retiré(s) → élimine "
                "courts + solder_mask_bridge sur pads NC", stub_n)
        post = strip_nc_nets(routed_text)
        # Angles pro : les coins droits deviennent des 45°, net par net, avec
        # annulation dès qu'une violation apparaît (cf. la docstring de
        # `convert_corners_45_drc_aware`). AVANT le remplissage des zones, dont
        # les polygones seraient invalidés par toute réécriture de piste.
        from tools.drc import copper_layer_count

        tier_45 = parse_retained_tier(result.stdout) or _MFR_TIER_LADDER.split(",")[0]
        post = convert_corners_45_drc_aware(
            post.encode("utf-8"), tier_45.strip(), copper_layer_count(post),
        ).decode("utf-8", errors="replace")
        # Le remplissage vient EN DERNIER : toute réécriture de zone postérieure
        # (strip/regénération) invaliderait les polygones remplis.
        routed = _fill_zones(_solid_connect_zones(post).encode("utf-8"))

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

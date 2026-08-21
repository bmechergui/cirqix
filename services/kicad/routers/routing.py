"""FastAPI router for auto-routing.

Two endpoints:

- ``POST /route``         — path-based, kept for backwards compatibility.
- ``POST /route/auto``    — base64 I/O. Pipeline:
    1. Freerouting (Java) — preferred, handles all complexity.
    2. kicad-tools Python router — fallback when Java absent, ≤ 10 nets, 60s budget.
    3. skipped=True — when both are unavailable or board is too complex.

Pipeline Freerouting: ``.kicad_pcb`` → Specctra DSN → Freerouting (Java) → SES → ``.kicad_pcb``.
Pipeline kicad-tools: ``.kicad_pcb`` → Python A* negotiated router → ``.kicad_pcb``.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from tools import kct_route
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["routing"])

# 2-layer simple boards usually < 90s, 4-layer ~300s, 8-layer ~600s
_DEFAULT_TIMEOUT_S: int = 300
# Borne HAUTE acceptée par la route. Alignée sur `_ROUTE_TIMEOUT_S` de
# tools/kct_route.py : la frontière HTTP ne doit jamais être plus serrée que le
# budget que le routeur sait consommer, ni que celui que le client calcule
# (`routingSearchBudgetS` → jusqu'à 3000 s sur 8 couches).
#
# ⚠️ Elle valait 900 s alors que les deux extrémités avaient été portées à
# 1800-3600 s : `POST /route/auto` répondait **422 Unprocessable Entity** et le
# routage n'avait pas lieu du tout. Relever un budget à ses deux bouts sans la
# validation du milieu ne rallonge rien — ça coupe. Constaté sur un run réel le
# 2026-08-20. Garde : tests/test_route_budget.py.
_MAX_TIMEOUT_S: int = 3600
_PCBNEW_RUNNER_TIMEOUT_S: int = 60
_PCBNEW_RUNNER = Path(__file__).resolve().parent.parent / "tools" / "routing_pcbnew_runner.py"


# ----------------------------------------------------------------------------
# Pydantic models
# ----------------------------------------------------------------------------

_KICAD_TOOLS_MAX_NETS: int = 30
_KICAD_TOOLS_MAX_COMPS: int = 30
# Budget du routeur kicad-tools (passé à route_kct). 300s = budget « 4 couches » :
# route_kct escalade jusqu'à 4 couches (--auto-layers) en visant 100%
# (--min-completion 1.0) → la tentative 4L a besoin de temps. Plafond, pas
# attente fixe (kct rend la main dès 100%). Aligné sur _DEFAULT_TIMEOUT_S.
_PYTHON_ROUTER_TIMEOUT_S: int = 300

# En dessous de ce % de complétion, préférer Freerouting (si dispo) au résultat
# kicad-tools. (route_kct vise lui-même 100% via --min-completion 1.0 ; ce seuil
# reste le garde-fou d'acceptation côté routeur.)
_MIN_ROUTED_PCT: int = 95


class RouteAutoRequest(BaseModel):
    kicad_pcb_b64: str = Field(..., description=".kicad_pcb encoded as base64")
    layers: int = Field(default=2, description="Copper layer count (2, 4, or 8)")
    timeout_s: int = Field(default=_DEFAULT_TIMEOUT_S, ge=30, le=_MAX_TIMEOUT_S)

    def model_post_init(self, _context: Any) -> None:
        if self.layers not in (2, 4, 8):
            raise ValueError("layers must be 2, 4, or 8")


class RouteAutoResponse(BaseModel):
    kicad_pcb_b64: Optional[str] = None
    routed_percent: int = 0
    layers: int
    via_count: int = 0
    track_length_mm: float = 0.0
    skipped: bool = False
    warning: Optional[str] = None


# ----------------------------------------------------------------------------
# Internal helpers (mocked in tests)
# ----------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Client de l'API Freerouting (Niveau 2)
# ---------------------------------------------------------------------------
#
# ⚠️ Le préfixe est `/v1`, PAS `/api/v1`. Le client sondait `/api/v1/system/status`
# — un chemin que Freerouting v2.1.0 ne sert pas — donc la sonde renvoyait
# toujours `None` et le Niveau 2 n'a JAMAIS été emprunté. Chaque routage repartait
# sur le Niveau 3, un `java -jar` complet avec démarrage de JVM, pendant que la
# JVM persistante (~400 Mo) attendait pour rien.
#
# Contrat mesuré le 2026-08-20 contre l'instance de production :
#   GET  /api/v1/system/status            -> 404      | GET /v1/system/status -> 200
#   POST /v1/sessions/create sans en-têtes -> 500      | avec en-têtes         -> 200
#   POST /v1/jobs/{id}/input multipart     -> 415      | {"data": <b64>}       -> 200
#   POST /v1/jobs/{id}/start               -> 405      | PUT                   -> 200
#   états sérialisés en MAJUSCULES ("QUEUED", "COMPLETED")
#
# Quatre erreurs indépendantes, chacune suffisante seule.
# Garde : tests/test_freerouting_api_contract.py.

_FREEROUTING_API_PREFIX = "/v1"
# Identité serveur-à-serveur. Le serveur EXIGE une identité, même en local
# (« Freerouting-Profile-ID or Freerouting-Profile-Email ... must be set »).
# Ce n'est pas un secret : l'API n'écoute que sur la boucle locale.
_FREEROUTING_PROFILE_ID = os.environ.get(
    "FREEROUTING_PROFILE_ID", "00000000-0000-4000-8000-000000000001"
)
_FREEROUTING_PROFILE_EMAIL = os.environ.get(
    "FREEROUTING_PROFILE_EMAIL", "service@cirqix.local"
)


def _freerouting_api_base() -> str:
    return os.environ.get("FREEROUTING_API_URL", "http://127.0.0.1:37864")


def _freerouting_api_headers() -> dict[str, str]:
    """En-têtes d'identité, obligatoires sur CHAQUE appel."""
    return {
        "Accept": "application/json",
        "Freerouting-Profile-ID": _FREEROUTING_PROFILE_ID,
        "Freerouting-Profile-Email": _FREEROUTING_PROFILE_EMAIL,
        "Freerouting-Environment-Host": "cirqix/1.0",
    }


def _freerouting_input_payload(dsn_bytes: bytes) -> dict[str, str]:
    """Corps d'envoi du DSN — un `BoardFilePayload`, pas un multipart.

    Le multipart renvoie 415 Unsupported Media Type.
    """
    return {
        "filename": "board.dsn",
        "data": base64.b64encode(dsn_bytes).decode("ascii"),
    }


def _freerouting_job_done(state: str) -> bool:
    """Le serveur sérialise l'enum en MAJUSCULES.

    L'ancien client comparait à `"completed"` : la boucle de sondage ne sortait
    donc jamais et finissait en timeout sur un job pourtant terminé.
    """
    return str(state).upper() == "COMPLETED"


def _freerouting_job_failed(state: str) -> bool:
    return str(state).upper() in ("FAILED", "CANCELLED", "INVALID")


def _find_freerouting_api() -> Optional[str]:
    """Return Freerouting API base URL if the server is reachable, else None."""
    import urllib.request

    base = _freerouting_api_base()
    try:
        req = urllib.request.Request(
            f"{base}{_FREEROUTING_API_PREFIX}/system/status",
            headers=_freerouting_api_headers(),
        )
        urllib.request.urlopen(req, timeout=2)
        return base
    except Exception:
        return None


def _route_with_freerouting_api(
    pcb_bytes: bytes,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> bytes:
    """Route via Freerouting persistent REST API server (1 JVM for all users).

    Flow: export DSN → POST session → POST job → upload DSN (JSON) → PUT start →
          poll status → GET output (SES) → pcbnew Specctra import.
    """
    import json
    import time
    import urllib.request

    base = _freerouting_api_base()
    pre = _FREEROUTING_API_PREFIX

    def _api(method: str, path: str, payload: Optional[dict] = None) -> dict:
        headers = _freerouting_api_headers()
        body: Optional[bytes] = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{base}{path}", data=body, method=method, headers=headers
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else {}

    with tempfile.TemporaryDirectory() as tmp:
        dsn_path = Path(tmp) / "board.dsn"
        ses_path = Path(tmp) / "board.ses"

        _export_specctra(pcb_bytes, dsn_path)

        session = _api("POST", f"{pre}/sessions/create", {})
        session_id = session["id"]

        job = _api("POST", f"{pre}/jobs/enqueue", {"session_id": session_id})
        job_id = job["id"]

        _api(
            "POST",
            f"{pre}/jobs/{job_id}/input",
            _freerouting_input_payload(dsn_path.read_bytes()),
        )

        _api("PUT", f"{pre}/jobs/{job_id}/start", {})

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status = _api("GET", f"{pre}/jobs/{job_id}")
            state = status.get("state", "")
            if _freerouting_job_done(state):
                break
            if _freerouting_job_failed(state):
                raise RuntimeError(f"Freerouting API job {state}")
            time.sleep(2)
        else:
            raise RuntimeError("Freerouting API timeout")

        output = _api("GET", f"{pre}/jobs/{job_id}/output")
        # `data` est le champ du `BoardFilePayload` ; les deux autres noms sont
        # conservés en repli, sans preuve qu'ils existent — un output vide est
        # rattrapé plus bas par la garde netlist.
        ses_b64 = output.get("data") or output.get("output_file") or output.get("ses") or ""
        if not ses_b64:
            raise RuntimeError("Freerouting API returned an empty output")
        ses_path.write_bytes(base64.b64decode(ses_b64))

        return _specctra_roundtrip(pcb_bytes, ses_path)


def _find_freerouting() -> Optional[tuple[str, str]]:
    """Locate (java, freerouting.jar) or return None when either is absent."""
    java = shutil.which("java")
    if not java:
        return None
    candidates = [
        os.environ.get("FREEROUTING_JAR"),
        "/opt/freerouting/freerouting.jar",
        "/usr/local/share/freerouting/freerouting.jar",
        str(Path(__file__).parent.parent / "freerouting" / "freerouting.jar"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return (java, c)
    return None


def _run_freerouting(
    paths: tuple[str, str], dsn: Path, ses: Path, timeout_s: int
) -> None:
    """Invoke Freerouting CLI. Raises on non-zero exit or timeout."""
    java, jar = paths
    cmd = [
        java, "-jar", jar,
        "-de", str(dsn),
        "-do", str(ses),
        "-mp", "100",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout_s, check=False,
    )
    if result.returncode != 0 and not ses.exists():
        raise RuntimeError(f"Freerouting exit {result.returncode}")


def _specctra_roundtrip(pcb_bytes: bytes, ses_path: Path) -> bytes:
    """Apply a SES in a bounded child process; never call pcbnew in FastAPI."""
    with tempfile.TemporaryDirectory() as tmp:
        in_pcb = Path(tmp) / "in.kicad_pcb"
        out_pcb = Path(tmp) / "out.kicad_pcb"
        in_pcb.write_bytes(pcb_bytes)
        _run_pcbnew_operation({
            "operation": "specctra_roundtrip",
            "pcb": str(in_pcb),
            "ses": str(ses_path),
            "output": str(out_pcb),
        })
        if not out_pcb.is_file():
            raise RuntimeError("pcbnew Specctra child produced no PCB output")
        return out_pcb.read_bytes()


def _count_routable_nets(pcb_bytes: bytes) -> int:
    """Nets qui demandent réellement un routage (≥ 2 pads attribués).

    Le seuil dépend du writer, parce que la forme numérotée porte une
    DÉCLARATION en tête du fichier en plus des pads, et la forme nommée non :

        (net 3 "GND")  → 1 déclaration + 1 par pad  → routable si ≥ 3
        (net "GND")    → 1 par pad, sans déclaration → routable si ≥ 2

    Les nets à un seul pad (broches non connectées, `Net-(U1-X)`) sont exclus
    dans les deux cas : il n'y a rien à router.
    """
    from collections import Counter

    text = pcb_bytes.decode("utf-8", errors="replace")

    numerotes = Counter(nom for _, nom in _NET_NUMBERED_RE.findall(text) if nom)
    if numerotes:
        return sum(1 for c in numerotes.values() if c >= 3)

    nommes = Counter(nom for nom in _NET_NAMED_RE.findall(text) if nom)
    return sum(1 for c in nommes.values() if c >= 2)


def _count_footprints(pcb_bytes: bytes) -> int:
    """Count footprint blocks in a .kicad_pcb S-expression."""
    text = pcb_bytes.decode("utf-8", errors="replace")
    return len(re.findall(r'\(footprint\s+"', text))


def _route_with_kicad_tools(pcb_bytes: bytes, timeout_s: int) -> tuple[bytes, int]:
    """Route via the official ``kct route`` CLI — délégué à tools/kct_route.

    Pas de sauvetage ici : si routed_pct < 100, l'orchestrateur appelle
    explicitement l'agent reasoner (POST /reason/auto) — étape visible UI.

    ⚠️ `timeout_s` vient de la REQUÊTE. Cette fonction passait
    `_PYTHON_ROUTER_TIMEOUT_S` (300 s) en ignorant ce que le client demandait :
    le chemin PRINCIPAL de routage était donc plafonné à 300 s quoi qu'il
    arrive, et seul le repli Freerouting honorait la demande. C'était le vrai
    plafond du routage — celui qui rendait un routage de 15-20 min inatteignable
    par l'API, quelles que soient les autres constantes relevées.
    Garde : tests/test_route_budget.py.
    """
    routed, routed_pct, _analysis = kct_route.route_kct(pcb_bytes, timeout_s=timeout_s)
    return routed, routed_pct


def _run_pcbnew_operation(payload: dict[str, str]) -> None:
    """Run one pcbnew operation outside uvicorn's worker/thread process.

    pcbnew owns non-thread-safe C++ global state.  A lock would only serialize
    threads inside one uvicorn worker and would not isolate crashes; a bounded
    child process contains both concurrency and native failures.
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(_PCBNEW_RUNNER), json.dumps(payload)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PCBNEW_RUNNER_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"pcbnew child timed out after {_PCBNEW_RUNNER_TIMEOUT_S}s"
        ) from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        raise RuntimeError(f"pcbnew child exit {proc.returncode}: {detail}")


def _export_specctra(pcb_bytes: bytes, dsn_path: Path) -> None:
    """Export a PCB to Specctra DSN in a bounded pcbnew child process.

    All existing tracks are removed before export so Freerouting starts from
    scratch — without stale TS-generated traces that pointed to pre-placement
    component positions.
    """
    with tempfile.TemporaryDirectory() as tmp:
        in_pcb = Path(tmp) / "in.kicad_pcb"
        in_pcb.write_bytes(pcb_bytes)
        _run_pcbnew_operation({
            "operation": "export_specctra",
            "pcb": str(in_pcb),
            "dsn": str(dsn_path),
        })
    if not dsn_path.is_file():
        raise RuntimeError("pcbnew Specctra child produced no DSN output")


def _measure_routing(pcb_bytes: bytes) -> tuple[int, int]:
    """Return ``(routable nets, unrouted nets)`` from real PCB connectivity.

    The total deliberately reuses the repository's canonical S-expression rule
    (one declaration plus at least two pad assignments).  pcbnew only determines
    which of those nets still have pads in separate copper components.

    Fail closed: if the child cannot prove connectivity, raising is safer than
    turning a completed Freerouting job or a produced SES into a fabricated 100%.
    """
    total_nets = _count_routable_nets(pcb_bytes)
    with tempfile.TemporaryDirectory() as tmp:
        in_pcb = Path(tmp) / "in.kicad_pcb"
        result_path = Path(tmp) / "connectivity.json"
        in_pcb.write_bytes(pcb_bytes)
        _run_pcbnew_operation({
            "operation": "measure_connectivity",
            "pcb": str(in_pcb),
            "result": str(result_path),
        })
        if not result_path.is_file():
            raise RuntimeError("pcbnew connectivity child produced no result")
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            unrouted_nets = result["unrouted_nets"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RuntimeError("invalid pcbnew connectivity result") from exc

    if not isinstance(unrouted_nets, int) or isinstance(unrouted_nets, bool):
        raise RuntimeError("invalid pcbnew unrouted-nets count")
    if unrouted_nets < 0 or unrouted_nets > total_nets:
        raise RuntimeError(
            f"impossible pcbnew connectivity result: {unrouted_nets}/{total_nets}"
        )
    return total_nets, unrouted_nets


def _measured_routed_percent(
    pcb_bytes: bytes,
    expected_routable_nets: int,
) -> int:
    total_nets, unrouted_nets = _measure_routing(pcb_bytes)
    # A router must preserve the routing problem, not merely solve whatever
    # subset survived its import/export.  Recomputing the denominator only from
    # the output would let a board that lost N-1 nets claim 100% on the last one.
    if total_nets != expected_routable_nets:
        raise RuntimeError(
            "routable net count changed during routing: "
            f"{expected_routable_nets} in, {total_nets} out"
        )
    if total_nets == 0:
        # Un denominateur nul n'est pas une victoire. On renvoyait 100 ici : un
        # board sans le moindre net routable etait annonce parfaitement route.
        # La garde d'entree de `route_auto` refuse deja ces boards ; celle-ci
        # reste en defense en profondeur, pour tout appelant futur.
        raise RuntimeError(
            "cannot measure routing: board has no routable net (0 nets with >=2 pads)"
        )
    return ((total_nets - unrouted_nets) * 100) // total_nets


# ----------------------------------------------------------------------------
# Garde de netlist
# ----------------------------------------------------------------------------

# Un net PORTEUR D'UN NOM s'écrit de DEUX façons selon le writer :
#
#     (net 3 "TRIG_THR")   ← kicad-tools, et KiCad <= 9
#     (net "TRIG_THR")     ← pcbnew de KiCad 10 (`generator_version "10.0"`)
#
# `(net N)` seul, dans un segment, n'est qu'une référence : ne pas le compter,
# sinon un board réduit à des pistes orphelines satisferait la garde.
#
# ⚠️ Seule la première forme était reconnue. Tout board réécrit par pcbnew 10 —
# c'est-à-dire tout board sorti du round-trip Specctra, donc de Freerouting —
# comptait ZÉRO net et se faisait refuser par `_guard_netlist_preserved`.
# Mesuré le 2026-08-20 : entrée 30 occurrences numérotées, sortie 78 nommées,
# et `kicad-cli pcb drc` sur cette sortie répond « Found 0 unconnected items ».
# Le board était valide, routé et connecté : le « 0 en sortie » était un FAUX
# POSITIF du compteur, et il bloquait Freerouting en entier.
# Garde : tests/test_net_counting_kicad10.py.
_NET_NUMBERED_RE = re.compile(r'\(net\s+(\d+)\s+"([^"]*)"\)')
_NET_NAMED_RE = re.compile(r'\(net\s+"([^"]*)"\)')


def _net_decl_count(pcb: bytes) -> int:
    """Nombre d'occurrences de net porteuses d'un nom, quelle que soit la forme."""
    text = pcb.decode("utf-8", errors="replace")
    return len(_NET_NUMBERED_RE.findall(text)) + len(_NET_NAMED_RE.findall(text))


def _niveau4_warning(freerouting_a_echoue: bool, net_count: int) -> str:
    """Message du Niveau 4 — il doit nommer la cause, pas les deux.

    « Freerouting absent » désigne le déploiement ; « Freerouting défaillant »
    désigne ce qu'il a produit. Les confondre fait chercher au mauvais endroit.
    """
    cause = "défaillant" if freerouting_a_echoue else "absent"
    return f"Freerouting {cause} — kicad-tools negotiated utilisé ({net_count} nets)"


def _guard_netlist_preserved(pcb: bytes, input_nets: int, source: str) -> None:
    """Refuse de renvoyer un board qui a perdu TOUTE sa netlist.

    Mesuré le 2026-07-28 (issue #72) : le board entrait au routage avec 30
    déclarations de net et en ressortait avec **zéro** — pistes absentes,
    fichier réécrit par le repli pcbnew — pendant que l'endpoint rapportait
    ``routed_percent=100, skipped=False, warning=None``.

    Les 6 nets ressortaient alors non connectés au DRC, avec ``violations=0`` :
    sans netlist il n'y a plus de règle à violer, donc le board paraît « propre »
    parce qu'il est vide. Un board de 31 Ko sans une seule déclaration de net
    n'est pas un routage réussi.

    On ne contrôle QUE la disparition totale : un routage peut légitimement
    fusionner ou renommer des nets. Et si l'entrée n'avait déjà pas de netlist,
    ce n'est pas au routeur de s'en plaindre — lever ici masquerait la cause amont.
    """
    if input_nets == 0:
        return
    if _net_decl_count(pcb) > 0:
        return
    logger.error(
        "route_auto: %s a renvoyé un board SANS netlist (%d nets en entrée, 0 en sortie) "
        "— refus de le livrer",
        source, input_nets,
    )
    raise HTTPException(
        status_code=500,
        detail=(
            f"routing produced a board without netlist ({source}): "
            f"{input_nets} nets in, 0 out"
        ),
    )


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------

@router.post("/route/auto", response_model=RouteAutoResponse)
def route_auto(req: RouteAutoRequest) -> RouteAutoResponse:
    """
    Auto-route a board.

    Priority:
      1. kicad-tools A* (negotiated) — ≤30 composants ET ≤30 nets, timeout 60s.
      2. Freerouting (Java)          — circuits complexes ou si kicad-tools échoue.
      3. skipped=True                — aucun routeur disponible → GND plane seulement.
    """
    try:
        pcb_bytes = base64.b64decode(req.kicad_pcb_b64)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid base64: {exc}") from exc

    # Netlist d'entrée : sert de référence à la garde anti-board-vide (issue #72).
    input_nets = _net_decl_count(pcb_bytes)
    net_count = _count_routable_nets(pcb_bytes)
    comp_count = _count_footprints(pcb_bytes)
    is_simple = net_count <= _KICAD_TOOLS_MAX_NETS and comp_count <= _KICAD_TOOLS_MAX_COMPS

    logger.info(
        "route_auto: %d routable nets, %d composants — simple=%s",
        net_count, comp_count, is_simple,
    )

    # FAIL CLOSED : zéro net routable n'est pas un routage réussi.
    #
    # `_measured_routed_percent` renvoyait 100 quand `total_nets == 0` — un
    # dénominateur nul traité comme une victoire. Or un board dont AUCUN pad ne
    # porte d'attribution `(net …)` produit exactement ce compte : les nets sont
    # déclarés en tête de fichier, mais rien ne les référence, donc aucun n'a
    # les ≥2 pads qui en feraient un problème de routage.
    #
    # Le générateur TypeScript de repli (`schematic-engine.ts`) fabrique
    # précisément ce board : il déclare les nets, dessine les pistes, et émet
    # les pads SANS `(net …)`. Un board sans la moindre connexion électrique
    # était donc annoncé « routé à 100 % », ce qui désarme d'un coup
    # `shouldRescueRouting` ET `shouldRetryPlacement`, laisse Sonnet enchaîner
    # sur le DRC — propre, puisqu'il n'y a aucune règle à violer sans netlist —
    # puis sur l'export, et rend commandable un board vide.
    #
    # La garde `_guard_netlist_preserved` ne pouvait pas le voir : elle compte
    # les DÉCLARATIONS de net, qui sont bien présentes. Deux mesures
    # différentes, d'où l'angle mort.
    #
    # Refus À L'ENTRÉE plutôt qu'après trois tentatives de routage : le message
    # désigne la cause réelle, en amont, au lieu d'un « tous les routeurs ont
    # échoué » qui enverrait chercher au mauvais endroit.
    #
    # Trouvé le 2026-08-12 par un audit externe (Codex).
    if net_count == 0:
        logger.error(
            "route_auto: aucun net routable (%d déclarations, %d composants) — "
            "les pads ne portent aucune attribution (net …) ; refus de livrer",
            input_nets, comp_count,
        )
        raise HTTPException(
            status_code=422,
            detail=(
                "board has no routable net: "
                f"{input_nets} net declarations, {comp_count} footprints, but no pad "
                "carries a (net ...) assignment. Nothing to route — this is an "
                "upstream PCB generation defect, not a routing failure."
            ),
        )

    # Best kicad-tools partial result so far (reused at Niveau 4 if Freerouting absent)
    kt_partial: Optional[tuple[bytes, int]] = None
    # Freerouting a-t-il TOURNÉ puis échoué, ou n'était-il pas là ?
    #
    # Les deux mènent au Niveau 4, mais ne se soignent pas au même endroit :
    # ABSENT se lit dans le déploiement (binaire ou JVM manquants, problème
    # d'image), DÉFAILLANT se lit dans les données (Freerouting a rendu quelque
    # chose d'inutilisable — un board sans netlist, le 2026-08-20). Un message
    # qui dit « indisponible ou défaillant » envoie chercher au mauvais endroit
    # une fois sur deux.
    freerouting_a_echoue = False

    # --- Niveau 1 : kicad-tools A* (circuits simples ≤30 nets/comps) ---
    if is_simple:
        try:
            new_pcb, routed_pct = _route_with_kicad_tools(pcb_bytes, req.timeout_s)
            logger.info("kicad-tools A*: %d%% routé", routed_pct)
            if routed_pct >= _MIN_ROUTED_PCT:
                _guard_netlist_preserved(new_pcb, input_nets, "kicad-tools")
                return RouteAutoResponse(
                    kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
                    routed_percent=routed_pct,
                    layers=req.layers,
                    skipped=False,
                )
            # Below threshold: keep it, but try Freerouting for a better result.
            kt_partial = (new_pcb, routed_pct)
            logger.info(
                "kicad-tools %d%% < %d%% — tentative Freerouting",
                routed_pct, _MIN_ROUTED_PCT,
            )
        except Exception as exc:
            logger.warning("kicad-tools A* échoué (%s) — Freerouting API", exc)

    # --- Niveau 2 : Freerouting REST API server (1 JVM persistant, meilleure qualité) ---
    api_url = _find_freerouting_api()
    if api_url is not None:
        try:
            new_pcb = _route_with_freerouting_api(pcb_bytes, req.timeout_s)
            _guard_netlist_preserved(new_pcb, input_nets, "freerouting-api")
            routed_pct = _measured_routed_percent(new_pcb, net_count)
            logger.info("Freerouting API: %d%% routé (connectivité mesurée)", routed_pct)
            return RouteAutoResponse(
                kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
                routed_percent=routed_pct,
                layers=req.layers,
                skipped=False,
            )
        except Exception as exc:
            freerouting_a_echoue = True
            logger.warning("Freerouting API échoué (%s) — subprocess fallback", exc)

    # --- Niveau 3 : Freerouting subprocess (fallback si API server absent) ---
    paths = _find_freerouting()
    if paths is not None:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dsn = Path(tmp) / "board.dsn"
                ses = Path(tmp) / "board.ses"
                _export_specctra(pcb_bytes, dsn)
                _run_freerouting(paths, dsn, ses, req.timeout_s)
                new_pcb = _specctra_roundtrip(pcb_bytes, ses)
            _guard_netlist_preserved(new_pcb, input_nets, "freerouting-cli")
            routed_pct = _measured_routed_percent(new_pcb, net_count)
            logger.info("Freerouting: %d%% routé (connectivité mesurée)", routed_pct)
            return RouteAutoResponse(
                kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
                routed_percent=routed_pct,
                layers=req.layers,
                skipped=False,
            )
        except Exception as exc:
            # ⚠️ `HTTPException` COMPRISE — c'est ce que lève la garde netlist.
            #
            # Ce bloc relevait auparavant un 500, ce qui court-circuitait le
            # Niveau 4 : le routage partiel déjà obtenu par kicad-tools
            # (`kt_partial`) était jeté parce qu'un AUTRE routeur avait échoué.
            # Mesuré le 2026-08-20 sur le board STM32 réel : Freerouting rend un
            # board sans netlist (99 nets en entrée, 0 en sortie), la garde le
            # refuse — à raison —, et un routage valide partait avec lui.
            #
            # Refuser le board de Freerouting reste juste ; condamner l'appel ne
            # l'est pas. Freerouting ABSENT et Freerouting DÉFAILLANT conduisent
            # désormais au même repli, comme l'annonçait déjà le commentaire du
            # Niveau 4. Aucun risque de faux succès : le Niveau 4 revalide ce
            # qu'il livre, et le Niveau 5 rend `skipped=True`, traité en
            # fail-fast par `handleRouting`.
            # Garde : tests/test_routing_netlist_guard.py.
            freerouting_a_echoue = True
            logger.warning("Freerouting échoué (%s) — repli kicad-tools", exc)

    # --- Niveau 4 : kicad-tools negotiated sans limite (tous circuits) ---
    # Reuse the Niveau-1 partial when we already have one (avoid a second
    # expensive run). Même algorithme A* negotiated, fallback quand Freerouting
    # absent ou échoue.
    try:
        if kt_partial is not None:
            new_pcb, routed_pct = kt_partial
        else:
            new_pcb, routed_pct = _route_with_kicad_tools(pcb_bytes, req.timeout_s)
        logger.info("kicad-tools A* (no limit): %d%% routé", routed_pct)
        _guard_netlist_preserved(new_pcb, input_nets, "kicad-tools")
        return RouteAutoResponse(
            kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
            routed_percent=routed_pct,
            layers=req.layers,
            skipped=False,
            warning=_niveau4_warning(freerouting_a_echoue, net_count),
        )
    except Exception as exc:
        logger.warning("kicad-tools A* (no limit) échoué (%s) — GND plane", exc)

    # --- Niveau 5 : skipped → GND plane seulement (TypeScript addGroundPlane) ---
    reason = f"Tous les routeurs ont échoué ({net_count} nets, {comp_count} composants)"
    logger.info("Routage ignoré — %s", reason)
    return RouteAutoResponse(
        kicad_pcb_b64=None,
        routed_percent=0,
        layers=req.layers,
        skipped=True,
        warning=reason,
    )

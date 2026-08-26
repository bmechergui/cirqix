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
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
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
        # ⚠️ `layers` est un PLAFOND depuis le 2026-08-21, plus une consigne :
        # le service part de 2 et escalade jusqu a lui. Le modele n acceptait
        # que 2, 4 ou 8 — la grille des PLANS — et rejetait donc un plafond
        # legitime a 12 ou 16, alors que l echelle sait y monter.
        #
        # Un empilage a nombre impair de couches cuivre ne se fabrique pas.
        if self.layers < 2 or self.layers > _MAX_LAYERS or self.layers % 2:
            raise ValueError(
                f"layers must be an even count between 2 and {_MAX_LAYERS}"
            )


class RouteAutoResponse(BaseModel):
    kicad_pcb_b64: Optional[str] = None
    routed_percent: int = 0
    layers: int
    via_count: int = 0
    track_length_mm: float = 0.0
    skipped: bool = False
    warning: Optional[str] = None
    # Quel niveau a REELLEMENT produit le board livre.
    #
    # La cascade a quatre niveaux, et le client TypeScript ecrivait
    # `engine: 'kicad-tools'` EN DUR. Sur un board dense, kicad-tools rend 91 %,
    # sous le seuil, et c'est Freerouting qui livre — l'utilisateur lisait
    # pourtant « Routage kicad-tools ». Une attribution fausse envoie chercher au
    # mauvais endroit ; elle m'a coute plusieurs heures le 2026-08-20.
    #
    # `None` quand aucun board n'est livre : une reponse vide ne s'attribue pas
    # un moteur.
    engine: Optional[str] = None


# ----------------------------------------------------------------------------
# Internal helpers (mocked in tests)
# ----------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Budget de l'APPEL, pas du niveau
# ---------------------------------------------------------------------------
#
# `route_auto` enchaîne jusqu'à quatre routeurs. Chacun recevait `req.timeout_s`
# EN ENTIER, donc un seul appel pouvait valoir plusieurs fois le budget demandé :
# mesuré le 2026-08-20, `timeout_s: 1800` a produit **2547 s** de travail réel.
#
# Le client, lui, calcule son échéance à partir d'UN budget
# (`routingAbortMs = budget + marge`). Il raccroche donc pendant que le service
# travaille encore, et tout le travail déjà fait part à la poubelle. Un budget
# qui ne borne rien n'est pas un budget.
#
# Une échéance UNIQUE est calculée à l'entrée ; chaque niveau reçoit le RESTANT.
# Garde : tests/test_routing_budget_par_appel.py.

# En dessous, on ne lance pas un niveau : un routeur tué en cours ne rend rien,
# alors qu'un niveau plus rapide pourrait encore aboutir.
_MIN_LEVEL_BUDGET_S: int = 30


def _now() -> float:
    """Horloge monotone — indirection pour que les tests puissent la piloter."""
    return time.monotonic()


def _remaining_budget_s(deadline: float, now: Optional[float] = None) -> int:
    """Temps restant avant l'échéance de l'appel, jamais négatif.

    Un budget négatif passé à un sous-processus serait interprété comme
    « pas de limite » par certains outils : plancher à zéro.
    """
    reste = deadline - (_now() if now is None else now)
    return max(0, int(reste))


def _budget_suffisant(budget_s: int) -> bool:
    return budget_s >= _MIN_LEVEL_BUDGET_S


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
        _confier_au_plan(dsn_path)
        if _VIAS_RESERVES:
            dsn_path.write_text(_injecter_wiring(
                dsn_path.read_text(encoding="utf-8", errors="replace"),
                [(v["via_x"], v["via_y"]) for v in _VIAS_RESERVES],
                _NETS_CONFIES_AU_PLAN[0] if _NETS_CONFIES_AU_PLAN else "GND",
            ), encoding="utf-8")

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

    ⚠️ Les nets CONFIÉS AU PLAN sont exclus eux aussi. Mesure du 2026-08-26,
    carte LED passée dans la chaîne complète : 4 segments, zéro pour GND,
    0 connexion manquante et 0 violation DRC — mais `routed_percent` annonçait
    **66 %**, GND comptant comme non routé alors que le plan le relie.

    Ce chiffre n'est pas décoratif : `routed_percent < 100` déclenche le
    reasoner, les re-tirages de placement et le repli. Une carte parfaite
    relançait donc la machine indéfiniment. C'est aussi l'explication des
    « 91 % » du board STM32 — 12 nets routables, GND confié au plan, 11/12.

    Exclure un net que le plan prend en charge n'est pas une indulgence : c'est
    la bonne question posée. Personne n'attend de piste pour ce net-là.
    """
    from collections import Counter

    text = pcb_bytes.decode("utf-8", errors="replace")
    au_plan = set(_NETS_CONFIES_AU_PLAN)

    numerotes = Counter(nom for _, nom in _NET_NUMBERED_RE.findall(text) if nom)
    if numerotes:
        return sum(1 for nom, c in numerotes.items() if c >= 3 and nom not in au_plan)

    nommes = Counter(nom for nom in _NET_NAMED_RE.findall(text) if nom)
    return sum(1 for nom, c in nommes.items() if c >= 2 and nom not in au_plan)


# ---------------------------------------------------------------------------
# Mesures du board routé
# ---------------------------------------------------------------------------
#
# ⚠️ `via_count` et `track_length_mm` n'étaient JAMAIS calculés : les réponses
# sortaient avec les valeurs par défaut du modèle (`0`, `0.0`), que le client
# TypeScript lit et transmet à l'interface. Un board réellement routé — 53
# segments mesurés le 2026-08-20 — s'affichait « 0 via, 0 mm de piste ».
#
# Ce ne sont pas des indicateurs manquants, ce sont des chiffres FAUX présentés
# comme réels. Et un zéro est plausible (un board sans via en a zéro), donc rien
# ne distinguait « mesuré à zéro » de « jamais mesuré ».
# Garde : tests/test_routing_metrics.py.

_VIA_RE = re.compile(r"\(via\s")
_SEGMENT_RE = re.compile(
    r"\(segment\s+\(start\s+(-?[\d.]+)\s+(-?[\d.]+)\)\s+\(end\s+(-?[\d.]+)\s+(-?[\d.]+)\)"
)


def _layers_block(text: str) -> str:
    """Contenu du bloc `(layers …)` en tête de fichier, vide s'il est absent.

    Lecture ligne à ligne plutôt qu'une expression régulière multiligne : la
    fermeture est une ligne réduite à `)`, et une regex mêlant tabulations et
    échappements est fragile à écrire comme à relire.
    """
    dedans = False
    bloc: list[str] = []
    for ligne in text.splitlines():
        if not dedans:
            if ligne.strip().startswith("(layers"):
                dedans = True
            continue
        if ligne.strip() == ")":
            break
        bloc.append(ligne)
    return chr(10).join(bloc)

_COPPER_LAYER_RE = re.compile(r'"[A-Za-z0-9.]+\.Cu"')


# ---------------------------------------------------------------------------
# Escalade de couches
# ---------------------------------------------------------------------------
#
# `tools/pcb.py` genere TOUJOURS deux couches cuivre. Freerouting, lui, route
# sur autant de couches que le DSN en declare — verifie le 2026-08-21 :
#
#     board 2 couches -> DSN ['F.Cu', 'B.Cu']
#     board 4 couches -> DSN ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu']
#
# Il n'a donc aucune limite propre : l'empilage est une DONNEE D'ENTREE. Jusqu'ici
# personne ne la decidait — `req.layers` arrivait au service et n'etait que
# recopie dans la reponse.
#
# Nouveau contrat : `req.layers` est un PLAFOND (celui du plan), pas une consigne.
# On part de 2 et on monte tant que le routage n'est pas complet.
#
# ⚠️ Une carte 4 couches coute sensiblement plus cher a fabriquer qu'une 2
# couches. On monte parce que le routage a ECHOUE, jamais parce que le plan
# l'autorise : le plan plafonne le besoin, il ne le prescrit pas.
#
# Garde : tests/test_stackup_escalade.py.

# Borne absolue de l escalade.
#
# ⚠️ Ce n est PAS un plafond produit — celui-la vient du plan. C est un
# garde-fou : sans lui, un plafond aberrant (plan corrompu, valeur non
# validee) ferait boucler l escalade jusqu a epuisement du budget sur des
# empilages qui ne se fabriquent pas.
_MAX_LAYERS: int = 16


def _layer_ladder(plafond: int) -> list[int]:
    """Paliers d escalade autorises, du plus economique au plus permissif.

    2, 4, 6, 8, 10 ... jusqu au plafond. Pas de maximum code en dur : un
    arret a 8 serait un chiffre arbitraire, les cartes 10, 12 ou 16 couches
    existent (decision du 2026-08-21).

    Un empilage a nombre IMPAIR de couches cuivre ne se fabrique pas : un
    plafond impair est ramene au palier pair inferieur.

    Un plafond hors grille (plan corrompu, valeur inconnue) ne leve pas et
    n ouvre aucun droit : on retombe sur le minimum.
    """
    borne = min(int(plafond), _MAX_LAYERS)
    paliers = [n for n in range(2, borne + 1, 2)]
    return paliers or [2]

def _expand_stackup(pcb_bytes: bytes, n_couches: int) -> bytes:
    """Reecrit le bloc `(layers ...)` pour porter `n_couches` couches cuivre.

    Ne RETIRE jamais de couche : descendre casserait les pistes deja posees sur
    les couches internes. Les couches non cuivre (masque, serigraphie,
    Edge.Cuts) sont preservees telles quelles, et le reste du fichier n'est pas
    touche.

    Numerotation KiCad : F.Cu = 0, internes 1..n, B.Cu = 31.
    """
    text = pcb_bytes.decode("utf-8", errors="replace")
    lignes = text.splitlines(keepends=True)

    debut = fin = None
    for i, ligne in enumerate(lignes):
        if debut is None:
            if ligne.strip().startswith("(layers"):
                debut = i
            continue
        if ligne.strip() == ")":
            fin = i
            break
    if debut is None or fin is None:
        return pcb_bytes

    corps = lignes[debut + 1:fin]
    actuel = len(set(_COPPER_LAYER_RE.findall("".join(corps))))
    if n_couches <= actuel:
        return pcb_bytes

    indent = corps[0][: len(corps[0]) - len(corps[0].lstrip())] if corps else "\t\t"
    autres = [l for l in corps if not _COPPER_LAYER_RE.search(l)]

    cuivre = [f'{indent}(0 "F.Cu" signal)\n']
    for k in range(1, n_couches - 1):
        cuivre.append(f'{indent}({k} "In{k}.Cu" signal)\n')
    cuivre.append(f'{indent}(31 "B.Cu" signal)\n')

    nouvelles = lignes[: debut + 1] + cuivre + autres + lignes[fin:]
    return "".join(nouvelles).encode("utf-8")


# ---------------------------------------------------------------------------
# Plans de masse, coules AVANT le routage
# ---------------------------------------------------------------------------
#
# ⚠️ Le plan arrivait APRES le routage (`addGroundPlane`, cote TypeScript). Le
# routeur n avait donc jamais su qu il existait, et tirait des pistes GND a
# travers toute la carte au lieu de relier chaque pad par un moignon.
#
# L export DSN rend bien la zone sous forme de `(plane GND (polygon B.Cu ...))`
# — verifie le 2026-08-21 — donc Freerouting SAIT s y raccorder. Encore
# faut-il la lui donner.
#
# ⚠️ Le polygone TypeScript etait dessine a l ORIGINE : `(xy 0 0)` ...
# `(xy largeur hauteur)`. Or le contour du board STM32 reel est a
# `(gr_rect (start 100 100) (end 160 140))` — le plan tombait ENTIEREMENT hors
# de la carte. Un plan hors contour ne relie rien.
#
# Decision produit (2026-08-21) : les plans vont sur les deux faces EXTERIEURES,
# quel que soit le nombre de couches. En 4 couches cela donne GND/SIG/SIG/GND,
# un empilage blinde ; les couches internes restent aux signaux.
#
# Garde : tests/test_ground_planes_avant_routage.py.

_GROUND_PLANE_LAYERS: tuple[str, ...] = ("F.Cu", "B.Cu")
_EDGE_COORD_RE = re.compile(
    r"\((?:start|end|xy)\s+(-?[\d.]+)\s+(-?[\d.]+)\)"
)


def _board_outline(pcb_bytes: bytes) -> Optional[tuple[float, float, float, float]]:
    """Boite englobante du contour (Edge.Cuts), ou None s il est illisible.

    Sans contour, on ne devine pas : un plan pose au hasard ne relierait rien.

    Decoupage par chaine plutot que regex multiligne : le contour peut etre
    ecrit sur une ligne (`gr_line ... (layer "Edge.Cuts")`) ou sur plusieurs
    (`gr_rect` avec ses `(start ...)` / `(end ...)` indentes), et une regex
    melant tabulations et retours a la ligne est fragile a ecrire comme a relire.
    """
    text = pcb_bytes.decode("utf-8", errors="replace")
    xs: list[float] = []
    ys: list[float] = []
    for morceau in text.split("(gr_")[1:]:
        if "Edge.Cuts" not in morceau:
            continue
        # Ne lire que jusqu au prochain element graphique : le suivant a son
        # propre contexte, et ses coordonnees ne decrivent pas ce contour.
        for x, y in _EDGE_COORD_RE.findall(morceau):
            xs.append(float(x))
            ys.append(float(y))
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


# Seuil de « boitier dense », identique a celui du placement
# (`tools/placement.py::_DENSE_PAD_COUNT`, lui-meme aligne sur
# `kicad_tools.optim.fom_features`). On ne reinvente pas un critere qui existe.
_DENSE_PAD_COUNT: int = 16
# Marge autour du boitier : le plan doit s arreter assez loin pour laisser au
# routeur un canal de sortie de broche.
_KEEPOUT_MARGIN_MM: float = 1.5


def _dense_footprint_boxes(pcb_bytes: bytes) -> list[tuple[float, float, float, float]]:
    """Boites englobantes des boitiers fine-pitch haut-broches, avec marge.

    ⚠️ Un plan ne peut pas atteindre les broches d un LQFP au pas de 0,5 mm :
    entre deux pattes il n y a place pour aucun cuivre, quel que soit
    l isolement (mesure du 2026-08-21 : 0,5 mm -> 6 connexions manquantes,
    0,25 -> 3, 0,2 -> 3). Le routeur, lui, considere GND « pris en charge par
    le plan » et cesse de le router : ces broches ne sont alors reliees ni par
    le plan, ni par une piste.

    On lit le fichier avec le parseur de kicad-tools, celui qu utilise deja le
    placement — pas de geometrie custom.
    """
    from kicad_tools.schema.pcb import PCB

    with tempfile.TemporaryDirectory() as tmp:
        chemin = Path(tmp) / "b.kicad_pcb"
        chemin.write_bytes(pcb_bytes)
        try:
            pcb = PCB.load(str(chemin))
        except Exception as exc:
            logger.warning("keepout fine-pitch: board illisible (%s) — aucun keepout", exc)
            return []

    boites: list[tuple[float, float, float, float]] = []
    for fp in pcb.footprints:
        pads = list(getattr(fp, "pads", []) or [])
        if len(pads) < _DENSE_PAD_COUNT:
            continue
        # ⚠️ Les positions de pad sont RELATIVES au boitier : il faut y ajouter
        # sa position. Sans cela la boite se calcule autour de l origine et le
        # keepout tombe hors de la carte — meme erreur que le plan de masse
        # dessine a (0,0), corrigee le meme jour.
        origine = getattr(fp, "position", (0.0, 0.0))
        ox = float(getattr(origine, "x", origine[0]))
        oy = float(getattr(origine, "y", origine[1]))

        xs: list[float] = []
        ys: list[float] = []
        for pad in pads:
            pos = getattr(pad, "position", None)
            if pos is None:
                continue
            px = float(getattr(pos, "x", pos[0]))
            py = float(getattr(pos, "y", pos[1]))
            xs.append(ox + px)
            ys.append(oy + py)
        if not xs:
            continue
        m = _KEEPOUT_MARGIN_MM
        boites.append((min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m))
    return boites


# Longueur de la piste de sortie, en mm. Assez pour degager le boitier, assez
# court pour rester dans le canal d escape reserve par le placement.
# Longueur de la sortie de broche, depuis le CENTRE du pad.
#
# ⚠️ 2,0 mm essaye le 2026-08-23 et MESURE PIRE : 0 sortie posee, 3 broches
# orphelines, contre 7 vias et 1 orpheline a 1,2 mm. L hypothese — le via
# retombe au ras des voisines, la pastille faisant 1,475 mm de long — etait
# plausible mais fausse : un trajet plus long rencontre simplement DAVANTAGE
# d obstacles. Ne pas rallonger sans remesurer.
_ESCAPE_TRACE_MM: float = 1.2

# `Pad 47 [GND] of U2 on F.Cu` -> pastille, NET, reference.
# Le net sert a distinguer une paire pad<->pad reparable (net a plan) d une
# paire qui releve du routage.
_PAD_ISOLEE_RE = re.compile(r"^Pad\s+(\S+)\s+\[([^\]]*)\]\s+of\s+(\S+)\s")
_ZONE_RE = re.compile(r"^Zone\s+\[")
# `Zone [GND] on F.Cu, priority 0` -> le net de la zone.
_ZONE_NET_RE = re.compile(r"^Zone\s+\[([^\]]*)\]")


def _pads_isolees_du_plan(rapport_drc: dict) -> list[tuple[str, str]]:
    """Broches que le DRC signale comme non reliees A UNE ZONE.

    ⚠️ Les paires « pad <-> pad » relevent en general du ROUTAGE : y poser un via
    ne relierait rien. MAIS si le net est pris en charge par un PLAN, un via sous
    chaque pastille les relie par l autre face — c est meme la seule reparation
    possible quand aucune sortie laterale n existe.

    Mesure du 2026-08-26 : apres via-in-pad, la derniere connexion manquante du
    board STM32 etait `Pad 47 [GND] of U2 <-> Pad 8 [GND] of U2`, deux pastilles
    du meme net a plan. Les ignorer laissait le board incomplet pour rien.

    Le fanout est une REPARATION : un rapport qu on ne comprend pas ne produit
    rien, jamais une exception. On n ajoute pas une panne a une panne.
    """
    isolees: list[tuple[str, str]] = []
    for item in rapport_drc.get("unconnected_items", []) or []:
        descriptions = [
            str(i.get("description", "")) for i in (item.get("items") or [])
        ]
        pads = [m for m in (_PAD_ISOLEE_RE.match(d) for d in descriptions) if m]
        touche_zone = any(_ZONE_RE.match(d) for d in descriptions)
        if not touche_zone:
            # Paire pad <-> pad : on ne la retient que si le net est confie a un
            # plan, seul cas ou un via repare quelque chose.
            nets = {m.group(2) for m in pads}
            if not nets or not nets.issubset(set(_NETS_CONFIES_AU_PLAN)):
                continue
        for m in pads:
            isolees.append((m.group(3), m.group(1)))
    return isolees


# Regles ouvertes pour une carte portant un boitier fine-pitch. Valeurs
# atteignables chez JLCPCB en option payante (via bouche/recouvert) — pas le
# procede standard, d ou le conditionnement.
_REGLES_FINE_PITCH = {
    "min_via_diameter": 0.3,
    "min_through_hole_diameter": 0.15,
    "min_via_annular_width": 0.075,
    "min_hole_clearance": 0.15,
    "min_clearance": 0.15,
    "min_track_width": 0.15,
}


def _projet_kicad(pcb_bytes: bytes):
    """Fichier projet aux regles ouvertes, ou None si la carte n en a pas besoin.

    ⚠️ Les contraintes de percage ne viennent PAS du fichier de carte : il n en
    declare aucune. Depuis KiCad 6 elles vivent dans le fichier PROJET
    (`.kicad_pro`). Sans lui, `kicad-cli` applique ses defauts — via >= 0,50 mm,
    percage >= 0,30, anneau >= 0,10 — et nos boards n ont jamais eu de projet.

    Consequence mesuree le 2026-08-26 : le via-in-pad, seule reparation
    possible pour les pattes d un LQFP-48 que le plan n atteint pas, etait
    refuse par 9 erreurs. Avec un projet aux regles ouvertes : 0.

    ⚠️ On n ouvre PAS par defaut. Un percage de 0,15 mm est une OPTION PAYANTE
    chez JLCPCB. La condition est la presence reelle d un boitier dense — meme
    critere que le halo d escape et le keepout de coulee.
    """
    if not _dense_footprint_boxes(pcb_bytes):
        return None
    return {
        "board": {"design_settings": {"rules": dict(_REGLES_FINE_PITCH)}},
        "meta": {"filename": "b.kicad_pro", "version": 3},
    }

def _rapport_drc(pcb_bytes: bytes) -> dict:
    """Rapport DRC de kicad-cli, ou dict vide s il est indisponible."""
    cli = shutil.which("kicad-cli")
    if cli is None:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        pcb = Path(tmp) / "b.kicad_pcb"
        rapport = Path(tmp) / "b.json"
        pcb.write_bytes(pcb_bytes)
        # ⚠️ Le fichier PROJET doit etre a cote du board, sinon kicad-cli
        # applique ses defauts et le verdict porte sur des regles que la
        # carte ne suit pas.
        projet = _projet_kicad(pcb_bytes)
        if projet is not None:
            (Path(tmp) / "b.kicad_pro").write_text(
                json.dumps(projet), encoding="utf-8")
        try:
            subprocess.run(
                [cli, "pcb", "drc", str(pcb), "--format", "json", "-o", str(rapport)],
                capture_output=True, text=True, timeout=300, check=False,
            )
            return json.loads(rapport.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("fanout: rapport DRC indisponible (%s)", exc)
            return {}


# Padstack des vias reserves. Nom impose par le DSN que pcbnew exporte —
# `(use_via "Via[0-1]_600:300_um")` dans le bloc `(class kicad_default ...)`.
# Un nom inconnu ferait rejeter le DSN par Freerouting.
_PADSTACK_VIA = "Via[0-1]_600:300_um"

# Vias reserves pour l appel de routage en cours. Variable de module parce que
# `_export_specctra` est appele depuis deux chemins (API et sous-processus)
# et qu il faut injecter aux DEUX — un seul site oublie et la reservation ne
# vaudrait que pour la moitie des routages, sans que rien ne le signale.
_VIAS_RESERVES: list = []


def _bloc_wiring(vias: list, net: str) -> str:
    """Vias reserves, au format Specctra. Rend "" si la liste est vide.

    ⚠️ Unites du DSN, verifiees sur un export reel : `(resolution um 10)`, les
    coordonnees sont en MICROMETRES et **Y est negatif** (Specctra oriente Y
    vers le haut, KiCad vers le bas). Oublier le signe placerait chaque via en
    miroir de sa vraie position — un board syntaxiquement valide et
    geometriquement faux.

    ⚠️ `(type protect)` n est pas decoratif : sans lui le routeur peut
    deplacer ou supprimer le via, et la reservation ne reserverait rien.
    """
    if not vias:
        return ""
    lignes = []
    for x_nm, y_nm in vias:
        lignes.append(
            '    (via "%s" %.1f %.1f (net %s) (type protect))'
            % (_PADSTACK_VIA, x_nm / 1000.0, -y_nm / 1000.0, net)
        )
    return chr(10).join(lignes)


def _injecter_wiring(dsn_text: str, vias: list, net: str) -> str:
    """Ecrit les vias reserves dans le bloc `(wiring)` du DSN.

    ⚠️ pcbnew laisse ce bloc VIDE meme sur un board portant 160 segments —
    verifie le 2026-08-23. Son exporteur ne transporte pas les pistes
    existantes ; on ecrit donc nous-memes, mais seulement quelques vias.

    ⚠️ Un DSN dont on ne reconnait pas la structure est rendu TEL QUEL : mieux
    vaut un routage sans reservation qu un DSN corrompu, que Freerouting
    rejetterait en bloc.
    """
    bloc = _bloc_wiring(vias, net)
    if not bloc:
        return dsn_text
    i = dsn_text.find("(wiring")
    if i == -1:
        logger.warning("DSN sans bloc (wiring) — reservation abandonnee")
        return dsn_text
    j = dsn_text.find(")", i + len("(wiring"))
    if j == -1:
        logger.warning("DSN au bloc (wiring) non ferme — reservation abandonnee")
        return dsn_text
    return dsn_text[:i] + "(wiring" + chr(10) + bloc + chr(10) + "  " + dsn_text[j:]

def _vias_a_reserver(pcb_bytes: bytes) -> list:
    """Positions de via a reserver, calculees sur le board PLACE.

    On coule les plans sur une COPIE pour savoir quelles broches GND le plan
    n atteindra pas — c est le DRC qui les designe, pas une heuristique. Puis
    on calcule leur sortie tant que la place existe encore.

    ⚠️ La copie ne sert qu a MESURER : le board rendu au routeur reste sans
    plan, sinon le routeur croirait GND deja connecte et cesserait de router
    ses pastilles — le piege documente plus haut.

    Rend [] au moindre echec : la reservation est un BONUS, jamais un passage
    oblige. Sans elle le routage se deroule comme avant.
    """
    try:
        sonde = _fill_zones(_add_ground_planes(pcb_bytes))
        isolees = _pads_isolees_du_plan(_rapport_drc(sonde))
        if not isolees:
            return []
        with tempfile.TemporaryDirectory() as tmp:
            entree = Path(tmp) / "in.kicad_pcb"
            resultat = Path(tmp) / "r.json"
            entree.write_bytes(pcb_bytes)
            _run_pcbnew_operation({
                "operation": "plan_escape",
                "pcb": str(entree),
                "result": str(resultat),
                "pads": json.dumps(isolees),
                "escape_mm": str(_ESCAPE_TRACE_MM),
            })
            data = json.loads(resultat.read_text(encoding="utf-8"))
        vias = data.get("vias") or []
        if vias:
            logger.info("reservation : %d via(s) d echappement places avant routage,"
                        " %d renonce(s)", len(vias), data.get("renonces", 0))
        return vias
    except Exception as exc:
        logger.warning("reservation impossible (%s) — routage sans reservation", exc)
        return []


def _reposer_vias_reserves(pcb_bytes: bytes, vias: list) -> bytes:
    """Repose apres routage les vias reserves — l aller-retour Specctra les efface.

    ⚠️ Mesure du 2026-08-21 : 17 vias poses AVANT routage, 4 apres. Le
    round-trip supprime toutes les pistes, vias compris. La reservation ne sert
    donc qu a faire router les signaux AUTOUR ; c est ici qu elle se
    materialise.
    """
    if not vias:
        return pcb_bytes
    with tempfile.TemporaryDirectory() as tmp:
        entree = Path(tmp) / "in.kicad_pcb"
        sortie = Path(tmp) / "out.kicad_pcb"
        resultat = Path(tmp) / "r.json"
        entree.write_bytes(pcb_bytes)
        try:
            _run_pcbnew_operation({
                "operation": "escape_pads",
                "pcb": str(entree),
                "output": str(sortie),
                "result": str(resultat),
                "pads": json.dumps([[v["ref"], v["pad"]] for v in vias]),
                "escape_mm": str(_ESCAPE_TRACE_MM),
            })
        except Exception as exc:
            logger.warning("repose des vias impossible (%s) — board conserve", exc)
            return pcb_bytes
        if not sortie.is_file():
            return pcb_bytes
        return sortie.read_bytes()

def _recoudre_les_ilots(pcb_bytes: bytes) -> bytes:
    """Relie par un via les pastilles qu une piste a detachees du plan.

    ⚠️ Cause etablie le 2026-08-23 : sur le board PLACE, plans coules et
    remplis, ZERO broche GND orpheline — le plan atteint tout, fine-pitch
    compris. Les orphelines n apparaissent qu APRES le routage, quand les
    pistes de signal posees sur F.Cu DECOUPENT le plan en ilots. Le DRC le
    disait depuis le debut : `Zone [GND] on F.Cu <-> Zone [GND] on F.Cu`.

    Ce n est donc pas un probleme de geometrie fine-pitch, mais de
    FRAGMENTATION. Un ilot detache se recoud par un via vers l autre face.

    Reparation, jamais regression : au moindre doute on rend le board recu.
    """
    isolees = _pads_isolees_du_plan(_rapport_drc(pcb_bytes))
    if not isolees:
        return pcb_bytes
    with tempfile.TemporaryDirectory() as tmp:
        entree = Path(tmp) / "in.kicad_pcb"
        sortie = Path(tmp) / "out.kicad_pcb"
        resultat = Path(tmp) / "r.json"
        entree.write_bytes(pcb_bytes)
        try:
            _run_pcbnew_operation({
                "operation": "stitch_islands",
                "pcb": str(entree),
                "output": str(sortie),
                "result": str(resultat),
                "pads": json.dumps(isolees),
            })
        except Exception as exc:
            logger.warning("couture des ilots impossible (%s) — board conserve", exc)
            return pcb_bytes
        if not sortie.is_file():
            return pcb_bytes
        n = json.loads(resultat.read_text(encoding="utf-8")).get("stitched", 0)
        recousu = sortie.read_bytes()
    if not n:
        return pcb_bytes
    logger.info("couture : %d ilot(s) du plan relie(s) par un via", n)
    # Meme garde que le fanout : une reparation ne doit jamais ajouter
    # d erreurs. Un via mal place vaut moins qu une broche orpheline.
    if _compte_erreurs(_rapport_drc(recousu)) > _compte_erreurs(_rapport_drc(pcb_bytes)):
        logger.warning("couture : erreurs ajoutees — board d origine conserve")
        return pcb_bytes
    return recousu

def _percent_verifie(pcb_bytes: bytes, percent_moteur: int, routables: int) -> int:
    """Corrige le pourcentage du moteur par ce que le DRC voit sur le board LIVRE.

    ⚠️ La mesure du moteur regarde AILLEURS : le board juste apres le routeur,
    avant que les plans soient coules et les reparations faites, et sans les
    nets confies au plan. Une pastille GND restee orpheline lui est donc
    structurellement invisible.

    Banc du 2026-08-26, cinq cartes de 17 a 100 composants : TROIS annoncees
    a 100 % gardaient 1, 1 et 3 connexions manquantes.

    L enjeu depasse l affichage : `routed_percent` decide d arreter, de
    relancer le placement ou d appeler le reasoner, et les statuts qui en
    decoulent alimentent le gate JLCPCB. Un 100 % mensonger arrete la chaine
    sur une carte incomplete.

    ⚠️ Correction A LA BAISSE seulement. Si le moteur annonce 50 %, ce n est
    pas au DRC de le promouvoir — il constate des manques, pas des reussites.
    Et un DRC indisponible ne change rien : mieux vaut le chiffre du routeur
    qu un chiffre invente.
    """
    if routables <= 0:
        return percent_moteur
    rapport = _rapport_drc(pcb_bytes)
    manquants = rapport.get("unconnected_items") or []
    if not manquants:
        return percent_moteur
    # On compte les NETS touches, pas les paires : un net tres fragmente
    # rendrait le pourcentage negatif.
    nets = set()
    for item in manquants:
        for i in item.get("items") or []:
            d = str(i.get("description", ""))
            m = _PAD_ISOLEE_RE.match(d)
            if m:
                nets.add(m.group(2))
                continue
            # ⚠️ Une paire `Zone [GND] <-> Zone [GND]` est un PLAN COUPE EN
            # ILOTS, pas une pastille orpheline. Ne chercher que des pastilles
            # la rendait invisible — mesure du 2026-08-26 : les 3 « manquantes »
            # de la carte a 100 composants etaient exactement cela, et le
            # pourcentage restait a 100 %.
            z = _ZONE_NET_RE.match(d)
            if z:
                nets.add(z.group(1))
    if not nets:
        return percent_moteur
    reel = int(round(100 * max(0, routables - len(nets)) / routables))
    if reel < percent_moteur:
        logger.warning(
            "routage : %d %% annonce par le moteur, mais le DRC voit %d net(s) "
            "incomplet(s) sur %d — pourcentage ramene a %d %%",
            percent_moteur, len(nets), routables, reel)
        return reel
    return percent_moteur

def _recoudre_les_zones(pcb_bytes: bytes) -> bytes:
    """Relie par un via les ilots d un meme plan, decoupes par les pistes.

    ⚠️ Distinct de `_recoudre_les_ilots`, qui traite des PASTILLES isolees.
    Ici il n y a pas de pastille en cause : c est le cuivre du plan lui-meme
    qui est coupe. Mesure du 2026-08-26, carte a 100 composants — zone GND sur
    F.Cu = 5 ilots, sur B.Cu = 1 seul. Le DRC le signalait par des paires
    `Zone [GND] <-> Zone [GND]`, invisibles a la couture de pastilles.

    Reparation, jamais regression : au moindre doute on rend le board recu, et
    on refuse un resultat qui ajoute des erreurs.
    """
    if b"filled_polygon" not in pcb_bytes:
        return pcb_bytes
    with tempfile.TemporaryDirectory() as tmp:
        entree = Path(tmp) / "in.kicad_pcb"
        sortie = Path(tmp) / "out.kicad_pcb"
        resultat = Path(tmp) / "r.json"
        entree.write_bytes(pcb_bytes)
        try:
            _run_pcbnew_operation({
                "operation": "stitch_zones",
                "pcb": str(entree),
                "output": str(sortie),
                "result": str(resultat),
                "nets": json.dumps(list(_NETS_CONFIES_AU_PLAN)),
            })
        except Exception as exc:
            logger.warning("couture des zones impossible (%s) — board conserve", exc)
            return pcb_bytes
        if not sortie.is_file():
            return pcb_bytes
        n = json.loads(resultat.read_text(encoding="utf-8")).get("stitched", 0)
        recousu = sortie.read_bytes()
    if not n:
        return pcb_bytes
    logger.info("couture : %d via(s) poses dans les ilots de plan", n)
    if _compte_erreurs(_rapport_drc(recousu)) > _compte_erreurs(_rapport_drc(pcb_bytes)):
        logger.warning("couture de zones : erreurs ajoutees — board d origine conserve")
        return pcb_bytes
    return recousu

def _gnd_orphelines(pcb_bytes: bytes) -> int:
    """Nombre de broches GND que le DRC declare non reliees a leur plan."""
    try:
        return len(_pads_isolees_du_plan(_rapport_drc(pcb_bytes)))
    except Exception as exc:
        # Ne pas declencher un repli couteux sur une mesure qu on n a pas pu
        # faire : sans verdict, on garde ce que la sequence a produit.
        logger.warning("plan de masse : orphelines non mesurables (%s)", exc)
        return 0


def _router_en_incluant_gnd(pcb_bytes: bytes, req: "RouteAutoRequest",
                            budget_s: float):
    """Refait le routage SANS confier GND au plan, puis recoule les plans.

    Repli de la sequence demandee par l utilisateur. Il n intervient que si des
    broches GND sont restees orphelines : la sequence est toujours essayee
    d abord, et gardee des qu elle aboutit.

    ⚠️ Rend None sur echec — l appelant garde alors le board de la sequence.
    Un repli qui echoue ne doit pas detruire le resultat qu il devait ameliorer.
    """
    global _NETS_CONFIES_AU_PLAN
    memoire = _NETS_CONFIES_AU_PLAN
    try:
        _NETS_CONFIES_AU_PLAN = ()
        tentative = RouteAutoRequest(
            kicad_pcb_b64=base64.b64encode(pcb_bytes).decode("ascii"),
            layers=req.layers,
            timeout_s=max(budget_s, _MIN_LEVEL_BUDGET_S),
        )
        res = _route_auto_once(tentative)
        if not res.kicad_pcb_b64 or res.skipped:
            return None
        board = _fill_zones(_add_ground_planes(base64.b64decode(res.kicad_pcb_b64)))
        return _fanout_pads_isolees(board)
    except Exception as exc:
        logger.warning("repli routage GND impossible (%s) — sequence conservee", exc)
        return None
    finally:
        _NETS_CONFIES_AU_PLAN = memoire


def _fill_zones(pcb_bytes: bytes) -> bytes:
    """Remplit les zones de cuivre. Reparation : au moindre doute, board rendu tel quel.

    ⚠️ Sans cet appel, `_add_ground_planes` ne produit que des CONTOURS : le
    board sort avec des zones et zero `filled_polygon`. Mesure du 2026-08-23,
    board STM32 — 3 zones declarees, 0 polygone rempli. Le plan n offrait donc
    aucun blindage, et le defaut restait invisible parce que les pistes
    assuraient toute la connectivite.

    `_specctra_roundtrip` remplit deja, mais il s execute AVANT la coulee.
    """
    if b"(zone" not in pcb_bytes:
        return pcb_bytes
    with tempfile.TemporaryDirectory() as tmp:
        entree = Path(tmp) / "in.kicad_pcb"
        sortie = Path(tmp) / "out.kicad_pcb"
        entree.write_bytes(pcb_bytes)
        try:
            _run_pcbnew_operation({
                "operation": "fill_zones",
                "pcb": str(entree),
                "output": str(sortie),
            })
        except Exception as exc:
            logger.warning("plans : remplissage impossible (%s) — board conserve", exc)
            return pcb_bytes
        if not sortie.exists():
            return pcb_bytes
        rempli = sortie.read_bytes()
    if b"filled_polygon" not in rempli:
        # Un remplissage qui ne produit aucun polygone n a pas eu lieu : mieux
        # vaut le dire que livrer un contour vide en le croyant rempli.
        logger.warning("plans : aucun polygone rempli — board conserve")
        return pcb_bytes
    return rempli


def _compte_erreurs(rapport: dict) -> int:
    """Nombre de violations de severite `error`. Les warnings ne bloquent rien."""
    return sum(
        1 for v in (rapport.get("violations") or [])
        if isinstance(v, dict) and v.get("severity") == "error"
    )


def _pose_les_vias_d_echappement(pcb_bytes: bytes, isolees: list) -> bytes:
    """Pose un via par broche isolee. Rend le board d origine en cas d echec."""
    with tempfile.TemporaryDirectory() as tmp:
        entree = Path(tmp) / "in.kicad_pcb"
        sortie = Path(tmp) / "out.kicad_pcb"
        resultat = Path(tmp) / "r.json"
        entree.write_bytes(pcb_bytes)
        try:
            _run_pcbnew_operation({
                "operation": "escape_pads",
                "pcb": str(entree),
                "output": str(sortie),
                "result": str(resultat),
                "pads": json.dumps(isolees),
                "escape_mm": str(_ESCAPE_TRACE_MM),
            })
        except Exception as exc:
            logger.warning("fanout: sortie de broche impossible (%s) — board conserve", exc)
            return pcb_bytes
        if not sortie.is_file():
            return pcb_bytes
        n = json.loads(resultat.read_text(encoding="utf-8")).get("escaped", 0)
        logger.info("fanout: %d broche(s) sortie(s) vers le plan", n)
        return sortie.read_bytes()


def _fanout_pads_isolees(pcb_bytes: bytes) -> bytes:
    """Sort par un via les broches que le plan n a pas pu relier.

    ⚠️ APRES le routage, jamais avant : le round-trip Specctra supprime toutes
    les pistes, vias compris (17 vias poses avant routage, 4 apres).

    ⚠️ Le via est pose A L AVEUGLE — la direction de sortie pointe a l oppose
    du centre du boitier, sans regarder ce qui se trouve sur le trajet. Mesure
    du 2026-08-23, board STM32 : le fanout ajoute 6 ERREURS dont DEUX
    `shorting_items` entre GND et +3.3V. Sans lui, zero erreur.

    D ou la garde : on compare les erreurs AVANT et APRES, et on rend
    l original des qu elles augmentent. Echanger une connexion manquante
    contre un court-circuit est un mauvais marche — la premiere bloque la
    commande au DRC, le second peut partir en fabrication.

    Garde : tests/test_fanout_jamais_regression.py.
    """
    rapport = _rapport_drc(pcb_bytes)
    isolees = _pads_isolees_du_plan(rapport)
    if not isolees:
        return pcb_bytes

    repare = _pose_les_vias_d_echappement(pcb_bytes, isolees)
    if repare is pcb_bytes:
        return pcb_bytes

    avant = _compte_erreurs(rapport)
    apres = _compte_erreurs(_rapport_drc(repare))
    if apres > avant:
        logger.warning(
            "fanout: %d erreur(s) ajoutee(s) (%d -> %d) — board d origine conserve",
            apres - avant, avant, apres)
        return pcb_bytes
    return repare


def _couches_deja_couvertes(text: str) -> set:
    r"""Couches portant deja une zone de cuivre.

    ⚠️ Le motif precedent exigeait `(zone` et `(layer` sur la MEME ligne :

        re.findall(r'\(zone[^\n]*\\(layer "([^"]+)"', text)

    KiCad les ecrit sur des lignes SEPAREES. L ensemble ressortait donc
    toujours vide et `_add_ground_planes` coulait par-dessus une zone
    existante. Mesure du 2026-08-24 sur le board d un run reel : QUATRE zones
    GND, deux par face, et 3 erreurs DRC
    « Copper zones intersect (must have distinct priorities) ».

    Aucun re-tirage de placement ne corrige cela — le run rebouclait six fois
    sur 18 violations identiques avant d epuiser ses iterations.

    Invisible en local : notre generateur ecrit ses zones sur une seule ligne,
    et la fixture en heritait. Le defaut n apparait que sur un board reecrit
    par pcbnew — donc tout board sorti du round-trip Specctra.
    """
    couches = set()
    for bloc in text.split("(zone")[1:]:
        # On ne lit que le debut du bloc : `(layer ...)` y figure toujours,
        # avant les polygones remplis qui peuvent peser des milliers de lignes.
        tete = bloc[:400]
        couches.update(re.findall(r'\(layers?\s+"([^"]+)"', tete))
    return couches


# Mots-cles de keepout dont KiCad attend un JETON NU, jamais une chaine.
_CLES_KEEPOUT = ("tracks", "vias", "pads", "copperpour", "footprints")


def _deguillemeter_keepout(pcb_bytes: bytes) -> bytes:
    """Retire les guillemets des valeurs de keepout. KiCad les refuse.

    ⚠️ Cause racine des 19 connexions manquantes de l ESP32 du banc, isolee le
    2026-08-26 en capturant le board que pcbnew refusait :

        (keepout (tracks "not_allowed") ...)   -> LoadBoard rend None
        (keepout (tracks not_allowed) ...)     -> charge

    pcbnew refuse le fichier ENTIER. L export Specctra echoue, Freerouting
    n est jamais appele, et la cascade retombe sur kicad-tools : 7 connexions
    manquantes et 58 erreurs de fabricabilite la ou Freerouting en produit
    zero.

    ⚠️ Le keepout fautif n est PAS le notre — le notre ecrit ses valeurs nues.
    Il vient d un board genere par kicad_tools. On repare a la lecture, comme
    on requote deja les proprietes numeriques nues des schemas.

    ⚠️ J ai d abord accuse les COUCHES du meme keepout (32 citees sur une carte
    qui en declare 2). Anomalie reelle, mais la mesure a tranche : la retirer
    ne changeait rien, deguillemeter suffit.
    """
    text = pcb_bytes.decode("utf-8", errors="replace")
    motif = (chr(92) + "((" + "|".join(_CLES_KEEPOUT) + ") " + chr(34) +
             "([a-z_]+)" + chr(34) + chr(92) + ")")
    nouveau, n = re.subn(motif, lambda m: "(%s %s)" % (m.group(1), m.group(2)), text)
    if not n:
        return pcb_bytes
    logger.info("keepout : %d valeur(s) deguillemetee(s) — KiCad refuse les chaines", n)
    return nouveau.encode("utf-8")

def _retirer_couches_fantomes(pcb_bytes: bytes) -> bytes:
    """Retire des zones les couches que la carte ne declare pas.

    ⚠️ Cause racine des 19 connexions manquantes de l ESP32 du banc, trouvee le
    2026-08-26 en capturant le board que pcbnew refusait :

        couches cuivre declarees par la carte :  2  (F.Cu, B.Cu)
        couches citees par un keepout         : 32  (F.Cu, B.Cu, In1..In30)

    pcbnew refuse alors le fichier ENTIER — `LoadBoard` rend `None`. L export
    Specctra echoue, Freerouting n est jamais appele, et la cascade retombe sur
    kicad-tools : 7 connexions manquantes et 58 erreurs de fabricabilite la ou
    Freerouting en produit zero.

    ⚠️ Le keepout fautif n est PAS le notre — le notre ecrit `(copperpour
    not_allowed)` sans guillemets. Il vient d un board genere par kicad_tools.
    On repare a la lecture, comme on requote deja les proprietes numeriques.

    ⚠️ On retire les COUCHES, jamais la zone : un keepout supprime laisserait
    le plan couler sous un boitier fine-pitch.
    """
    text = pcb_bytes.decode("utf-8", errors="replace")
    reelles = set(_couches_cuivre_declarees(text))
    if not reelles:
        return pcb_bytes

    def nettoyer(m):
        citees = re.findall(chr(34) + "([^" + chr(34) + "]+)" + chr(34), m.group(1))
        gardees = [c for c in citees if not c.endswith(".Cu") or c in reelles]
        if gardees == citees:
            return m.group(0)
        return "(layers " + " ".join(chr(34) + c + chr(34) for c in gardees) + ")"

    motif = (chr(92) + "(layers ((?:" + chr(92) + "s*" + chr(34) + "[^" + chr(34) + "]+" + chr(34) + ")+)" + chr(92) + "s*" + chr(92) + ")")
    nouveau, n = re.subn(motif, nettoyer, text)
    if not n or nouveau == text:
        return pcb_bytes
    logger.info("zones : couches fantomes retirees (la carte n en declare que %d)",
                len(reelles))
    return nouveau.encode("utf-8")


def _couches_cuivre_declarees(text: str) -> list:
    """Couches cuivre du bloc `(layers ...)` DE LA CARTE.

    ⚠️ Borne au bloc lui-meme, pas a un nombre de caracteres : les ZONES ont
    leur propre `(layers ...)`, et une fenetre fixe les avalait — le
    nettoyage croyait alors declarees les couches fantomes qu il devait
    retirer, et ne retirait rien.
    """
    i = text.find("(layers")
    if i == -1:
        return []
    prof = 0
    for j in range(i, len(text)):
        if text[j] == "(":
            prof += 1
        elif text[j] == ")":
            prof -= 1
            if prof == 0:
                bloc = text[i:j + 1]
                break
    else:
        return []
    return re.findall(chr(34) + "([A-Za-z0-9]+" + chr(92) + ".Cu)" + chr(34), bloc)

def _add_ground_planes(pcb_bytes: bytes) -> bytes:
    """Coule une zone GND sur chaque face exterieure, si elle n y est pas deja.

    N empile jamais un second plan : `kct route` coule lui-meme ses zones power,
    et deux remplissages concurrents sur la meme couche seraient un conflit, pas
    une securite.
    """
    text = pcb_bytes.decode("utf-8", errors="replace")

    numerote = re.search(r'\(net (\d+) "GND"\)', text)
    if not numerote and not re.search(r'\(net "GND"\)', text):
        return pcb_bytes

    contour = _board_outline(pcb_bytes)
    if contour is None:
        logger.warning("plans de masse: contour Edge.Cuts illisible — aucun plan coule")
        return pcb_bytes
    x1, y1, x2, y2 = contour

    existantes = _couches_deja_couvertes(text)
    # ⚠️ DECISION PRODUIT (2026-08-22, reaffirmee) : les plans vont sur les
    # DEUX faces exterieures, y compris en 2 couches.
    #
    # La reserve a ete posee deux fois, mesures a l appui, et tranchee dans ce
    # sens. Elle est conservee ici pour que le cout soit connu, pas rediscute :
    #
    #   LQFP-48 : pads 0,3 mm, pas 0,5 mm -> 0,2 mm entre deux pattes.
    #   Un isolement de 0,25 mm de chaque cote en demanderait 0,5 : le cuivre
    #   du plan ne passe pas entre les pattes. Le routeur croit alors GND pris
    #   en charge et ne le route pas ; le plan ne peut pas l atteindre. Ni l un
    #   ni l autre ne fait le travail.
    #
    # Le dispositif qui rend ce choix tenable, dans l ordre :
    #   1. keepout de coulee autour des boitiers denses  (le plan s arrete)
    #   2. fanout des broches signalees par le DRC       (sortie + via)
    #   3. vias de couture sur les ilots fragmentes      (`kct stitch`)
    #
    # Sans le point 3, la piste de sortie du fanout coupe le plan en ilots et
    # le DRC signale « Zone <-> Zone ». La couture est la reponse industrielle
    # standard a un plan fragmente.
    # Garde : tests/test_ground_planes_avant_routage.py.
    a_couler = [c for c in _GROUND_PLANE_LAYERS if c not in existantes]
    if not a_couler:
        return pcb_bytes

    # Sans numero de net, on n en invente pas : `(net_name "GND")` suffit a
    # KiCad, et un identifiant fabrique pourrait en designer un autre.
    ref = f"(net {numerote.group(1)}) " if numerote else ""

    zones: list[str] = []
    for couche in a_couler:
        zones.append(
            chr(10).join([
                f'  (zone {ref}(net_name "GND") (layer "{couche}") (hatch edge 0.508)',
                # ⚠️ 0,5 mm vidait tout le cuivre entre les broches d un boitier
                # fine-pitch. Mesure du 2026-08-21 sur le LQFP-48 (pas 0,5 mm) :
                # 0.5 -> 6 connexions manquantes, 0.25 -> 3. La valeur venait de
                # la version TypeScript, ecrite pour un board simple.
                "    (connect_pads yes (clearance 0.25))",
                "    (min_thickness 0.25)",
                "    (fill yes (thermal_gap 0.25) (thermal_bridge_width 0.5))",
                f"    (polygon (pts (xy {x1} {y1}) (xy {x2} {y1}) (xy {x2} {y2}) (xy {x1} {y2})))",
                "  )",
            ])
        )

    # ⚠️ Un plan ne peut pas atteindre les broches d un boitier fine-pitch :
    # entre deux pattes au pas de 0,5 mm il n y a place pour aucun cuivre. Le
    # routeur, lui, tient pour deja connectees les pastilles qui tombent
    # GEOMETRIQUEMENT dans le polygone de la zone, et cesse de les router —
    # ces broches finissent reliees NI par le plan NI par une piste (2 a 3
    # connexions manquantes mesurees le 2026-08-21).
    #
    # ⚠️ Verifie le 2026-08-23 sur le DSN reellement exporte : le net GND
    # n est PAS retire de la netlist — ses 18 broches sont presentees au
    # routeur AVEC comme SANS coulee. Seul le bloc `(plane GND ...)` change
    # (2 declarations, une par face). Le routeur n est donc pas PRIVE du
    # travail, il DECIDE de ne pas le faire. Meme confusion que `kct stitch`,
    # qui repondait « No unconnected pads found » pour la meme raison :
    # etre dans le polygone n est pas etre relie au cuivre.
    #
    # Un keepout de COULEE resout les deux : le plan cesse de pretendre les
    # couvrir, et le routeur les route jusqu au bord du plan. Pistes et vias
    # restent autorises — on interdit le remplissage, pas le routage.
    for (kx1, ky1, kx2, ky2) in _dense_footprint_boxes(pcb_bytes):
        zones.append(
            chr(10).join([
                '  (zone (net 0) (net_name "") (layer "F.Cu") (hatch edge 0.508)',
                "    (keepout (tracks allowed) (vias allowed) (pads allowed)",
                "             (copperpour not_allowed) (footprints allowed))",
                f"    (polygon (pts (xy {kx1} {ky1}) (xy {kx2} {ky1}) "
                f"                  (xy {kx2} {ky2}) (xy {kx1} {ky2})))",
                "  )",
            ])
        )

    coupe = text.rstrip()
    if not coupe.endswith(")"):
        return pcb_bytes
    corps = chr(10).join(zones)
    return (coupe[:-1] + chr(10) + corps + chr(10) + ")").encode("utf-8")


def _count_copper_layers(pcb_bytes: bytes) -> int:
    """Nombre de couches CUIVRE réellement déclarées par le board.

    ⚠️ `layers` recopiait la DEMANDE du client (`layers=req.layers`) sans jamais
    regarder le board : une requête à 4 couches recevait « 4 » sur un board qui
    en a 2. `handlers/routing.ts` remonte ce chiffre à l'orchestrateur et à
    l'utilisateur (« … 12 nets, 4 couches »), donc c'était de la désinformation,
    pas un détail d'affichage. Même famille que `via_count`.

    Ne lit que le bloc `(layers …)` en tête : les `(layer "F.Cu")` des pistes
    sont des RÉFÉRENCES, pas des déclarations — les compter donnerait le nombre
    de segments.

    Un board sans bloc `(layers …)` rend 0 : rien à mesurer n'est pas une
    autorisation à inventer une valeur plausible.
    Garde : tests/test_routing_layers_reels.py.
    """
    text = pcb_bytes.decode("utf-8", errors="replace")
    bloc = _layers_block(text)
    if not bloc:
        return 0
    return len(set(_COPPER_LAYER_RE.findall(bloc)))


def _count_vias(pcb_bytes: bytes) -> int:
    return len(_VIA_RE.findall(pcb_bytes.decode("utf-8", errors="replace")))


def _track_length_mm(pcb_bytes: bytes) -> float:
    """Longueur cumulée des segments de piste, en millimètres.

    Ne compte que les `(segment …)` : les `(arc …)` portent aussi du cuivre mais
    demandent la géométrie de l'arc. Freerouting et `kct route` produisent des
    segments ; un routeur qui émettrait des arcs sous-estimerait la longueur —
    limite connue, pas un chiffre inventé.
    """
    text = pcb_bytes.decode("utf-8", errors="replace")
    total = 0.0
    for x1, y1, x2, y2 in _SEGMENT_RE.findall(text):
        total += math.hypot(float(x2) - float(x1), float(y2) - float(y1))
    return round(total, 3)


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


# Bruit que pcbnew crache a chaque chargement de board et qui n a jamais rien
# a voir avec la panne. Il remplissait a lui seul les 300 caracteres du message
# d erreur, cachant la VRAIE cause — trois diagnostics perdus le 2026-08-21
# (SetFilled, GetConnectedItems, puis celui-ci).
_BRUIT_PCBNEW = ("property.h", "PROPERTY_ENUM", "m_choices.GetCount")


def _utile(sortie: str) -> str:
    """Garde les lignes qui DISENT quelque chose, jette l assert wxWidgets."""
    lignes = [
        l for l in sortie.strip().splitlines()
        if l.strip() and not any(bruit in l for bruit in _BRUIT_PCBNEW)
    ]
    # Les dernieres lignes portent l exception ; le debut est la pile d appels.
    return " | ".join(lignes[-4:])[:600] if lignes else sortie.strip()[:300]


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
        raise RuntimeError(
            f"pcbnew child exit {proc.returncode}: "
            f"{_utile(proc.stderr or proc.stdout or '')}"
        )


# Nets que le PLAN prend en charge : ils sont retires de la netlist du DSN, donc
# le routeur ne leur tire aucune piste. Le plan est coule APRES le routage, et
# les pastilles qu il n atteint pas reellement recoivent un via d echappement.
#
# ⚠️ NE PAS obtenir cet effet en declarant un plan dans le DSN : le routeur
# tiendrait alors pour connectees les pastilles geometriquement contenues dans
# le polygone, ce qui est FAUX sur un pas de 0,5 mm (3 connexions manquantes
# mesurees). Retirer le net est sans ambiguite ; declarer un plan est une
# promesse que la geometrie ne tient pas.
# ⚠️ DESACTIVE le 2026-08-23, apres mesure. Confier GND au plan suppose que le
# plan porte du CUIVRE — or nos zones n en portent pas : le board rendu compte
# 3 zones et ZERO `filled_polygon`. Ce sont des contours vides.
#
# Mesure, board STM32, variante activee :
#     17 connexions manquantes (contre 0 aujourd hui), et pas seulement sur le
#     fine-pitch : C1, C2, C3, C12..C16 et U1 — de gros pads que le plan
#     atteindrait sans peine s il etait rempli.
#
# L ordre actuel (router TOUT, couler ensuite) masque le defaut : les pistes
# font le travail, donc l absence de remplissage ne se voit pas dans le DRC.
# Retirer GND du routage retire ce masque et revele le plan vide.
#
# Reactiver ce reglage EXIGE d abord un remplissage reel des zones
# (`ZONE_FILLER` dans le processus pcbnew), puis une nouvelle mesure.
# Séquence demandée par l'utilisateur, active depuis le 2026-08-23 :
#   ① le plan prend GND en charge — il est retiré de la netlist du DSN
#   ② le routeur ne route que les SIGNAUX
#   ③ coulée finale, remplie
#   ④ les broches GND non reliées reçoivent une sortie fine + un via
#
# Elle divise le cuivre posé par deux (≈105 segments contre 214) : les pistes
# GND que le routeur tirait deviennent redondantes dès que le plan est coulé.
#
# ⚠️ Elle n'aboutit pas toujours. Mesuré sur le board STM32, 1 à 3 broches
# fine-pitch du LQFP-48 restent orphelines : l'espace libre autour d'elles
# (0,318 mm) est inférieur à ce qu'un via réclame (0,500 mm), et le trajet
# vers la zone dégagée doit traverser cette zone saturée. D'où le repli
# ci-dessous — jamais livrer une carte non connectée.
_NETS_CONFIES_AU_PLAN: tuple[str, ...] = ("GND",)


def _strip_net_from_dsn(dsn_text: str, net_name: str) -> tuple[str, int]:
    """Retire `(net <nom> (pins ...))` de la section network. Rend (texte, broches)."""
    debut = dsn_text.find(f"(net {net_name}")
    if debut == -1:
        return dsn_text, 0
    # Refuser un prefixe commun : `GND` ne doit pas emporter `GNDA`.
    suivant = dsn_text[debut + len(f"(net {net_name}")]
    if not suivant.isspace():
        return dsn_text, 0

    profondeur, i = 0, debut
    while i < len(dsn_text):
        if dsn_text[i] == "(":
            profondeur += 1
        elif dsn_text[i] == ")":
            profondeur -= 1
            if profondeur == 0:
                break
        i += 1
    else:
        return dsn_text, 0  # parentheses desequilibrees : on ne touche a rien

    bloc = dsn_text[debut : i + 1]
    pins = bloc[bloc.find("(pins") :].replace("(pins", "").replace(")", "")
    n = len(pins.split())

    fin = i + 1
    while fin < len(dsn_text) and dsn_text[fin] in " " + chr(9):
        fin += 1
    if dsn_text[fin : fin + 1] == chr(10):
        fin += 1
    tete = dsn_text[:debut].rstrip(" " + chr(9))
    return tete + dsn_text[fin:], n


def _confier_au_plan(dsn_path: Path) -> int:
    """Retire du DSN les nets pris en charge par le plan. Rend le nb de broches."""
    texte = dsn_path.read_text(encoding="utf-8", errors="replace")
    total = 0
    for net in _NETS_CONFIES_AU_PLAN:
        texte, n = _strip_net_from_dsn(texte, net)
        total += n
    if total:
        dsn_path.write_text(texte, encoding="utf-8")
        logger.info("routage : %d broches confiees au plan (%s)", total,
                    ", ".join(_NETS_CONFIES_AU_PLAN))
    return total


def _export_specctra(pcb_bytes: bytes, dsn_path: Path) -> None:
    """Export a PCB to Specctra DSN in a bounded pcbnew child process.

    All existing tracks are removed before export so Freerouting starts from
    scratch — without stale TS-generated traces that pointed to pre-placement
    component positions.
    """
    # ⚠️ Nettoyer AVANT de charger : une zone citant des couches que la
    # carte ne declare pas fait rendre `None` a `LoadBoard`, et pcbnew refuse
    # le fichier ENTIER. Mesure du 2026-08-26 : un keepout de kicad-tools
    # citait 32 couches sur une carte qui en declare 2.
    pcb_bytes = _retirer_couches_fantomes(pcb_bytes)
    pcb_bytes = _deguillemeter_keepout(pcb_bytes)
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
        # Meme exclusion que `_count_routable_nets` : sans elle le
        # numerateur et le denominateur ne parleraient pas du meme ensemble.
        "exclure_nets": json.dumps(list(_NETS_CONFIES_AU_PLAN)),
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

def _route_auto_once(req: RouteAutoRequest) -> RouteAutoResponse:
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
    # Échéance de l'APPEL, calculée UNE fois. Chaque niveau recevra le restant.
    deadline = _now() + req.timeout_s

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

    # --- Niveau 1 : Freerouting REST API server (1 JVM persistant, meilleure qualité) ---
    # ⚠️ Un niveau lance avec zero seconde echoue INSTANTANEMENT — et son
    # echec est ensuite impute au routeur, ce qui envoie chercher au mauvais
    # endroit. Mesure du 2026-08-21 : « Freerouting echoue (... timed out
    # after 0 seconds) » alors qu il n avait jamais tourne, le Niveau 1 ayant
    # consomme tout le budget. Mieux vaut passer au suivant.
    api_url = _find_freerouting_api()
    if api_url is not None and _budget_suffisant(_remaining_budget_s(deadline)):
        try:
            new_pcb = _route_with_freerouting_api(
                pcb_bytes, _remaining_budget_s(deadline)
            )
            _guard_netlist_preserved(new_pcb, input_nets, "freerouting-api")
            routed_pct = _measured_routed_percent(new_pcb, net_count)
            logger.info("Freerouting API: %d%% routé (connectivité mesurée)", routed_pct)
            return RouteAutoResponse(
                kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
                routed_percent=routed_pct,
                layers=_count_copper_layers(new_pcb),
                engine="freerouting-api",
                via_count=_count_vias(new_pcb),
                track_length_mm=_track_length_mm(new_pcb),
                skipped=False,
            )
        except Exception as exc:
            freerouting_a_echoue = True
            logger.warning("Freerouting API échoué (%s) — subprocess fallback", exc)

    # --- Niveau 2 : Freerouting subprocess (fallback si API server absent) ---
    paths = _find_freerouting()
    if paths is not None and _budget_suffisant(_remaining_budget_s(deadline)):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dsn = Path(tmp) / "board.dsn"
                ses = Path(tmp) / "board.ses"
                _export_specctra(pcb_bytes, dsn)
                _confier_au_plan(dsn)
                if _VIAS_RESERVES:
                    dsn.write_text(_injecter_wiring(
                        dsn.read_text(encoding="utf-8", errors="replace"),
                        [(v["via_x"], v["via_y"]) for v in _VIAS_RESERVES],
                        _NETS_CONFIES_AU_PLAN[0] if _NETS_CONFIES_AU_PLAN else "GND",
                    ), encoding="utf-8")
                _run_freerouting(paths, dsn, ses, _remaining_budget_s(deadline))
                new_pcb = _specctra_roundtrip(pcb_bytes, ses)
            _guard_netlist_preserved(new_pcb, input_nets, "freerouting-cli")
            routed_pct = _measured_routed_percent(new_pcb, net_count)
            logger.info("Freerouting: %d%% routé (connectivité mesurée)", routed_pct)
            return RouteAutoResponse(
                kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
                routed_percent=routed_pct,
                layers=_count_copper_layers(new_pcb),
                engine="freerouting-cli",
                via_count=_count_vias(new_pcb),
                track_length_mm=_track_length_mm(new_pcb),
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

    # ⚠️ kicad-tools est passe DERRIERE Freerouting le 2026-08-21 (decision
    # produit). L escalade de couches etait etouffee : mesure, le premier
    # palier consommait 751 s — tout le budget — et Freerouting recevait
    # ensuite ZERO seconde. Un palier Freerouting coute 4 a 31 s.
    #
    # La qualite va dans le meme sens (board STM32, 6 tirages) : Freerouting
    # rend 0 connexion manquante et n ajoute AUCUNE violation ; kicad-tools en
    # laisse 7 et ajoute 58 ERREURS de fabricabilite.
    #
    # Il RESTE dans la cascade : seul a savoir escalader les couches lui-meme
    # (`--auto-layers`), et derniere chance quand Freerouting echoue.
    # Garde : tests/test_ordre_des_niveaux.py.
    # --- Niveau 3 : kicad-tools A* (circuits simples ≤30 nets/comps) ---
    if is_simple and _budget_suffisant(_remaining_budget_s(deadline)):
        try:
            new_pcb, routed_pct = _route_with_kicad_tools(
                pcb_bytes, _remaining_budget_s(deadline)
            )
            logger.info("kicad-tools A*: %d%% routé", routed_pct)
            if routed_pct >= _MIN_ROUTED_PCT:
                _guard_netlist_preserved(new_pcb, input_nets, "kicad-tools")
                return RouteAutoResponse(
                    kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
                    routed_percent=routed_pct,
                    layers=_count_copper_layers(new_pcb),
                    engine="kicad-tools",
                    via_count=_count_vias(new_pcb),
                    track_length_mm=_track_length_mm(new_pcb),
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

    # --- Niveau 4 : kicad-tools negotiated sans limite (tous circuits) ---
    # Reuse the Niveau-1 partial when we already have one (avoid a second
    # expensive run). Même algorithme A* negotiated, fallback quand Freerouting
    # absent ou échoue.
    try:
        if kt_partial is not None:
            new_pcb, routed_pct = kt_partial
        elif _budget_suffisant(_remaining_budget_s(deadline)):
            new_pcb, routed_pct = _route_with_kicad_tools(
                pcb_bytes, _remaining_budget_s(deadline)
            )
        else:
            # Rien a sauver et plus de temps : on tombe sur le Niveau 5, qui rend
            # `skipped=True`. Traite en fail-fast cote TypeScript — jamais un
            # faux succes.
            raise RuntimeError("budget epuise avant le Niveau 4")
        logger.info("kicad-tools A* (no limit): %d%% routé", routed_pct)
        _guard_netlist_preserved(new_pcb, input_nets, "kicad-tools")
        return RouteAutoResponse(
            kicad_pcb_b64=base64.b64encode(new_pcb).decode("ascii"),
            routed_percent=routed_pct,
            layers=_count_copper_layers(new_pcb),
            engine="kicad-tools",
            via_count=_count_vias(new_pcb),
            track_length_mm=_track_length_mm(new_pcb),
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


@router.post("/route/auto", response_model=RouteAutoResponse)
def route_auto(req: RouteAutoRequest) -> RouteAutoResponse:
    """Route en escaladant les couches jusqu'a obtenir 100 %.

    `req.layers` est un PLAFOND (celui du plan), pas une consigne. On part de 2
    couches et on monte 4 -> 6 -> 8 tant que le routage n'est pas complet.

    ⚠️ Une carte 4 couches coute sensiblement plus cher a fabriquer qu'une 2
    couches. On monte parce que le routage a ECHOUE, jamais parce que le plan
    l'autorise : le plan plafonne le besoin, il ne le prescrit pas.

    L'escalade est possible parce que Freerouting route sur autant de couches
    que le DSN en declare — l'empilage est une donnee d'entree, pas une decision
    du routeur. Mesure du 2026-08-21 : board 4 couches -> DSN
    ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'].

    ⚠️ Le budget vaut pour l'APPEL ENTIER, escalade comprise : chaque palier
    recoit le temps RESTANT. Sans cela, l'escalade multiplierait le budget par
    le nombre de paliers — exactement le defaut corrige plus haut au niveau de
    la cascade.

    Garde : tests/test_stackup_escalade.py.
    """
    try:
        pcb_bytes = base64.b64decode(req.kicad_pcb_b64)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid base64: {exc}") from exc

    deadline = _now() + req.timeout_s
    meilleur: Optional[RouteAutoResponse] = None
    # Denominateur de la mesure : les nets routables du board d ENTREE. Le
    # recalculer sur la sortie fausserait le pourcentage.
    nets_routables = _count_routable_nets(pcb_bytes)

    for palier in _layer_ladder(req.layers):
        restant = _remaining_budget_s(deadline)
        if meilleur is not None and not _budget_suffisant(restant):
            logger.info(
                "route_auto: escalade interrompue avant %d couches — budget epuise",
                palier,
            )
            break

        # ⚠️ Les plans sont coules APRES le routage, pas ici. Coules avant, le
        # routeur voyait la zone GND, en deduisait « GND est pris en charge » et
        # cessait de router ce net — alors que le plan ne peut PAS atteindre les
        # pattes d un LQFP-48. Ni le plan ni le routeur ne faisait le travail :
        # 3 connexions manquantes, qu aucun levier ne resorbait.
        etendu = _expand_stackup(pcb_bytes, palier)

        # ⚠️ Reserver AVANT de router : apres, il n y a plus de place. Mesure
        # du 2026-08-23 — 504 candidats essayes autour des pattes orphelines
        # du LQFP-48, aucun ne passe, le voisinage comptant 182 obstacles
        # (les pistes de signal). Les vias sont declares dans le DSN pour que
        # le routeur travaille autour, puis reposes apres le round-trip
        # Specctra, qui efface tout ce qui le precede.
        global _VIAS_RESERVES
        _VIAS_RESERVES = _vias_a_reserver(etendu) if _NETS_CONFIES_AU_PLAN else []

        tentative = RouteAutoRequest(
            kicad_pcb_b64=base64.b64encode(etendu).decode("ascii"),
            layers=req.layers,
            timeout_s=max(restant, _MIN_LEVEL_BUDGET_S),
        )
        res = _route_auto_once(tentative)

        # Reparation ciblee : les broches fine-pitch que le plan n atteint pas
        # et que le routeur n a pas routees, faute de les croire a sa charge.
        if res.kicad_pcb_b64 and not res.skipped:
            # Le routeur a relie toutes les broches par des pistes, fine-pitch
            # comprises. Les plans arrivent maintenant en COMPLEMENT — du cuivre
            # et du blindage en plus, sans responsabilite de connexion.
            #
            # Mesure du 2026-08-22 (idee de l utilisateur, verifiee) :
            #     routage sans plan   -> 0 manquante, 181 segments, 8 vias
            #     plans ajoutes apres -> 0 manquante, zones sur F.Cu ET B.Cu
            #
            # Le prix est un peu plus de cuivre pose (181 segments contre 105) :
            # mince, face a une carte qui passe le DRC.
            # Reposer les vias reserves : le round-trip Specctra les a effaces,
            # mais le routeur a travaille AUTOUR de leurs positions.
            route = _reposer_vias_reserves(base64.b64decode(res.kicad_pcb_b64),
                                           _VIAS_RESERVES)
            avec_plans = _add_ground_planes(route)
            # Un plan non rempli n est qu un contour : sans cuivre, aucun blindage.
            avec_plans = _fill_zones(avec_plans)
            # Filet : si une broche reste orpheline malgre tout, on la sort par
            # un via. Le plus souvent il n y a rien a reparer.
            final = _fanout_pads_isolees(avec_plans)
            # Puis la couture : ce que le fanout n a pas pu sortir tient
            # souvent a un ilot de plan detache par une piste, pas a la
            # pastille elle-meme.
            final = _recoudre_les_ilots(final)
            # Puis les ILOTS DE PLAN : les pistes de signal decoupent le
            # cuivre de la face composants, et aucune pastille n est en cause.
            final = _recoudre_les_zones(final)

            # ⚠️ REPLI — la séquence « le plan prend GND » est préférée, mais
            # elle laisse parfois des broches fine-pitch non reliées : le via
            # d'échappement ne rentre pas (0,318 mm libres pour 0,500 exigés).
            # Une carte non connectée ne part pas en fabrication — on refait
            # alors le routage en INCLUANT GND, qui relie tout par des pistes.
            # Plus de cuivre, mais une carte complète.
            if _NETS_CONFIES_AU_PLAN and _gnd_orphelines(final):
                logger.warning(
                    "plan de masse : %d broche(s) GND non reliée(s) — "
                    "repli sur un routage incluant GND", _gnd_orphelines(final))
                secours = _router_en_incluant_gnd(etendu, req, restant)
                if secours is not None:
                    final = secours

            res.kicad_pcb_b64 = base64.b64encode(final).decode("ascii")
            res.layers = _count_copper_layers(final)
            res.via_count = _count_vias(final)
            res.track_length_mm = _track_length_mm(final)

            # ⚠️ Ne RE-MESURER que si le fanout a ajoute des connexions. Couler
            # un plan ne change pas ce que le routeur a accompli — le plan ajoute
            # du cuivre sur un net deja relie, il ne peut que completer. Ecraser
            # le pourcentage du moteur par une nouvelle mesure dans ce cas, c est
            # remplacer un chiffre etabli par un chiffre recalcule sans raison.
            if final is not avec_plans:
                res.routed_percent = _measured_routed_percent(final, nets_routables)

            # ⚠️ Dernier mot au DRC, qui voit le board LIVRE — plans coules,
            # reparations faites. La mesure du moteur, elle, regarde le board
            # juste apres le routeur et ignore les nets confies au plan.
            res.routed_percent = _percent_verifie(
                final, res.routed_percent, nets_routables
            )

        logger.info(
            "route_auto: palier %d couches -> %d%% (%s)",
            palier, res.routed_percent, res.engine or "aucun moteur",
        )

        if res.routed_percent >= 100 and not res.skipped:
            return res
        if meilleur is None or res.routed_percent > meilleur.routed_percent:
            meilleur = res

    # Aucun palier n'a atteint 100 % : on rend le MEILLEUR, jamais le dernier.
    # Un palier superieur peut faire moins bien (plus de vias, plus de conflits),
    # et livrer le dernier essai plutot que le meilleur serait une regression
    # silencieuse.
    assert meilleur is not None  # `_layer_ladder` rend toujours au moins [2]
    return meilleur

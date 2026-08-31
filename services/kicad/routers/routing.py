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
from tools.sexp_quote import unquote_keepout_values
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
# Delai du sous-processus pcbnew. Il ne mesure PAS la duree du travail — il
# attrape un pcbnew bloque.
#
# ⚠️ A 60 s, il coupait un travail d UNE SECONDE. Mesure du 2026-08-31 sur les
# boards de l A/B, machine au repos :
#
#     stitch_zones  0,7-0,8 s        fill_zones  1,3-1,4 s
#
# Et pourtant, pendant l A/B lui-meme, TROIS expirations :
#
#     couture des ilots impossible (pcbnew child timed out after 60s)
#
# La cause n est pas la duree mais la FAMINE DE CPU : un tirage de routage
# abandonne continue de tourner dans la JVM — `cancel` repond 501, on ne peut
# pas le tuer — a 400-500 % de CPU pendant que le post-traitement s execute.
# Nos propres tirages abandonnes sabotent les etapes qui les suivent, et la
# JVM execute deux jobs en parallele (verifie le 2026-08-29).
#
# Consequence mesuree : la couture n a JAMAIS tourne sur la plus grosse carte
# du banc. Le plan restait fragmente, des broches GND non reliees, et rien ne
# le disait hormis un avertissement noye — l echec est silencieux precisement
# quand la carte est grosse, c est-a-dire quand la couture est necessaire.
#
# Ralentissement observe : plus de 75x. On prend 600 s, qui absorbe largement
# cette contention tout en restant BORNE — sans borne, un pcbnew reellement
# bloque tiendrait le pipeline entier.
_PCBNEW_RUNNER_TIMEOUT_S: int = 600
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


# Reglages passes a Freerouting a l enfilement du job.
#
# ⚠️ On n envoyait RIEN, donc les defauts du serveur — dont `fanout.enabled =
# false`. Or le fanout est exactement la sequence voulue : sortir par une courte
# piste et un via les broches que le plan n atteint pas. Nous le faisions APRES
# coup (`_fanout_pads_isolees`), sur un board deja route, quand la place manque ;
# le routeur sait le faire PENDANT, quand il reste de l espace.
#
# ⚠️ MESURE DU 2026-08-28, Nucleo, meme board place, quatre conditions :
#
#     defauts (temoin)      91 %   5 manq   0 err   76 vias
#     fanout actif          91 %   5 manq   0 err   84 vias   <- aucun gain
#     via_costs 50->10      ECHEC — expiration en cascade
#     fanout + via_costs    86 %   9 manq   0 err   85 vias   <- pire
#
# Aucun reglage ne bat les defauts. Le fanout n a rien relie de plus et a pose
# huit vias supplementaires ; le cout de via abaisse fait exploser l espace de
# recherche — l API expire, le repli sous-processus aussi, et la chaine finit
# sans board. Le 50 par defaut n est pas arbitraire : il BORNE l exploration.
#
# On repasse donc aux defauts. Le mecanisme d injection reste en place : il a
# permis la mesure, et rien ne dit qu un autre reglage ne la vaudra pas.
#
# Garde : tests/test_reglages_freerouting.py.
#
# ⚠️ UN SEUL reglage est desormais impose, et il ne porte pas sur la QUALITE
# du routage mais sur son ARRET. Freerouting ne s arrete pas au bout d un
# temps : il s arrete quand il converge — ou jamais.
#
# Mesure du 2026-08-29 sur les 495 jobs du journal Freerouting :
#
#     226 422 passes au total, dont 191 695 SANS le moindre progres — 84 %
#
# Profil constant, ici `stm32-100` a 2 couches :
#
#     pass    4  score 772.19  (46 unrouted)     <- tout le travail est ici
#     pass    5  score 772.19  (46 unrouted)
#     ...  995 passes rigoureusement identiques ...
#     pass  999  score 772.19  (46 unrouted)
#
# 44 minutes dont une dizaine de secondes utiles. Et `max_passes: 9999` n est
# meme pas de nous : c est le defaut que Freerouting ecrit lui-meme dans son
# `freerouting.json` au premier demarrage.
#
# ⚠️ Le plafond NE PEUT PAS etre bas, et c est le piege. 19 % des jobs
# progressent encore apres la passe 30, certains jusqu a la 997e — et ce sont
# ceux qui finissent a UN seul net non route. Distribution du dernier progres :
#
#     <=  10 passes : 72 % des jobs
#     <=  30 passes : 81 %
#     <= 100 passes : 89 %
#
# 150 laisse une marge au-dessus des 89 % tout en divisant par ~6,7 le cout
# d un palier condamne.
#
# ⚠️ L arret sur STAGNATION serait strictement meilleur — fenetre de 150 passes
# sans progres, qui ne coupe AUCUN des 461 jobs mesures (plus grand ecart entre
# deux progres : 144 passes). Il est indisponible : `PUT /jobs/{id}/cancel`
# repond `501 Not Implemented`, et apres annulation la sortie du job repond
# `400`. Un job annule ne rend pas son routage partiel.
# ⚠️ **DECISION DE L UTILISATEUR, 2026-08-29 : ON NE TOUCHE PAS AUX REGLAGES
# DE FREEROUTING.** Il fait son travail — six cartes du banc sur sept routent a
# 100 % en 30 a 45 secondes. Une carte qui lui coute une heure ne prouve pas
# qu il est mal regle : elle dit que ce qu on lui DONNE est mauvais.
#
# Ce qui a ete mesure et reste vrai (pour ne pas le remesurer) :
#   - 84 % des passes ne produisent aucun progres (495 jobs) ;
#   - le champ `max_passes` du job est stocke mais IGNORE par le routeur —
#     job a 150, routeur a la passe 571 ; les jobs a 9999 s arretaient a 999.
#     Un reglage accepte n est pas stocke, un reglage stocke n est pas applique.
# Ces mesures decrivent un SYMPTOME. La cause est en amont, dans le board.
_REGLAGES_FREEROUTING: Optional[dict] = None


# Passes consecutives sans progres au-dela desquelles on cesse d ATTENDRE un
# job. Sur 461 jobs mesures, le plus grand ecart entre deux progres est de 144
# passes : 150 ne coupe aucun job vivant. On coupe l ATTENTE, jamais le job —
# `cancel` repond 501 et la JVM execute deux jobs en parallele (verifie le
# 2026-08-29) : le palier suivant demarre pendant que le cadavre finit seul.
_STAGNATION_PASSES: int = 150

# Au-dela de ce nombre de nets non routes, un palier est CONDAMNE : on le juge
# sur une fenetre courte au lieu d attendre 150 passes.
#
# ⚠️ Calibration sur 299 jobs reels, a la passe 20 :
#
#     progressent APRES la passe 20 : 101 jobs, unrouted@20 va jusqu a 22
#     morts avant la passe 20       : 198 jobs, unrouted@20 des 1
#
# La separation n est PAS parfaite EN BAS — un job a 1 net non route peut etre
# mort comme il peut aboutir 900 passes plus tard, et c est pourquoi un seuil
# bas tuerait des jobs vivants. EN HAUT elle est nette : au-dela de 22, aucun
# des 101 progresseurs tardifs. 25 laisse la marge.
_MORT_AU_DELA_DE: int = 25

# Fenetre appliquee a un palier condamne. 30 passes ~ 75 s a 2,5 s la passe,
# contre ~375 s pour la fenetre longue.
_STAGNATION_PASSES_CONDAMNE: int = 30


# En dessous de ce nombre de nets non routes, ON N ABANDONNE JAMAIS L ATTENTE.
#
# ⚠️ Regression mesuree en production le 2026-08-29 sur `arduino-uno` :
#
#     Freerouting fige (162 passes sans progres, 1 non route)
#     palier 2 couches fige a ~93% — escalade immediate
#
# Cette carte routait 100 % A 2 COUCHES dans les deux bancs precedents : le
# routeur finit par router ce dernier net APRES la fenetre de 150 passes. La
# detection la faisait monter a 4 couches sans necessite — une couche de plus
# a fabriquer, pour rien.
#
# Le cout d attendre est BORNE par `_PLAFOND_ATTENTE_S`, jamais par le nombre
# de passes : le gain est un palier de couches en moins sur la carte LIVREE.
#
# ⚠️ Seuil ramene de 5 a 2 sur avis de Grok, et il a raison : sur une carte a
# 15 nets, 5 restants font 33 % — ce n est pas « presque fini », c est
# peut-etre un vrai mur a 2 couches. Les rattrapages tardifs mesures finissent
# a UN net. Entre 3 et 25, la fenetre longue s applique ; elle suffit la.
_PRESQUE_FINI: int = 2

# ⚠️ Plafond de temps, INDEPENDANT du recit de Freerouting. « Ne jamais
# couper » est juste sur le critere des PASSES, faux sur l horloge : a 2,5 s la
# passe (stm32-100), 999 passes valent 40 minutes — on recreerait le plafond
# qu on vient d abattre. Les rattrapages tardifs mesures tiennent largement
# dessous : 999 passes a 0,15 s font 2,5 min sur arduino-uno.
_PLAFOND_ATTENTE_S: float = 300.0


def _fenetre_stagnation(unrouted: int) -> int:
    """Passes plates a tolerer, selon ce qu il reste a router.

    Avis de Grok, verifie : le compteur de passes seul ne suffit pas — c est
    le NOMBRE de nets non routes qui distingue un cadavre d un job qui
    progresse encore. Un `unrouted` inconnu (0) ne raccourcit rien : sans
    mesure on attend, on n abandonne pas a l aveugle.
    """
    if unrouted <= _PRESQUE_FINI:
        # 0 inclus : `unrouted` inconnu, on ne coupe pas a l aveugle.
        return 0
    return (_STAGNATION_PASSES_CONDAMNE if unrouted > _MORT_AU_DELA_DE
            else _STAGNATION_PASSES)

# Marge sur la cadence observee avant de declarer un routeur MUET. Trois
# passes d ecart : en dessous on couperait un job dont la cadence est
# simplement irreguliere.
_MARGE_CADENCE: float = 3.0


def _numero_de_passe(lignes: list, short_name: str) -> int:
    """Numero de la DERNIERE passe journalisee par ce job, 0 si aucune.

    Distinguer « lent » de « muet » exige de suivre le NUMERO de passe, pas le
    pourcentage : un routeur qui avance sans progresser reste vivant.
    """
    return next((int(p) for j, p, _, _ in reversed(lignes) if j == short_name), 0)


def _routeur_muet(silence_s: float, cadence_s: float, passes_vues: int) -> bool:
    """Le routeur a-t-il cesse de journaliser ?

    ⚠️ Le garde-fou d origine mesurait le temps SANS PROGRES et coupait un
    routeur qui parlait, mais lentement. Mesure du 2026-08-31, `stm32-100`,
    deux tirages independants : « 42 passes sans progres, 3 non routes,
    plafond de temps » — un board a TROIS nets du but, abandonne parce qu une
    passe y dure ~7 s et que 300 s n en couvrent que 42.

    Le compteur de PASSES s adapte tout seul a la taille de la carte ; le
    chronometre, non. On rend donc au chronometre son seul role legitime :
    detecter le SILENCE.

    ⚠️ Le seuil suit la cadence mesuree, sans quoi on recreerait le defaut de
    la Nucleo — un tirage abandonne apres UNE passe sur un board ou une passe
    dure plusieurs minutes.

    ⚠️ Moins de deux passes vues : aucune cadence n est estimable. « Je n ai
    pas pu mesurer » n est pas « il est mort » — on n abandonne pas.
    """
    if passes_vues < 2 or cadence_s <= 0:
        return False
    return silence_s > max(_PLAFOND_ATTENTE_S, _MARGE_CADENCE * cadence_s)


# Autorise-t-on la detection de stagnation a ABANDONNER un tirage ?
#
# ⚠️ Vrai en temps normal, et c est ce qui rend l escalade rapide : sans elle,
# un job condamne coute 44 minutes de politesse. Mis a Faux pour une DERNIERE
# CHANCE, quand tous les tirages ont fige et qu il ne reste RIEN a livrer.
#
# Mesure du 2026-08-31, `nucleo-f401` : six tirages figes d affilee
# (43, 79, ?, 77, 77, 62 %), aucun conserve — `RoutageFige` ne transporte que
# des compteurs, jamais le board. Meme scenario la veille sur `stm32-100` :
# « Tous les routeurs ont echoue » alors que des tirages avaient touche 96 %.
#
# Mieux vaut attendre un tirage jusqu au bout que rendre une carte vide.
# ⚠️ Repli quand `_NETS_CONFIES_AU_PLAN` est momentanement vide — il l est a
# l interieur de `_router_en_incluant_gnd`. Sans ce repli, la regle « ce qui
# manque est confie au plan » deviendrait inerte au pire moment.
_NETS_DE_PLAN_CONNUS: frozenset = frozenset({"GND", "AGND", "DGND", "GNDA"})

_ABANDON_AUTORISE: bool = True


def _fenetre_effective(fenetre: int, autorise: bool) -> int:
    """La fenetre de passes, ou 0 quand l abandon est desarme.

    Zero signifie « ne coupe pas sur les passes ». Le detecteur de SILENCE
    reste actif en toutes circonstances : un routeur muet est une panne, pas
    une lenteur, et il ne doit jamais tenir le budget.
    """
    return fenetre if autorise else 0


def _faut_couper(plat: int, fenetre: int, muet: bool) -> bool:
    """Faut-il cesser d attendre ce tirage ?

    ⚠️ `fenetre == 0` veut dire « ne coupe pas » — presque fini, ou compte de
    nets inconnu. L ancienne condition coupait quand meme par l horloge :
    l intention de `_fenetre_stagnation` etait annulee par la ligne qui
    l utilisait. Seul le silence passe outre, et c est une panne, pas une
    lenteur.
    """
    if fenetre and plat >= fenetre:
        return True
    return muet


# Ou vit le journal de Freerouting. Meme conteneur que la JVM ; le chemin suit
# `--user_data_path`, fixe par notre entrypoint.
_FREEROUTING_LOG = Path(os.environ.get(
    "FREEROUTING_LOG", "/tmp/freerouting/freerouting.log"))


class RoutageFige(RuntimeError):
    """Le routeur repete des passes identiques : le palier est prouve mort.

    Porte l estimation du pourcentage atteint, lue dans le journal — c est la
    PREUVE d echec du palier que la regle utilisateur exige avant d escalader.
    """

    def __init__(self, unrouted: int, nets: int):
        self.unrouted = unrouted
        self.nets = nets
        self.routed_percent = (
            max(0, round(100 * (nets - unrouted) / nets)) if nets > 0 else 0)
        super().__init__(
            f"routage fige : {unrouted} net(s) non route(s) apres "
            f"{_STAGNATION_PASSES} passes sans progres")


# ⚠️ L IDENTIFIANT DE LIGNE A DEUX FORMES, et n avoir verifie que la premiere
# a rendu la detection inerte sur toute une categorie de cartes :
#
#     [AC4604]           job seul
#     [E8A788\BAD9AA]    session ANTISLASH job
#
# Mesure du 2026-08-30 : sur `nucleo-f401`, les 27 lignes de passe portaient
# la forme composee. Aucune coupure n a eu lieu, les tirages ont dure 17 a
# 24 minutes, le budget s est epuise et la carte est sortie a 80 % avec
# 16 connexions manquantes — contre 100 % au banc de reference.
#
# Le job est le DERNIER segment : on l ancre sur la fin, jamais sur la
# longueur totale du crochet.
#
# ⚠️ ET LE SUFFIXE DU SCORE A LUI AUSSI DEUX FORMES :
#
#     (46 unrouted)
#     (51 unrouted and 1 violation)
#
# Exiger la parenthese fermante juste apres « unrouted » ne reconnaissait
# aucune ligne du journal reel de la Nucleo. Troisieme variation de format
# trouvee sur CE MEME journal : la regle est de valider le parseur contre le
# fichier reel a chaque fois, jamais contre une fixture ecrite de memoire.
_LIGNE_PASSE_RE = re.compile(
    r"\[[^\]]*?([0-9A-F]{6})\].*pass #(\d+)"
    r".*score of ([\d.]+) \((\d+) unrouted")


def _passes_sans_progres(log_text: str, short_name: str) -> int:
    """Passes consecutives du job `short_name` sans le moindre progres.

    Progres = baisse des nets non routes OU changement de score. Un journal
    illisible ou muet rend 0 : sans mesure on ATTEND, on n abandonne pas a
    l aveugle.

    ⚠️ Filtrer par job est OBLIGATOIRE : la JVM execute deux jobs en
    parallele, et compter les passes d un autre condamnerait un job vivant.
    """
    serie = []
    for m in _LIGNE_PASSE_RE.finditer(log_text):
        if m.group(1) != short_name:
            continue
        serie.append((int(m.group(2)), float(m.group(3)), int(m.group(4))))
    if len(serie) < 2:
        return 0
    serie.sort()
    plat = 0
    for i in range(1, len(serie)):
        if (serie[i][2] < serie[i - 1][2]
                or abs(serie[i][1] - serie[i - 1][1]) > 1e-9):
            plat = 0
        else:
            plat += 1
    return plat


def _route_with_freerouting_api(
    pcb_bytes: bytes,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    nets_routables: int = 0,
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
        # ⚠️ La garde portait sur les seuls vias reserves : sans via, les
        # pistes a proteger n auraient jamais ete injectees.
        if _VIAS_RESERVES or _PISTES_A_PROTEGER:
            dsn_path.write_text(_injecter_wiring(
                dsn_path.read_text(encoding="utf-8", errors="replace"),
                [(v["via_x"], v["via_y"]) for v in _VIAS_RESERVES],
                _NETS_CONFIES_AU_PLAN[0] if _NETS_CONFIES_AU_PLAN else "GND",
                pistes=_PISTES_A_PROTEGER,
            ), encoding="utf-8")

        session = _api("POST", f"{pre}/sessions/create", {})
        session_id = session["id"]

        # ⚠️ On enfilait le job SANS le moindre reglage, donc avec les defauts
        # de Freerouting. Interroges le 2026-08-28 (`GET /jobs/<id>`), ils
        # disent beaucoup :
        #
        #     fanout.enabled = false      l echappement natif est ETEINT
        #     scoring.via_costs = 50      un changement de couche coute 50
        #     scoring.plane_via_costs = 5
        #
        # Le second explique la repartition mesuree sur la Nucleo — F.Cu 243
        # segments, In2.Cu 5 — alors que les couches internes sont libres : le
        # routeur evite les couches internes parce qu y ALLER coute un via.
        #
        # `_REGLAGES_FREEROUTING` vaut None par defaut : aucun changement de
        # comportement tant qu on n a pas mesure.
        charge = {"session_id": session_id}
        if _REGLAGES_FREEROUTING:
            charge["router_settings"] = _REGLAGES_FREEROUTING
        job = _api("POST", f"{pre}/jobs/enqueue", charge)
        job_id = job["id"]

        _api(
            "POST",
            f"{pre}/jobs/{job_id}/input",
            _freerouting_input_payload(dsn_path.read_bytes()),
        )

        _api("PUT", f"{pre}/jobs/{job_id}/start", {})

        deadline = time.time() + timeout_s
        # Deux horloges distinctes, et c est tout le correctif : l une suit le
        # SILENCE (aucune passe nouvelle), l autre la cadence pour en calibrer
        # le seuil. Le temps sans PROGRES ne coupe plus rien — c est le
        # compteur de passes qui s en charge, et lui s adapte a la carte.
        premiere_passe_a = None
        depart_silence = time.time()
        derniere_passe = 0
        dernier_unrouted = 0
        short_name = str(job.get("short_name", "")).upper()
        while time.time() < deadline:
            status = _api("GET", f"{pre}/jobs/{job_id}")
            state = status.get("state", "")
            if _freerouting_job_done(state):
                break
            if _freerouting_job_failed(state):
                raise RuntimeError(f"Freerouting API job {state}")
            # ⚠️ COUPER L ATTENTE d un job fige — pas le job, qu on ne peut
            # pas tuer (`cancel` 501). Sur stm32-100, tout le travail est fait
            # a la passe 4 et 995 passes identiques suivent : 44 minutes de
            # politesse. Le journal est la seule fenetre sur l interieur ; s il
            # est illisible, on retombe sur l attente classique.
            if short_name and _FREEROUTING_LOG.is_file():
                try:
                    plat = _passes_sans_progres(
                        _FREEROUTING_LOG.read_text(encoding="utf-8",
                                                   errors="replace"),
                        short_name)
                except Exception:
                    plat = 0
                derniere = _LIGNE_PASSE_RE.findall(
                    _FREEROUTING_LOG.read_text(encoding="utf-8",
                                               errors="replace"))
                unrouted = next((int(u) for j, _, _, u in reversed(derniere)
                                 if j == short_name), 0)
                fenetre = _fenetre_effective(
                    _fenetre_stagnation(unrouted), _ABANDON_AUTORISE)
                # ⚠️ DEUX DECISIONS DISTINCTES, ET C EST LA CAUSE DE MES TROIS
                # ERREURS SUCCESSIVES sur ce mecanisme (diagnostic de Grok) :
                # « cesser d esperer ce tirage » n est pas « prouver que le
                # palier de couches ne suffit pas ». Un plateau a 93 % avec UN
                # net restant n est pas une preuve d empilement insuffisant —
                # c est un routeur qui n a pas fini.
                #
                # Le critere des PASSES ne coupe donc plus quand il ne reste
                # presque rien ; seul l HORLOGE tranche alors, et elle tranche
                # toujours. Sans elle, « ne jamais couper » recreerait les
                # 40 minutes sur une carte a 2,5 s la passe.
                # ⚠️ Le plafond compte le temps SANS PROGRES, pas le temps
                # total. Compte depuis le debut, il coupe un routage
                # legitimement long — et il l a fait : un tirage de la Nucleo a
                # ete abandonne apres UNE passe, sur un board de 61 nets ou une
                # passe dure plusieurs minutes. « 3 % » n etait pas un verdict,
                # c etait un abandon premature. Mon propre commentaire disait
                # deja « sans progres » ; le code, non.
                if unrouted and unrouted != dernier_unrouted:
                    dernier_unrouted = unrouted
                passe = _numero_de_passe(derniere, short_name)
                if passe > derniere_passe:
                    if premiere_passe_a is None:
                        premiere_passe_a = time.time()
                        premiere_passe = passe
                    derniere_passe = passe
                    depart_silence = time.time()
                # Cadence MESUREE : secondes par passe depuis la premiere vue.
                vues = derniere_passe - premiere_passe + 1 if premiere_passe_a else 0
                cadence = ((time.time() - premiere_passe_a) / vues
                           if premiere_passe_a and vues > 0 else 0.0)
                muet = _routeur_muet(time.time() - depart_silence, cadence, vues)
                if _faut_couper(plat, fenetre, muet):
                    logger.warning(
                        "Freerouting fige (%d passes sans progres, %d non "
                        "routes%s) — attente abandonnee, le job finit seul",
                        plat, unrouted,
                        ", routeur muet (%.0fs sans passe, cadence %.1fs)"
                        % (time.time() - depart_silence, cadence) if muet else "")
                    # ⚠️ MEMORISER avant de lacher : le job continue dans la
                    # JVM et finira seul. Sans cette trace, son cuivre est
                    # perdu — c est ce qui a fait sortir `stm32-100` en ECHEC
                    # alors qu un tirage avait atteint 72 %.
                    _JOBS_ABANDONNES.append({
                        "job_id": job_id, "pre": pre,
                        "percent": max(0, round(
                            100 * (nets_routables - unrouted) / nets_routables))
                        if nets_routables > 0 else 0,
                    })
                    raise RoutageFige(unrouted=unrouted,
                                      nets=nets_routables)
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


# Jobs de routage abandonnes par la detection de stagnation. Ils CONTINUENT de
# tourner dans la JVM — `PUT /jobs/{id}/cancel` repond 501, on ne peut pas les
# tuer — et finissent seuls. Leur cuivre existe donc, et personne n allait le
# chercher.
_JOBS_ABANDONNES: list[dict] = []


def _recuperer_jobs_abandonnes(pcb_bytes: bytes) -> Optional[bytes]:
    """Board du meilleur job abandonne ayant fini seul, ou None.

    ⚠️ Mesure du 2026-08-31, `stm32-100` : trois tirages figes a 68, 54 et
    72 %, tous jetes, et la carte sort en ECHEC total. Le board a 72 % existait.

    ⚠️ La « derniere chance » livree le matin meme n a PAS joue : elle est
    conditionnee par `_budget_suffisant(...)`, or quand tous les tirages ont
    fige le budget est DEJA consomme. Un filet de securite qui exige les
    ressources que la situation vient d epuiser ne sert a rien.

    Ici le cout est nul : on ne relance aucun routage, on demande sa sortie a
    un job qui a fini de son cote. Une requete HTTP.

    ⚠️ Tout echec est avale et rend None : le job peut avoir disparu, la JVM
    avoir redemarre, la sortie etre vide. Aucun de ces cas ne doit remplacer un
    echec franc par une exception.
    """
    meilleur_board = None
    meilleur_pct = -1
    for job in _JOBS_ABANDONNES:
        try:
            statut = _api("GET", "%s/jobs/%s" % (job["pre"], job["job_id"]))
            if not _freerouting_job_done(str(statut.get("state", ""))):
                continue
            sortie = _api("GET", "%s/jobs/%s/output" % (job["pre"], job["job_id"]))
            ses_b64 = (sortie.get("data") or sortie.get("output_file")
                       or sortie.get("ses") or "")
            if not ses_b64:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                ses = Path(tmp) / "b.ses"
                ses.write_bytes(base64.b64decode(ses_b64))
                board = _specctra_roundtrip(pcb_bytes, ses)
            if board and job.get("percent", 0) > meilleur_pct:
                meilleur_board, meilleur_pct = board, job.get("percent", 0)
        except Exception as exc:
            logger.debug("job abandonne %s irrecuperable (%s)",
                         job.get("job_id"), exc)
    if meilleur_board is not None:
        logger.warning(
            "route_auto: aucun tirage n a abouti — board RECUPERE d un job "
            "abandonne a ~%d%%, qui avait fini seul dans la JVM", meilleur_pct)
    return meilleur_board


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


# Tirages de routage a CHAQUE palier de couches.
#
# Methode demandee par l utilisateur le 2026-08-28 : a 2 couches on tire et on
# re-tire ; si cela ne suffit pas on passe a 4 et on re-tire ; etc., en gardant
# toujours le meilleur.
#
# ⚠️ L escalade ne faisait qu UN tirage par palier. Freerouting est pourtant
# stochastique : sur le meme board place de la Nucleo, trois executions ont
# donne 65 %, 77 % et 91 %. Un palier juge insuffisant ne l etait peut-etre que
# ce tirage-la — et on montait d une couche pour rien, ce qui coute plus cher a
# fabriquer qu un re-tirage.
#
# ⚠️ TROIS TIRAGES, et la mesure a failli me faire ecrire le contraire.
# Nucleo, 2026-08-28, un run complet, trois tirages par palier :
#
#     palier 2 :  62, 62, 62      identiques
#     palier 4 :  58, 55, 68      TREIZE points d ecart
#     palier 6 :  62, 55, 56
#
# J avais conclu « Freerouting est deterministe » sur le seul palier 2, ou les
# trois tirages coincidaient. C etait faux, et c est exactement l erreur que
# cette base de code documente partout : conclure d un echantillon.
#
# Les tirages paient : le meilleur resultat de ce run — 68 % — vient du
# TROISIEME tirage du palier 4. Sans lui la carte sortait a 62 %.
#
# ⚠️ La dispersion mesuree plus tot (81, 74, 79 %) melangeait deux effets, le
# tirage et le chemin d escalade. Celle-ci, a palier constant, ne mesure que le
# routeur.
_TIRAGES_ROUTAGE_PAR_PALIER = 3

# Tirages consecutifs sans le moindre gain que l on tolere avant de cesser
# d escalader. Deux paliers entiers a plat : en dessous, deux tirages
# malchanceux au meme palier couperaient l escalade avant d avoir essaye le
# palier suivant.
_TOLERANCE_SANS_GAIN = 2 * _TIRAGES_ROUTAGE_PAR_PALIER


def _paliers_avec_tirages(echelle: list, tirages: int) -> list:
    """Repete chaque palier `tirages` fois, dans l ordre.

        [2, 4], 3  ->  [2, 2, 2, 4, 4, 4]

    L ordre compte : on epuise 2 couches AVANT de payer 4, une carte a moins de
    couches coutant moins cher a fabriquer.

    ⚠️ On repete le palier dans l ECHELLE plutot que de restructurer la boucle,
    chemin critique de plus de cent lignes. Le corps existant garde deja le
    meilleur sur le couple (pourcentage, erreurs) et rend la main des qu il
    tient 100 % sans erreur : les tirages surnumeraires ne sont jamais payes
    quand le premier suffit.

    Garde : tests/test_tirages_par_palier.py.
    """
    if tirages <= 1:
        return list(echelle)
    return [palier for palier in echelle for _ in range(tirages)]


def _palier_meilleur(candidat: tuple, reference: tuple) -> bool:
    """`candidat` bat-il `reference` ? Chaque tuple vaut ``(percent, erreurs)``.

    ⚠️ On classait sur le seul `routed_percent`. Deux paliers a 93 % etaient
    donc juges equivalents alors que l un passe le DRC et l autre non. Mesure
    du 2026-08-28 sur `stm32-baseline` :

        6 couches   93 % route   1 manquante   0 erreur
        2 couches   93 % route   1 manquante   1 ERREUR

    Le defaut existait deja ; il ne se voyait pas tant qu on essayait tous les
    paliers et qu on tombait par chance sur le bon.

    ⚠️ Le pourcentage PRIME : les erreurs departagent, elles ne renversent pas.
    Une carte incomplete n est pas rattrapee par un DRC propre.

    ⚠️ Un resultat identique n est PAS un gain, sans quoi l arret anticipe ne se
    declencherait jamais.

    Garde : tests/test_palier_choisi_sur_les_erreurs.py.
    """
    return candidat[0] > reference[0] or (
        candidat[0] == reference[0] and candidat[1] < reference[1])


# Sous ce pourcentage, re-tirer le meme palier est un pari perdu : on monte.
#
# ⚠️ Mesure du 2026-08-29, stm32-100 (100 composants, 208x156 mm). Trois
# tirages a 2 couches ont consomme les 3600 s du budget :
#
#     tirage 1  ->  60 %      28 min
#     tirage 2  ->  70 %      27 min
#     tirage 3  ->   0 %      « budget epuise avant le Niveau 4 »
#
# La carte n a JAMAIS essaye 4 couches — le seul levier qui lui manquait.
# Le budget n etait pas trop court : il a ete depense au mauvais endroit.
#
# Le seuil se DEDUIT de l ecart mesure entre tirages, il n est pas choisi.
# Sur le meme board place de la Nucleo, trois executions de Freerouting ont
# donne 65, 77 et 91 % : 26 points au plus. Un palier a 70 % ne peut donc pas
# atteindre 100 % par re-tirage, quel qu en soit le nombre. A 91 %, si — et
# ce rattrapage-la est mesure, on ne coupe pas dessus.
#
#     100 - 26 = 74      ->  80 garde une marge sans couper un rattrapage reel
#
# ⚠️ Ceci ne remplace PAS les re-tirages, contrairement au partage de budget
# essaye le 2026-08-28 (tous les paliers a 0 %, revert). Les tirages restent
# entiers ; seuls ceux d un palier hors d atteinte sont abandonnes.
_SEUIL_REDRAW_PCT: int = 80


def _tirages_epuises_au_palier(meilleur_pct: int) -> bool:
    """Faut-il abandonner les tirages restants de ce palier et monter ?

    Un ZERO ne declenche rien : « 0 % (aucun moteur) » n est pas un verdict de
    routage mais une panne — Freerouting injoignable, budget epuise avant le
    repli. Monter d une couche sur une panne serait payer une couche pour un
    defaut d infrastructure. On re-tire au meme palier.

    Garde : tests/test_escalade_precoce.py.
    """
    return 0 < meilleur_pct < _SEUIL_REDRAW_PCT


# Au-dessus de ce pourcentage, QUITTER le palier est le pari perdant : on
# accorde des tirages supplementaires avant d escalader.
#
# ⚠️ Symetrique exact de `_SEUIL_REDRAW_PCT` (80), qui refuse de RE-TIRER un
# palier hors d atteinte. Il lui manquait son jumeau — refuser de QUITTER un
# palier a portee — et cela s est paye, mesure du 2026-08-30 sur `stm32-100`,
# meme board place, meme code, deux runs :
#
#     run gagnant   2 couches : fige, 99 %, puis 100 %              1810 s
#     run perdant   2 couches : fige, 96 %, 99 %
#                   puis 4 couches : 87 %, puis 0 %, budget mort    4290 s
#
# Le run gagnant a gagne au TROISIEME tirage du MEME palier. Le perdant avait
# le meme 99 % en main, a quitte le palier, est redescendu a 87 % en payant une
# couche de plus, puis a tue son budget :
#
#     monter d une couche  ->  2400 s pour DEGRADER de 12 points
#     un tirage de plus    ->   600 s, et le seul 100 % obtenu
#
# ⚠️ Le seuil n est pas choisi : la preuve porte sur 99 %, on l etend a 97 %,
# soit deux nets sur les 79 de cette carte. Rien de mesure ne soutient plus
# bas — entre 80 et 97 le comportement reste celui d avant.
#
# ⚠️ Et une couche de plus n est pas neutre : une carte 4 couches coute plus
# cher a fabriquer. On ne la vend que sur preuve, jamais sur impatience.
_SEUIL_PALIER_A_PORTEE: int = 97

# ⚠️ BORNE OBLIGATOIRE. Sans elle, une carte qui plafonne a 99 % re-tirerait
# sans fin et ne verrait jamais 4 couches — on recreerait a l autre extremite
# le defaut du 2026-08-29, ou stm32-100 brulait tout son budget a 2 couches.
_TIRAGES_BONUS_A_PORTEE: int = 2


def _tirages_bonus(meilleur_pct: int) -> int:
    """Tirages supplementaires a accorder AVANT de quitter ce palier.

    Un ZERO n en recoit aucun : « 0 % (aucun moteur) » est une panne, pas un
    verdict de routage. Un palier hors d atteinte non plus — il est deja
    abandonne par `_tirages_epuises_au_palier`.

    Garde : tests/test_palier_a_portee.py.
    """
    if meilleur_pct >= _SEUIL_PALIER_A_PORTEE:
        return _TIRAGES_BONUS_A_PORTEE
    return 0


def _escalade_peut_aider(percent_moteur: int, erreurs: int,
                         manquants: Optional[set] = None) -> bool:
    """Ajouter des couches peut-il encore servir a quelque chose ?

    ⚠️ Non quand le ROUTEUR annonce 100 % sur un board propre. Il a tout relie
    par des pistes ; l ecart restant vient de NOTRE verification, qui regarde
    le board livre et compte un net confie au PLAN — GND, qui n est pas route
    mais COULE. Du cuivre supplementaire n y change rien, par construction.

    Mesure du 2026-08-31, `arduino-uno` : 93 % a 2, 4 puis 6 couches, moteur a
    100 % et un seul net incomplet (GND) a chaque palier. Douze minutes
    d escalade pour zero gain — et une carte 6 couches proposee la ou 2
    suffisent, alors qu elle coute sensiblement plus cher a fabriquer.

    L escalade existe pour donner de la place a un routeur qui n y arrive pas.
    Elle n a aucun sens face a un routeur qui a fini.

    ⚠️ On continue en revanche si le board porte des ERREURS : une violation de
    fabricabilite (clearance, largeur) peut, elle, se resoudre avec plus
    d espace — contrairement a une pastille de plan orpheline.

    Garde : tests/test_escalade_inutile.py.
    """
    if erreurs > 0:
        return True
    # ⚠️ REGLE DEMANDEE PAR L UTILISATEUR (2026-08-31), et mieux fondee que la
    # precedente, qui ne regardait que « le moteur annonce-t-il 100 % » :
    #
    #     il manque du GND     -> le plan ne l atteint pas   -> PAS d escalade
    #     il manque du SIGNAL  -> le routeur manque de place -> escalade
    #
    # Un net confie au PLAN n est pas route par des pistes : il est COULE. Du
    # cuivre supplementaire ne l atteint pas davantage. Preuve mesuree sur
    # `arduino-uno` : 93 % a 2, 4 puis 6 couches, moteur a 100 % chaque fois,
    # un seul net incomplet — GND. Six tirages, douze minutes, zero gain.
    #
    # ⚠️ Le critere est CE QUI manque, jamais COMBIEN. Un seul net de signal
    # justifie l escalade ; dix nets de plan ne la justifient pas.
    if manquants:
        plan = set(_NETS_CONFIES_AU_PLAN) or _NETS_DE_PLAN_CONNUS
        if set(manquants) <= plan:
            return False
    return percent_moteur < 100


def _escalade_epuisee(sans_gain: int) -> bool:
    """Faut-il cesser d escalader apres `sans_gain` paliers consecutifs plats ?

    Ne change JAMAIS le resultat rendu : `route_auto` garde le meilleur palier,
    pas le dernier. Seul le nombre d essais diminue.

    Garde : tests/test_escalade_sans_gain.py.
    """
    return sans_gain > _TOLERANCE_SANS_GAIN


# Capacite d echappement : signaux qu un COTE de boitier peut sortir, par couche.
#
# ⚠️ Ce nombre n est pas choisi, il est ENCADRE par nos propres cartes. Mesure
# du 2026-08-29, signaux a echapper du boitier le plus charge, par cote :
#
#     carte            signaux  /cote  couches  ok   C requis
#     stm32-baseline         7    1.8      2    oui    0.88
#     esp32-baseline         7    1.8      2    oui    0.88
#     stm32-30              13    3.2      4    oui    0.81
#     arduino-uno            2    0.5      2    oui    0.25
#     nucleo-f401           37    9.2      4    oui    2.31
#     stm32-60              26    6.5      4    oui    1.63
#     stm32-100             36    9.0      2    NON    4.50
#
# Les six reussites exigent C >= 2,31 ; le seul echec exige C < 4,50. On prend
# 3,0, qui reproduit AUSSI le besoin reel de 4 couches de stm32-60 — ce que
# 3,5 et au-dela manquent. Recalibrer si une carte dement ce tableau.
#
# ⚠️ CES CHIFFRES SONT LUS SUR LE BOARD, pas sur le circuit d entree, parce
# que c est le board que le code mesure. Une premiere calibration faite sur
# `circuit.json` donnait 43 signaux a stm32-100 la ou le board en montre 36 :
# la regle passait les tests et laissait quand meme demarrer a 2 couches, soit
# exactement le cas qu elle devait attraper. Une regle se calibre sur ce
# qu elle MESURE, jamais sur une source voisine.
#
# ⚠️ Le goulot est LOCAL, pas global. Sur trois jobs Freerouting de stm32-100,
# UN SEUL composant porte 20 a 28 % des echecs de connexion, les 85 autres 2 %
# chacun : c est le LQFP-48, et sa part egale sa part des connexions. Ce n est
# donc ni la taille de la carte ni la dispersion du placement — c est
# l echappement d un boitier fine-pitch.
_CAPACITE_ECHAPPEMENT: float = 3.0

# Cotes d un boitier. Un QFP en a quatre ; on ne distingue pas les SOIC, dont
# le nombre de signaux ne fait jamais plancher.
_COTES_BOITIER: int = 4


def _signaux_a_echapper(pcb_bytes: bytes, nets_plan: set) -> int:
    """Nets SIGNAL distincts du boitier le plus charge de la carte.

    ⚠️ Les nets confies au plan ne comptent PAS : ils sortent par-dessous, pas
    lateralement. Les compter ajouterait 58 signaux sur stm32-100 et ferait
    demarrer toutes les cartes trop haut — on vendrait des couches inutiles.

    ⚠️ Un net porte par plusieurs pastilles du meme boitier compte UNE fois :
    il sort par une piste, pas par autant qu il a de pastilles.

    Un board illisible rend 0 : on ne devine pas un plancher, on n en pose pas.
    """
    try:
        blocs = re.split(r"\(footprint ", pcb_bytes.decode("utf-8", "replace"))
    except Exception:
        return 0
    def _nets(bloc):
        trouves = {m for m in re.findall(r'\(net \d+ "([^"]*)"\)', bloc)}
        trouves |= {m for m in re.findall(r'\(net "([^"]*)"\)', bloc)}
        return {x for x in trouves if x and x not in nets_plan}

    par_boitier = [_nets(b) for b in blocs[1:]]
    # ⚠️ UNE PASTILLE N EST PAS UNE LIAISON. Sur un board, chaque pastille
    # porte un net — y compris celles qui ne vont nulle part, que le
    # generateur nomme `Net-(U1-Pad3)`. Sans ce filtre, tout LQFP-48 rendait
    # ~45 signaux quel que soit le circuit, et `stm32-baseline` — qui route a
    # 2 couches — se voyait imposer 4. Un net present sur un SEUL boitier n a
    # personne a rejoindre : il n a rien a echapper.
    occurrences = {}
    for nets in par_boitier:
        for x in nets:
            occurrences[x] = occurrences.get(x, 0) + 1
    liaisons = {x for x, k in occurrences.items() if k >= 2}
    return max((len(nets & liaisons) for nets in par_boitier), default=0)


def _couches_pour_echapper(signaux: int) -> int:
    """Couches cuivre minimales pour sortir `signaux` d un seul boitier.

    Les signaux se repartissent sur les quatre cotes ; chaque cote sort
    `_CAPACITE_ECHAPPEMENT` signaux par couche. Arrondi au nombre PAIR
    superieur — un empilage impair ne se fabrique pas — plancher a 2.

    ⚠️ C est un PLANCHER, pas une prediction. Il dit ce qui est hors
    d atteinte, pas ce qui suffira : l escalade garde le dernier mot.

    Garde : tests/test_palier_plancher.py.
    """
    if signaux <= 0:
        return 2
    par_cote = signaux / _COTES_BOITIER
    couches = math.ceil(par_cote / _CAPACITE_ECHAPPEMENT)
    return max(2, couches + (couches % 2))


def _layer_ladder(plafond: int, plancher: int = 2) -> list[int]:
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
    # ⚠️ Le plancher ne peut PAS forcer au-dela du plafond du plan : un compte
    # Free est limite a 2 couches, et on ne lui vend pas une carte a 4 au
    # motif qu elle routerait mieux. Le plafond commercial prime.
    depart = max(2, min(int(plancher), borne))
    depart -= depart % 2
    paliers = [n for n in range(max(2, depart), borne + 1, 2)]
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
        # ⚠️ Sur une copie REPAREE. Un board ecrit par kicad_tools porte des
        # valeurs de keepout entre guillemets ; kicad-cli refuse alors le
        # fichier entier et rend un rapport vide, que chaque appelant lit
        # « 0 erreur ». Mesure du 2026-08-27 : vingt erreurs invisibles sur
        # l ESP32 du banc. On ne juge pas un board qu on n a pas pu ouvrir.
        pcb.write_bytes(_deguillemeter_keepout(pcb_bytes))
        # ⚠️ Le fichier PROJET doit etre a cote du board, sinon kicad-cli
        # applique ses defauts et le verdict porte sur des regles que la
        # carte ne suit pas.
        projet = _projet_kicad(pcb_bytes)
        if projet is not None:
            (Path(tmp) / "b.kicad_pro").write_text(
                json.dumps(projet), encoding="utf-8")
        r = None
        try:
            r = subprocess.run(
                [cli, "pcb", "drc", str(pcb), "--format", "json", "-o", str(rapport)],
                capture_output=True, text=True, timeout=300, check=False,
            )
            return json.loads(rapport.read_text(encoding="utf-8"))
        except Exception as exc:
            # ⚠️ ERROR, pas WARNING : les appelants lisent le dict vide comme
            # « rien a signaler ». Tant qu ils le font, ce journal est le seul
            # endroit ou l absence de verdict est visible.
            logger.error(
                "DRC indisponible (%s) — le rapport vide sera lu « 0 erreur » "
                "par les gardes de cette requete. kicad-cli: %s",
                exc, ((r.stdout or r.stderr).strip()[:200]
                      if r is not None else "non execute"))
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
    for via in vias:
        # ⚠️ Un via peut porter SON PROPRE net. Le bloc n en acceptait qu un —
        # celui du plan — ce qui convenait tant qu on ne reservait que des
        # sorties GND. Un fanout de SIGNAUX declare des vias appartenant chacun
        # a un net different : les mettre tous sur GND creerait autant de
        # courts-circuits.
        if isinstance(via, dict):
            x_nm, y_nm = via["via_x"], via["via_y"]
            net_via = via.get("net") or net
        else:
            x_nm, y_nm = via
            net_via = net
        lignes.append(
            '    (via "%s" %.1f %.1f (net %s) (type protect))'
            % (_PADSTACK_VIA, x_nm / 1000.0, -y_nm / 1000.0, net_via)
        )
    return chr(10).join(lignes)



# Board dont les pistes doivent etre PROTEGEES au palier suivant. Etat de
# module, comme `_VIAS_RESERVES` : le DSN est construit plusieurs frames plus
# bas, et le faire descendre par signature traverserait toute la cascade.
_PISTES_A_PROTEGER: Optional[bytes] = None

# ⚠️ NOM DISTINCT de `_SEGMENT_RE` (ligne ~847), qui sert a `_track_length_mm`
# et ne capture que quatre groupes. Reutiliser le nom l ecrasait EN SILENCE :
# la mesure de longueur recevait sept groupes au lieu de quatre. Attrape par
# `tests/test_routing_metrics.py`, pas par la relecture.
_SEGMENT_COMPLET_RE = re.compile(
    r"\(segment\s+\(start\s+(-?[\d.]+)\s+(-?[\d.]+)\)\s*"
    r"\(end\s+(-?[\d.]+)\s+(-?[\d.]+)\)\s*"
    r"\(width\s+([\d.]+)\)\s*"
    r'\(layer\s+"([^"]+)"\)\s*'
    # ⚠️ DEUX FORMES, et n avoir accepte que la premiere rendait ZERO fil sur
    # un vrai board : `(net 3)` chez kicad-tools et KiCad <= 9, `(net "LED5")`
    # chez pcbnew 10. Meme piege que celui deja documente dans CLAUDE.md, celui
    # qui avait produit le faux diagnostic « Freerouting perd la netlist ».
    r'\(net\s+(?:(\d+)|"([^"]*)")\)')

_NET_NOM_RE = re.compile(r'\(net\s+(\d+)\s+"([^"]*)"\)')


def _bloc_wiring_pistes(pcb_bytes: bytes) -> str:
    """Pistes du board, au format Specctra, marquees `(type protect)`.

    ⚠️ RAISON D ETRE : le DSN produit par pcbnew porte un bloc `(wiring)` VIDE
    meme sur un board entierement route — verifie sur un export reel. Le
    routeur ne DETRUIT donc pas le cuivre recu : il ne le voit jamais. C est
    pourquoi chaque palier repartait de zero, et pourquoi mon objection
    initiale (« le routage incrementiel ne sert a rien ») etait fausse : elle
    citait une mesure faite sur `kct route`, un moteur que la cascade
    n emprunte jamais (16 routages sur 16 par l API Freerouting).

    ⚠️ Unites verifiees sur l export : `(resolution um 10)`, couches `F.Cu` /
    `B.Cu` SANS guillemets, nets NOMMES en clair, coordonnees en micrometres a
    une decimale, et **Y NEGATIF** — Specctra oriente Y vers le haut, KiCad
    vers le bas. Meme transformation que `_bloc_wiring`, deja validee en
    production par les vias reserves.

    ⚠️ Un segment dont le net est INCONNU du board est ECARTE, jamais devine :
    une piste rattachee au mauvais net est un court-circuit, pas une
    approximation. Le net 0 (« pas de net ») l est aussi.
    """
    if not pcb_bytes:
        return ""
    txt = pcb_bytes.decode("utf-8", "replace")
    noms = {int(n): nom for n, nom in _NET_NOM_RE.findall(txt)}
    lignes = []
    for x1, y1, x2, y2, largeur, couche, num, nomme in _SEGMENT_COMPLET_RE.findall(txt):
        # Forme nommee : le nom est la. Forme numerotee : on cherche la
        # declaration ; absente, on ECARTE — jamais on ne devine un net.
        if nomme:
            nom = nomme
        else:
            code = int(num) if num else 0
            nom = noms.get(code) if code else None
        if not nom:
            continue
        lignes.append(
            "    (wire (path %s %.1f %.1f %.1f %.1f %.1f)"
            " (net %s) (type protect))"
            % (couche, float(largeur) * 1000.0,
               float(x1) * 1000.0, -float(y1) * 1000.0,
               float(x2) * 1000.0, -float(y2) * 1000.0, nom))
    return chr(10).join(lignes)


def _injecter_wiring(dsn_text: str, vias: list, net: str,
                     pistes: Optional[bytes] = None) -> str:
    """Ecrit les vias reserves dans le bloc `(wiring)` du DSN.

    ⚠️ pcbnew laisse ce bloc VIDE meme sur un board portant 160 segments —
    verifie le 2026-08-23. Son exporteur ne transporte pas les pistes
    existantes ; on ecrit donc nous-memes, mais seulement quelques vias.

    ⚠️ Un DSN dont on ne reconnait pas la structure est rendu TEL QUEL : mieux
    vaut un routage sans reservation qu un DSN corrompu, que Freerouting
    rejetterait en bloc.
    """
    bloc = _bloc_wiring(vias, net)
    # Les pistes deja routees du meilleur board, protegees pour le palier
    # suivant : c est ce qui rend l escalade CUMULATIVE au lieu de repartir de
    # zero a chaque fois.
    fils = _bloc_wiring_pistes(pistes) if pistes else ""
    bloc = chr(10).join(x for x in (bloc, fils) if x)
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

# Pastilles minimales pour qu un boitier compte comme fine-pitch. Meme
# critere que `_dense_part_refs` cote placement : un connecteur a large pas n a
# pas de probleme d echappement.
_PADS_FINE_PITCH: int = 16


def _pads_signal_fine_pitch(pcb_bytes: bytes) -> list:
    """Pastilles SIGNAL a echapper, des boitiers fine-pitch : ``[(ref, pad)]``.

    ⚠️ La reservation existante ne sert QUE le plan de masse — les broches GND
    que le plan n atteint pas. Grok l a souligne : reserver des vias pour le
    PLAN n est pas echapper les SIGNAUX, et cela peut meme occuper les sites
    dont les signaux ont besoin.

    ⚠️ Sont exclus : les nets confies au plan (ils sortent par-dessous) et les
    pastilles ORPHELINES, dont le net ne touche qu un seul boitier — une
    pastille n est pas une liaison, meme piege que pour le plancher de couches.

    Rend [] au moindre doute : le fanout est un BONUS, jamais un passage oblige.
    """
    try:
        texte = pcb_bytes.decode("utf-8", "replace")
    except Exception:
        return []
    blocs = re.split(r"\(footprint\b", texte)[1:]
    if not blocs:
        return []

    def _pads(bloc):
        """(nom, net) de chaque pastille. Decoupage, pas regex globale.

        ⚠️ Une regex « du nom au net » a echoue sur les VRAIS boards et n a
        rien retenu : le bloc d une pastille tient sur PLUSIEURS lignes et
        contient des parentheses internes (`(at -3.15 2.3 180)`) que le motif
        `[^)]*` arretait net. Ma fixture, elle, tenait sur une seule ligne.
        On decoupe donc par pastille et on lit son premier `(net ...)`.
        """
        trouves = []
        for morceau in bloc.split('(pad "')[1:]:
            nom = morceau.split('"', 1)[0]
            m = re.search(r'\(net \d+ "([^"]*)"\)', morceau)
            if m:
                trouves.append((nom, m.group(1)))
        return trouves

    # Nets presents sur au moins DEUX boitiers : les seuls a router.
    occurrences: dict = {}
    par_bloc = []
    for bloc in blocs:
        # ⚠️ DEUX FORMES de reference selon la version KiCad, verifiees sur
        # des boards reels du depot :
        #     (property "Reference" "U1")   KiCad 8+
        #     (fp_text reference "U1"       forme anterieure
        # N accepter que la premiere rendait `None` sur tous les boards de
        # `examples/`, donc AUCUNE pastille retenue et un fanout inerte.
        ref = (re.search(r'\(property "Reference" "([^"]+)"', bloc)
               or re.search(r'\(fp_text reference "([^"]+)"', bloc))
        pads = _pads(bloc)
        par_bloc.append((ref.group(1) if ref else "", pads))
        for net in {n for _, n in pads}:
            occurrences[net] = occurrences.get(net, 0) + 1
    liaisons = {n for n, k in occurrences.items() if k >= 2 and n}

    cibles = []
    for ref, pads in par_bloc:
        if not ref or len(pads) < _PADS_FINE_PITCH:
            continue
        for nom, net in pads:
            if net in _NETS_CONFIES_AU_PLAN or net not in liaisons:
                continue
            cibles.append((ref, nom))
    return cibles


def _vias_signaux_a_reserver(pcb_bytes: bytes) -> list:
    """Vias d echappement pour les pastilles SIGNAL des boitiers fine-pitch.

    Meme mecanique que la reservation du plan — `plan_escape` calcule les
    positions sur le board PLACE, avant routage, tant que la place existe
    encore — mais sur d autres pastilles et avec un net PAR VIA.

    Rend [] au moindre echec : le fanout est un BONUS, jamais un passage
    oblige. Sans lui le routage se deroule comme avant.
    """
    cibles = _pads_signal_fine_pitch(pcb_bytes)
    if not cibles:
        return []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            entree = Path(tmp) / "in.kicad_pcb"
            resultat = Path(tmp) / "r.json"
            entree.write_bytes(pcb_bytes)
            _run_pcbnew_operation({
                "operation": "plan_escape",
                "pcb": str(entree),
                "result": str(resultat),
                "pads": json.dumps(cibles),
                "escape_mm": str(_ESCAPE_TRACE_MM),
            })
            vias = json.loads(resultat.read_text(encoding="utf-8")).get("vias") or []
        # ⚠️ JOURNALISER LA TENTATIVE, pas seulement le succes. Ne tracer que
        # `if vias` rend indistinguables « aucune cible » et « des cibles mais
        # aucune place » — c est exactement ce qui a masque une premiere
        # version inerte du fanout pendant une heure de mesure.
        logger.info(
            "fanout signal : %d via(s) reserves sur %d pastille(s) visees "
            "sous le(s) boitier(s) fine-pitch", len(vias), len(cibles))
        return vias
    except Exception as exc:
        logger.warning("fanout signal impossible (%s) — routage sans lui", exc)
        return []


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
        repose = sortie.read_bytes()
    # ⚠️ NE PEUT QU AMELIORER — la garde que ses trois voisines avaient et
    # qu elle n avait pas. Les positions de ces vias sont calculees AVANT le
    # routage ; rien ne garantit qu elles restent valides sur le board final.
    #
    # Mesure du 2026-08-31, `nucleo-f401` : 3 `copper_edge_clearance` (cuivre a
    # moins de 0,5 mm du bord), premiere fois que cette carte portait des
    # erreurs — ses deux mesures precedentes etaient a zero. Une carte avec des
    # erreurs de fabricabilite ne part pas en production.
    #
    # La garde ne tranche pas la cause : elle rend l etape incapable
    # d aggraver, comme le reste de la chaine.
    if _compte_erreurs(_rapport_drc(repose)) > _compte_erreurs(_rapport_drc(pcb_bytes)):
        logger.warning(
            "repose des vias : erreurs ajoutees — board d origine conserve")
        return pcb_bytes
    return repose

# Au-dela de ce nombre d ilots par face, le plan n est plus une reference : il
# est fragmente par les pistes de signal. Un plan sain fait UN ilot par face ;
# on tolere 2 pour une decoupe legitime (encoche, zone interdite).
_PLAN_FRAGMENTE_AU_DELA: int = 2


def _compte_ilots_de_plan(pcb_bytes: bytes) -> dict:
    """Ilots REMPLIS par zone : ``{"GND@F.Cu": 5, ...}``.

    ⚠️ La couture rapporte les vias qu elle POSE, jamais les ilots qui
    RESTENT. Nos deux filets — couture repetee, garde sur les broches GND
    orphelines — voient les opens ; ils ne voient pas un plan en peigne dont
    chaque morceau satisfait le DRC et ne sert pas de retour.

    Chaque ilot rempli est un bloc `filled_polygon` distinct dans le fichier :
    le compte se lit donc sans pcbnew.

    ⚠️ Mesurer APRES la coulee. Une zone non remplie n est qu un contour et
    rend 0 — ce qui la ferait passer pour parfaite.
    """
    try:
        texte = pcb_bytes.decode("utf-8", "replace")
    except Exception:
        return {}
    compte: dict = {}
    for bloc in re.split(r"\(zone\b", texte)[1:]:
        # ⚠️ DEUX ECRITURES d une zone, selon QUI a ecrit le board :
        #     (zone (net 3) (net_name "GND") ...)   notre generateur
        #     (zone (net 3) ...)                    pcbnew, SANS net_name
        # N accepter que la premiere rendait `{}` sur tout board passe par
        # pcbnew — c est-a-dire sur tous les boards LIVRES. Le plan de masse de
        # `stm32-100` etait en NEUF ilots sur F.Cu, visible dans le fichier
        # depuis le debut, et ce parseur le cachait.
        # ⚠️ TROIS ecritures du net d une zone, selon la version KiCad et
        # selon QUI a ecrit le board :
        #     (net 3) (net_name "GND")   notre generateur
        #     (net "GND")                pcbnew de KiCad 10
        #     (net 3)                    forme ancienne, nom a resoudre
        # C est la MEME variation que celle documentee pour le comptage des
        # nets (2026-08-20) — et je ne l ai pas appliquee ici.
        nom = (re.search(r'\(net_name "([^"]*)"\)', bloc)
               or re.search(r'\(net "([^"]+)"\)', bloc))
        numero = re.search(r'\(net (\d+)\)', bloc)
        couche = (re.search(r'\(layer "([^"]+)"\)', bloc)
                  or re.search(r'\(layers "([^"]+)"\)', bloc))
        if couche is None or (nom is None and numero is None):
            continue
        if nom is not None:
            etiquette = nom.group(1)
        else:
            # Le nom se lit dans la declaration globale du net.
            decl = re.search(r'\(net %s "([^"]*)"\)' % numero.group(1), texte)
            etiquette = decl.group(1) if decl else "net%s" % numero.group(1)
        cle = f"{etiquette}@{couche.group(1)}"
        compte[cle] = compte.get(cle, 0) + len(re.findall(r"\(filled_polygon", bloc))
    return compte


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

def _nets_incomplets(rapport: dict) -> set:
    """Nets que le DRC voit incomplets sur le board livre.

    ⚠️ DEUX formes a reconnaitre, et n en voir qu une rendait le defaut
    invisible :

        Pad 12 [GND] of U1              une pastille orpheline
        Zone [GND] on F.Cu, priority 0  un PLAN COUPE EN ILOTS

    Mesure du 2026-08-26 : les 3 « manquantes » de la carte a 100 composants
    etaient exactement des paires de zones, et le pourcentage restait a 100 %.

    ⚠️ Extraite de `_percent_verifie` pour servir AUSSI a la decision
    d escalade. Deux extractions separees divergeraient : le message nommerait
    des nets que la decision ne verrait pas.
    """
    nets = set()
    for item in rapport.get("unconnected_items") or []:
        for i in item.get("items") or []:
            d = str(i.get("description", ""))
            m = _PAD_ISOLEE_RE.match(d)
            if m:
                nets.add(m.group(2))
                continue
            z = _ZONE_NET_RE.match(d)
            if z:
                nets.add(z.group(1))
    return nets


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
    nets = _nets_incomplets(rapport)
    if not nets:
        return percent_moteur
    reel = int(round(100 * max(0, routables - len(nets)) / routables))
    if reel < percent_moteur:
        # ⚠️ NOMMER les nets, pas seulement les compter. Sans leur nom on ne
        # peut pas savoir si le manque vient d un SIGNAL que le routeur a rate
        # ou d un net confie au PLAN que la coulee n a pas rejoint — deux
        # defauts opposes, dans deux parties du code. J ai passe une heure a
        # chercher du cote du routeur alors qu il annoncait 100 %.
        logger.warning(
            "routage : %d %% annonce par le moteur, mais le DRC voit %d net(s) "
            "incomplet(s) sur %d — pourcentage ramene a %d %% ; net(s) : %s",
            percent_moteur, len(nets), routables, reel,
            ", ".join(sorted(nets)[:12]))
        return reel
    return percent_moteur

# Passages de couture au maximum. Recoudre deux ilots peut en reveler un
# troisieme : le cuivre nouvellement joint change la topologie, et la mesure
# suivante voit des paires que la premiere ne pouvait pas voir.
#
# ⚠️ Borne : une carte pathologique ferait tourner la boucle sans fin, et
# chaque passage coute un DRC plus un processus pcbnew.
_PASSES_COUTURE = 5


def _coudre_jusqu_au_bout(pcb_bytes: bytes) -> bytes:
    """Repete la couture des ilots tant qu elle change le board.

    ⚠️ Mesure du 2026-08-29 : quatre cartes du banc sortaient a 100 %, trois
    restaient a 96-98 % et TOUTES leurs connexions manquantes etaient des GND —
    trois quarts d entre elles des paires `Zone [GND] <-> Zone [GND]`, le plan
    coupe en ilots par les pistes de signal.

    La couture s executait bien — 1 a 4 vias poses a chaque passage — mais ne
    passait QU UNE FOIS.

    ⚠️ On s arrete des qu un passage ne change plus rien : `_recoudre_les_zones`
    rend le board recu tel quel quand elle ne pose aucun via, ou quand elle
    refuse un resultat qui ajouterait des erreurs. Insister serait vain.

    Garde : tests/test_couture_repetee.py.
    """
    for _ in range(_PASSES_COUTURE):
        recousu = _recoudre_les_zones(pcb_bytes)
        if recousu == pcb_bytes:
            return pcb_bytes
        pcb_bytes = recousu
    return pcb_bytes


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


def _secours_est_meilleur(avant: tuple, apres: tuple) -> bool:
    """Le board de secours vaut-il mieux que celui qu il remplacerait ?

    Les couples sont `(erreurs DRC, connexions manquantes)`. On classe sur
    l erreur d abord : une erreur de fabricabilite fait REFUSER la carte,
    une connexion manquante se voit au DRC et bloque la commande. Meme ordre
    que partout ailleurs dans le projet.

    ⚠️ A EGALITE on REFUSE. Le repli route GND par des pistes au lieu de le
    couler : il coute du cuivre en plus. Sans gain mesure, on garde l existant.

    ⚠️ Ce mecanisme etait le SEUL de la chaine a remplacer le board sans
    comparer. Mesure du 2026-08-31 : `stm32-60` repris hors du banc passe de
    98 % a 100 % par ce repli, alors qu au banc, sur le meme board, le repli
    s est declenche AUSSI et la carte est sortie a 98 %. Un repli qui reussit
    moins bien ecrasait un meilleur resultat sans que rien ne le dise.
    """
    return apres < avant


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
    if not _NETS_CONFIES_AU_PLAN:
        return None   # rien a inclure : aucun net n est confie au plan
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
        bilan = json.loads(resultat.read_text(encoding="utf-8"))
        n = bilan.get("escaped", 0)
        renonces = bilan.get("renonces", 0)
        logger.info("fanout: %d broche(s) sortie(s) vers le plan", n)
        # ⚠️ DIRE les renoncements. Ce compteur existait, etait rendu dans le
        # resultat, et etait JETE : on abandonnait des broches en silence.
        #
        # Or c est le dernier verrou du projet. Banc du 2026-08-31, huit
        # cartes : le net incomplet est GND sur SEPT messages sur sept. Le seul
        # chiffre qui mesure combien de broches GND restent orphelines n etait
        # ecrit nulle part.
        #
        # Un renoncement silencieux est indistinguable d un travail complet —
        # la faute traquee toute la session.
        #
        # ⚠️ On ne FORCE pas ces broches : sans sortie degagee, le via cree des
        # courts-circuits (6 erreurs dont 2 `shorting_items` mesurees le
        # 2026-08-23). Une broche orpheline bloque la commande au DRC ; une
        # broche court-circuitee peut partir en fabrication. On les compte.
        if renonces:
            logger.warning(
                "fanout: %d broche(s) RENONCEE(S) — aucune sortie degagee, "
                "elles resteront orphelines du plan (forcer un via y creerait "
                "un court-circuit)", renonces)
        return sortie.read_bytes()


def _fanout_pads_isolees(pcb_bytes: bytes) -> bytes:
    """Sort par un via les broches que le plan n a pas pu relier.

    ⚠️ APRES le routage, jamais avant : le round-trip Specctra supprime toutes
    les pistes, vias compris (17 vias poses avant routage, 4 apres).

    ⚠️ Cette docstring a decrit pendant des semaines un via pose « A L AVEUGLE ».
    C etait vrai le 2026-08-23 — le fanout ajoutait alors 6 ERREURS dont deux
    `shorting_items` entre GND et +3.3V — et c est FAUX depuis : `_escape_pads`
    consulte son environnement (`_choisir_sortie`) et RENONCE quand aucune
    sortie n est degagee.

    Le 2026-08-31, cette description perimee m a fait diagnostiquer un defaut
    qui n existait plus, et proposer un correctif deja en place. Une
    documentation fausse coute plus cher qu une documentation absente.

    La garde, elle, reste : on compare les erreurs AVANT et APRES et on rend
    l original des qu elles augmentent. Echanger une connexion manquante contre
    un court-circuit est un mauvais marche — la premiere bloque la commande au
    DRC, le second peut partir en fabrication.

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
    nouveau, n = unquote_keepout_values(text)
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

# Retrait du plan par rapport au contour. `copper_edge_clearance` vaut
# 0,5 mm par defaut chez KiCad ; on prend une marge au-dessus pour absorber
# l arrondi du remplissage.
_RETRAIT_BORD_MM: float = 0.6


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

    # ⚠️ RETRAIT du bord. Coule sur la boite englobante brute, le cuivre du
    # plan arrive au ras d Edge.Cuts et le DRC leve une ERREUR — pas un
    # avertissement : `copper_edge_clearance`, qui fait refuser la carte.
    # Mesure du 2026-08-26 : 3 erreurs de cette famille sur stm32-baseline.
    #
    # Un fabricant fraise le contour avec une tolerance ; du cuivre
    # affleurant se retrouve expose ou arrache.
    #
    # On retire, on ne supprime pas : un plan absent laisserait GND sans
    # porteur et la sequence « le plan prend GND en charge » s effondrerait.
    x1, y1 = x1 + _RETRAIT_BORD_MM, y1 + _RETRAIT_BORD_MM
    x2, y2 = x2 - _RETRAIT_BORD_MM, y2 - _RETRAIT_BORD_MM
    if x2 - x1 < 1.0 or y2 - y1 < 1.0:
        logger.warning("plans de masse: carte trop petite pour un retrait de bord")
        return pcb_bytes

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
        # ⚠️ NOMMER l operation. « pcbnew child timed out » ne dit pas ce qui a
        # expire : trois expirations dans un meme journal peuvent venir de la
        # couture, du remplissage ou de l echappement, et sans le nom on ne
        # peut ni imputer ni corriger. C est ce qui a rendu ce defaut invisible.
        raise RuntimeError(
            f"pcbnew child timed out after {_PCBNEW_RUNNER_TIMEOUT_S}s "
            f"(operation {payload.get('operation', '?')})"
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
# ⚠️ GND est CONFIE AU PLAN, pas route — sequence voulue par l utilisateur et
# reaffirmee le 2026-08-28 : couler le plan, router les signaux, et sortir en
# fine-pitch avec des vias les broches que le plan n atteint pas.
#
# Mesure du 2026-08-28, deux cartes, meme board place, meme budget :
#
#     carte          GND confie au plan        GND route en pistes
#     arduino-uno    93 % · 1 manq · 0 err     100 % · 0 manq · 0 err
#     nucleo-f401    81 % · 12 manq · 1 err     81 % · 12 manq · 0 err
#
# Router GND rendait la carte complete sur l Arduino. La decision produit est
# NEANMOINS de garder le plan en charge de GND : le levier a actionner est
# l echappement (`_fanout_pads_isolees`) et la couture, pas le renoncement au
# plan. Le chiffre est consigne ici pour que la comparaison reste disponible —
# il suffit de vider ce tuple pour la refaire.
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
                pcb_bytes, _remaining_budget_s(deadline),
                nets_routables=net_count,
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
        except RoutageFige:
            # ⚠️ NE PAS retomber sur le sous-processus : il referait 44 min
            # sur le meme board condamne. La stagnation est un VERDICT de
            # palier, pas une panne de moteur — elle remonte a la boucle
            # d escalade, qui monte d une couche.
            raise
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
                if _VIAS_RESERVES or _PISTES_A_PROTEGER:
                    dsn.write_text(_injecter_wiring(
                        dsn.read_text(encoding="utf-8", errors="replace"),
                        [(v["via_x"], v["via_y"]) for v in _VIAS_RESERVES],
                        _NETS_CONFIES_AU_PLAN[0] if _NETS_CONFIES_AU_PLAN else "GND",
                        pistes=_PISTES_A_PROTEGER,
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
def _armer_abandon(actif: bool) -> None:
    """Arme ou desarme l abandon sur stagnation, pour tout le processus.

    ⚠️ Etat de MODULE : il doit etre restaure sans faute, sinon la detection
    resterait desarmee pour toutes les requetes suivantes du meme worker — un
    desarmement invisible et durable.
    """
    global _ABANDON_AUTORISE
    _ABANDON_AUTORISE = actif


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

    sans_gain = 0
    meilleur_note = (-1, 10 ** 6)
    # ⚠️ Le palier de DEPART se deduit du board, il n est plus toujours 2.
    # `stm32-100` a brule 45 minutes a 2 couches — un palier qu aucun tirage
    # ne pouvait reussir, son LQFP-48 ayant 43 signaux a sortir. Le plafond du
    # plan reste maitre : on ne vend pas 4 couches a un compte limite a 2.
    # ⚠️ DECISION UTILISATEUR (2026-08-29) : ON PART TOUJOURS DE 2 COUCHES.
    #
    # Le plancher d echappement reste CALCULE et JOURNALISE — il dit ce qui est
    # hors d atteinte — mais il ne commande plus le depart. La raison est
    # commerciale : une carte 2 couches coute moins cher a fabriquer, et on ne
    # facture pas 4 couches a un client sur une PREVISION, meme etayee. On
    # escalade sur PREUVE.
    #
    # Le prix est mesure et assume : sur stm32-100, un tirage a 2 couches coute
    # ~44 min avant que `_tirages_epuises_au_palier` ne l abandonne. C est le
    # cout d une preuve plutot que d une supposition.
    signaux = _signaux_a_echapper(pcb_bytes, set(_NETS_CONFIES_AU_PLAN))
    plancher = _couches_pour_echapper(signaux)
    if plancher > 2:
        logger.info(
            "route_auto: le boitier le plus charge a %d signaux a echapper — "
            "%d couches seraient necessaires ; on tente 2 d abord (decision "
            "produit), l escalade tranchera sur mesure", signaux, plancher)
    # ⚠️ ARMER A L ENTREE, et non restaurer a la sortie. `_ABANDON_AUTORISE`
    # est un etat de MODULE : un `finally` ne protegerait que le chemin qui
    # l a desarme, alors qu armer ici REPARE aussi une fuite laissee par un
    # appel precedent — un desarmement invisible et durable serait le pire des
    # defauts silencieux, la detection de stagnation cessant d exister sans que
    # rien ne le dise.
    _armer_abandon(True)
    # ⚠️ Etat de MODULE, arme a l entree comme `_ABANDON_AUTORISE` : le laisser
    # traîner ferait proteger, dans une requete suivante, les pistes d une
    # carte qui n a rien a voir.
    global _PISTES_A_PROTEGER
    _PISTES_A_PROTEGER = None
    # ⚠️ Etat de module : sans remise a zero on recupererait le job d une AUTRE
    # carte, routee dans la requete precedente du meme worker.
    _JOBS_ABANDONNES.clear()
    essais = _paliers_avec_tirages(
        _layer_ladder(req.layers), _TIRAGES_ROUTAGE_PAR_PALIER)
    palier_courant: Optional[int] = None
    meilleur_du_palier = 0
    # ⚠️ Le bonus n est accorde qu UNE FOIS par palier : sinon une carte qui
    # plafonne a 99 % re-tirerait sans fin et ne verrait jamais 4 couches.
    bonus_accorde: set[int] = set()
    # ⚠️ Le routeur a-t-il DEJA fini, sur un board propre ? Si oui, escalader
    # est inutile par construction : l ecart restant vient d un net confie au
    # PLAN, que du cuivre supplementaire ne relie pas.
    escalade_inutile = False
    # Boucle indexee, et non `for ... in essais` : le bonus INSERE des tirages
    # dans la file au moment ou l on s appreterait a quitter le palier.
    i_essai = 0
    derniere_chance_donnee = False
    while True:
        if i_essai >= len(essais):
            # ⚠️ DERNIERE CHANCE. Tous les tirages ont fige et il ne reste
            # RIEN a livrer — or le job abandonne CONTINUE dans la JVM
            # (`cancel` repond 501) et finit seul : le cuivre existe, personne
            # ne va le chercher. Mesure du 2026-08-31 sur `nucleo-f401` : six
            # tirages figes (43, 79, ?, 77, 77, 62 %), zero board rendu. Meme
            # scenario la veille sur `stm32-100`, ou des tirages touchaient
            # 96 %.
            #
            # On ne desarme PAS le detecteur de stagnation — c est lui qui rend
            # l escalade rapide. On lui ajoute le cas limite : quand il a tout
            # abandonne, un tirage mene a son terme vaut mieux qu une carte
            # vide. Le detecteur de SILENCE reste actif.
            #
            # UNE SEULE FOIS : sinon une carte reellement impossible bouclerait
            # sans fin.
            if (meilleur is not None or derniere_chance_donnee
                    or not _budget_suffisant(_remaining_budget_s(deadline))):
                break
            derniere_chance_donnee = True
            _armer_abandon(False)
            essais.append(_layer_ladder(req.layers)[0])
            logger.warning(
                "route_auto: tous les tirages ont fige et aucun board n a ete "
                "garde — derniere chance a %d couches, SANS abandon sur "
                "stagnation (le routeur ira au bout)", essais[-1])
        palier = essais[i_essai]
        i_essai += 1
        if palier != palier_courant:
            # ⚠️ On s apprete a QUITTER le palier precedent. S il est a portee
            # de 100 %, le quitter est le pari perdant — mesure du 2026-08-30
            # sur stm32-100 : 99 % a 2 couches, puis 87 % a 4 couches pour
            # 2400 s, tandis qu un tirage de plus au meme palier en coutait
            # 600 et a produit le seul 100 % obtenu sur cette carte.
            # ⚠️ Le routeur a fini et le board est propre : monter d une
            # couche ne peut rien apporter, et coute plus cher a fabriquer.
            if escalade_inutile:
                logger.info(
                    "route_auto: escalade arretee avant %d couches — le routeur "
                    "annonce 100%% sur un board sans erreur ; ce qui manque est "
                    "confie au PLAN, que du cuivre en plus ne relie pas",
                    palier)
                break
            if palier_courant is not None and palier_courant not in bonus_accorde:
                bonus = _tirages_bonus(meilleur_du_palier)
                if bonus:
                    bonus_accorde.add(palier_courant)
                    logger.info(
                        "route_auto: %d tirage(s) de plus a %d couches avant "
                        "d escalader — %d%% est a portee de 100%%, et monter "
                        "d une couche coute plus cher qu un re-tirage",
                        bonus, palier_courant, meilleur_du_palier)
                    essais[i_essai - 1:i_essai - 1] = [palier_courant] * bonus
                    i_essai -= 1
                    continue
            # ⚠️ ESCALADE CUMULATIVE (demande utilisateur, 2026-08-31). En
            # montant d un palier, on PROTEGE les pistes du meilleur board
            # obtenu jusqu ici : le routeur complete au lieu de tout refaire.
            #
            # Ce n est possible que parce que le DSN exporte par pcbnew porte
            # un bloc `(wiring)` VIDE — verifie sur un export reel — donc le
            # routeur ne DETRUISAIT pas le cuivre recu, il ne le voyait jamais.
            # On le lui montre, marque `(type protect)`.
            #
            # Mon objection initiale citait la mesure du 2026-08-01 sur
            # `--preserve-existing` de `kct route` : un moteur que la cascade
            # n emprunte JAMAIS (16 routages sur 16 par l API Freerouting).
            if meilleur is not None and meilleur.kicad_pcb_b64:
                _PISTES_A_PROTEGER = base64.b64decode(meilleur.kicad_pcb_b64)
                # ⚠️ COMPTER les fils, ne pas se contenter d annoncer. Le
                # 2026-08-31 au matin, ce meme mecanisme en injectait ZERO
                # (le net nomme de KiCad 10) tout en affichant un message
                # rassurant. Un message qui ne compte pas peut mentir.
                n_fils = _bloc_wiring_pistes(_PISTES_A_PROTEGER).count("(wire")
                if not n_fils:
                    logger.warning(
                        "route_auto: passage a %d couches — AUCUNE piste "
                        "protegee alors que le board a %d%% : le routeur va "
                        "repartir de zero", palier, meilleur.routed_percent)
                else:
                    logger.info(
                        "route_auto: passage a %d couches — %d piste(s) du "
                        "meilleur board (%d%%) PROTEGEES, le routeur complete "
                        "au lieu de repartir de zero",
                        palier, n_fils, meilleur.routed_percent)
            palier_courant, meilleur_du_palier = palier, 0
        # ⚠️ Abandonner les tirages RESTANTS d un palier hors d atteinte. Ils
        # ne sont pas gratuits : sur stm32-100 ils ont mange les 3600 s et la
        # carte n a jamais essaye 4 couches (mesure du 2026-08-29).
        elif _tirages_epuises_au_palier(meilleur_du_palier):
            logger.info(
                "route_auto: tirages restants a %d couches abandonnes — %d%% "
                "est trop loin de 100%% pour qu un re-tirage le rattrape "
                "(ecart mesure : 26 points au plus)",
                palier, meilleur_du_palier)
            continue
        if _escalade_epuisee(sans_gain):
            logger.info(
                "route_auto: escalade arretee avant %d couches — %d palier(s) "
                "consecutif(s) sans gain, le meilleur est deja acquis",
                palier, sans_gain)
            break
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

        # ⚠️ LE PLAN EST COULE ICI, AVANT LE ROUTAGE — sequence demandee par
        # l utilisateur et reaffirmee le 2026-08-29 : couler le plan de masse
        # et raccorder les pattes qu il atteint, PUIS router les signaux, PUIS
        # affiner (echappement fine-pitch, vias, couture).
        #
        # On le coulait APRES. Le routeur ne voyait donc jamais le cuivre de
        # masse : il routait comme si la carte etait vide, et on posait le plan
        # par-dessus. Mesure sur la Nucleo, meme placement :
        #
        #     plan coule APRES  (production)   68-71 % route
        #     plan coule AVANT  (4 couches)    94 % route, 4 manquantes
        #
        # ⚠️ Cette comparaison melangeait l ordre du plan ET le nombre de
        # couches force : elle indique une direction, elle ne la prouve pas
        # seule. La decision est celle de l utilisateur.
        #
        # ⚠️ Un plan non REMPLI n est qu un contour, dont le routeur ne tient
        # aucun compte — meme defaut que celui du 2026-08-23.
        etendu = _fill_zones(_add_ground_planes(etendu))

        # ⚠️ Reserver AVANT de router : apres, il n y a plus de place. Mesure
        # du 2026-08-23 — 504 candidats essayes autour des pattes orphelines
        # du LQFP-48, aucun ne passe, le voisinage comptant 182 obstacles
        # (les pistes de signal). Les vias sont declares dans le DSN pour que
        # le routeur travaille autour, puis reposes apres le round-trip
        # Specctra, qui efface tout ce qui le precede.
        global _VIAS_RESERVES
        _VIAS_RESERVES = _vias_a_reserver(etendu) if _NETS_CONFIES_AU_PLAN else []

        # ⚠️ FANOUT DES SIGNAUX — distinct de la reservation ci-dessus,
        # qui ne sert QUE le plan de masse. Grok l a souligne : reserver
        # des vias pour le PLAN n est pas echapper les SIGNAUX, et cela
        # peut meme occuper les sites dont les signaux ont besoin.
        #
        # Au pas de 0,5 mm avec des pastilles de 0,3, il reste 0,2 mm
        # entre deux pastilles : avec le degagement JLCPCB, AUCUNE piste
        # n y passe (analyse OpenCode). Les 36 signaux du LQFP-48 doivent
        # donc sortir PAR-DESSOUS. On pose le via avant le routage et le
        # routeur travaille de via a via — ce qu il sait bien mieux faire.
        #
        # ⚠️ Le journal designe ce boitier sans ambiguite : un seul
        # composant porte 20 a 28 % des echecs de connexion, les 85
        # autres 2 % chacun, et sa part egale sa part des connexions.
        #
        # ⚠️ Ce n est PAS un manque de couches : `stm32-100` rend 99 % a
        # 2 couches et 87 % a 4. Le goulot est LOCAL.
        _VIAS_RESERVES = _VIAS_RESERVES + _vias_signaux_a_reserver(etendu)

        tentative = RouteAutoRequest(
            kicad_pcb_b64=base64.b64encode(etendu).decode("ascii"),
            layers=req.layers,
            # ⚠️ TOUT le restant, et c est voulu. Partager le budget entre
            # les essais a ete essaye le 2026-08-29 et s est revele
            # DESASTREUX : 1800 s / 12 essais = 150 s chacun, trop court pour
            # router une carte de 100 composants — tous les paliers ont rendu
            # 0 %, contre 96 % avec le budget entier.
            #
            # Donner tout le restant s adapte de soi-meme : sur une carte
            # rapide le premier essai prend 40 s et en laisse neuf autres ; sur
            # une carte lente il prend tout, et c est le bon choix. Le manque
            # sur les grandes cartes n est pas la repartition, c est le budget
            # TOTAL — un parametre de l appelant.
            timeout_s=max(restant, _MIN_LEVEL_BUDGET_S),
        )
        try:
            res = _route_auto_once(tentative)
        except RoutageFige as fige:
            # ⚠️ LA STAGNATION EST LA PREUVE QUE LE PALIER A ECHOUE — la regle
            # utilisateur « partir de 2, escalader sur preuve » est respectee,
            # seule l ATTENTE de la preuve raccourcit : ~2 min au lieu de 44.
            # Le job fige finit seul dans la JVM (deux jobs en parallele,
            # verifie le 2026-08-29) ; le palier suivant demarre sans lui.
            #
            # max(1, ...) : un pourcentage nul viendrait d un compte de nets
            # inconnu, et 0 est reserve aux PANNES — qui, elles, ne font pas
            # escalader. Une stagnation mesuree doit toujours faire abandonner
            # les tirages restants du palier.
            # ⚠️ UN TIRAGE FIGE N EST PAS UN PALIER MORT — et c est la
            # QUATRIEME fois que je confonds les deux sur ce mecanisme.
            # Freerouting est stochastique : 65, 77 et 91 % mesures sur le
            # MEME board place. Mesure du 2026-08-29 sur arduino-uno, palier
            # 2 couches : tirage 1 -> 93 %, tirage 2 -> 100 %. Abandonner le
            # palier au premier tirage fige aurait coute une couche.
            #
            # `meilleur_du_palier` n est donc PAS alimente ici : il sert a
            # decider si le PALIER merite ses tirages restants, et seul un
            # tirage ALLE A SON TERME repond a cette question. On abandonne ce
            # tirage-la, pas les autres.
            logger.warning(
                "route_auto: tirage fige a ~%d%% au palier %d couches — "
                "on passe au tirage suivant", fige.routed_percent, palier)
            sans_gain += 1
            continue

        # ⚠️ Initialise AVANT le bloc : lire cette variable par `locals()`
        # serait fragile, et un tirage sans board la laisserait indefinie.
        # Zero veut dire « le routeur n a rien annonce », donc on escalade.
        percent_moteur = 0
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
            final = _coudre_jusqu_au_bout(final)

            # ⚠️ DIRE ce qui reste, pas seulement ce qu on a repare. La couture
            # rapporte ses vias ; si elle laisse un plan en quinze morceaux, le
            # board est « connecte » et sa reference est mauvaise. Personne ne
            # le verrait — le DRC ne juge pas la fragmentation d un plan.
            ilots = _compte_ilots_de_plan(final)
            fragmentes = {k: v for k, v in ilots.items()
                          if v > _PLAN_FRAGMENTE_AU_DELA}
            if fragmentes:
                logger.warning(
                    "plan de masse FRAGMENTE : %s — connecte mais mauvaise "
                    "reference de retour",
                    ", ".join(f"{k} en {v} ilots" for k, v in sorted(fragmentes.items())))
            elif ilots:
                logger.info("plan de masse : %s",
                            ", ".join(f"{k} {v} ilot(s)" for k, v in sorted(ilots.items())))

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
                    # ⚠️ COMPARER avant de remplacer. Ce mecanisme etait le
                    # seul de la chaine a ecraser le board sans verifier qu il
                    # l ameliore — ses quatre voisines ont toutes cette garde.
                    rap_a = _rapport_drc(final)
                    rap_b = _rapport_drc(secours)
                    avant = (_compte_erreurs(rap_a),
                             len(rap_a.get("unconnected_items") or []))
                    apres = (_compte_erreurs(rap_b),
                             len(rap_b.get("unconnected_items") or []))
                    if _secours_est_meilleur(avant, apres):
                        logger.info(
                            "repli GND retenu : (%d erreur, %d manquante) -> "
                            "(%d erreur, %d manquante)",
                            avant[0], avant[1], apres[0], apres[1])
                        final = secours
                    else:
                        logger.warning(
                            "repli GND REFUSE : (%d erreur, %d manquante) ne "
                            "fait pas mieux que (%d erreur, %d manquante) — "
                            "board conserve",
                            apres[0], apres[1], avant[0], avant[1])

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
            # ⚠️ CONSERVER le chiffre du MOTEUR avant de l ecraser : c est lui
            # qui dit si le routeur a fini, et donc si escalader a encore un
            # sens. Le chiffre corrige, lui, melange le routage et l etat du
            # plan de masse.
            percent_moteur = res.routed_percent
            res.routed_percent = _percent_verifie(
                final, res.routed_percent, nets_routables
            )

        logger.info(
            "route_auto: palier %d couches -> %d%% (%s)",
            palier, res.routed_percent, res.engine or "aucun moteur",
        )

        # ⚠️ Les erreurs du palier, mesurees sur le board LIVRE. Un palier a
        # 100 % qui ne passe pas le DRC n est pas une reussite : la carte ne
        # part pas en fabrication.
        erreurs = (_compte_erreurs(_rapport_drc(final))
                   if res.kicad_pcb_b64 and not res.skipped else 10 ** 6)
        # ⚠️ QUELS nets manquent, pas seulement combien. Regle de l utilisateur :
        # un net confie au PLAN ne se relie pas avec du cuivre en plus.
        manquants_du_palier = (
            _nets_incomplets(_rapport_drc(final))
            if res.kicad_pcb_b64 and not res.skipped else set())
        if not _escalade_peut_aider(percent_moteur, erreurs,
                                    manquants=manquants_du_palier):
            escalade_inutile = True
            logger.info(
                "route_auto: ce qui manque est confie au PLAN (%s) — escalader "
                "n y changerait rien, c est un probleme d acces a la broche",
                ", ".join(sorted(manquants_du_palier)) or "-")
        if res.routed_percent >= 100 and not res.skipped and erreurs == 0:
            return res
        meilleur_du_palier = max(meilleur_du_palier, res.routed_percent)
        if meilleur is None or _palier_meilleur(
                (res.routed_percent, erreurs), meilleur_note):
            meilleur, meilleur_note = res, (res.routed_percent, erreurs)
            sans_gain = 0
        else:
            sans_gain += 1

    # Aucun palier n'a atteint 100 % : on rend le MEILLEUR, jamais le dernier.
    # Un palier superieur peut faire moins bien (plus de vias, plus de conflits),
    # et livrer le dernier essai plutot que le meilleur serait une regression
    # silencieuse.
    # ⚠️ NE JAMAIS FABRIQUER DE BOARD ICI. `meilleur` peut etre une reponse
    # SANS board — un palier « aucun moteur » rend `kicad_pcb_b64 = None`, et
    # s il est le seul alle a son terme, c est lui qui devient le meilleur.
    #
    # J ai voulu rendre le board d ENTREE dans ce cas, pour eviter le plantage
    # de `banc_exemples.py` sur `base64.b64decode(None)` (2026-08-30). C etait
    # une ERREUR, et `test_aucun_routeur_utilisable_reste_un_echec_franc` l a
    # refusee a juste titre : un appelant qui ignore `skipped` expedierait une
    # carte NON ROUTEE en fabrication, en silence. Un plantage, lui, s entend.
    #
    # L echec reste donc franc. C est a l APPELANT de traiter `skipped`.
    # ⚠️ Un `assert` vivait ici, avec ce commentaire : « `_layer_ladder` rend
    # toujours au moins [2] ». C est vrai des PALIERS, faux des RESULTATS — un
    # tirage fige n en produit aucun. Quand TOUS stagnent, `meilleur` reste
    # None et l assertion levait une `AssertionError` AU MESSAGE VIDE.
    #
    # Mesure du 2026-08-30, `nucleo-f401` : « escalade arretee — 7 paliers sans
    # gain », puis « ECHEC [exception] » et rien d autre. Une assertion qui
    # protege un invariant faux ne protege rien : elle transforme un echec
    # previsible en panne muette.
    #
    # On rend donc l echec FRANC que reclame
    # `test_aucun_routeur_utilisable_reste_un_echec_franc` : pas de board,
    # `skipped`, 0 %. L appelant sait le traiter.
    if meilleur is None:
        logger.error(
            "route_auto: aucun palier n a rendu de resultat — tous les tirages "
            "ont stagne ou echoue")
        # ⚠️ DERNIER RECOURS, et il ne coute AUCUN budget : les jobs abandonnes
        # continuent dans la JVM et finissent seuls. Mesure du 2026-08-31,
        # `stm32-100` : trois tirages figes a 68, 54 et 72 %, tous jetes, carte
        # sortie en ECHEC — alors que le board a 72 % existait.
        #
        # La « derniere chance » ne joue pas ici : elle exige du budget, et il
        # est justement epuise quand tous les tirages ont fige.
        recupere = _recuperer_jobs_abandonnes(pcb_bytes)
        if recupere is not None:
            pct = _measured_routed_percent(recupere, nets_routables)
            return RouteAutoResponse(
                kicad_pcb_b64=base64.b64encode(recupere).decode("ascii"),
                routed_percent=_percent_verifie(recupere, pct, nets_routables),
                layers=_count_copper_layers(recupere),
                engine="freerouting-recupere",
                via_count=_count_vias(recupere),
                track_length_mm=_track_length_mm(recupere),
                warning="tous les tirages ont stagne — board recupere d un job "
                        "abandonne, incomplet mais reel")
        return RouteAutoResponse(
            routed_percent=0, layers=req.layers, skipped=True,
            warning="tous les tirages ont stagne ou echoue — aucun routage")
    return meilleur

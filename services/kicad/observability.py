"""Initialisation Sentry du service KiCad — desactivee par defaut.

POURQUOI CE FILTRE EXISTE

Sentry est un service TIERS : tout ce qu'on lui envoie quitte notre
infrastructure. Or ce service manipule, a chaque requete, la propriete
intellectuelle du client — schemas ``.kicad_sch``, boards ``.kicad_pcb``,
Gerbers, le tout circulant en base64 dans les corps de requete.

Un ``sentry_sdk.init(dsn=...)`` nu attacherait ces corps aux evenements. Une
simple erreur de routage exfiltrerait alors le circuit d'un client, sans que
rien ne casse et sans qu'aucun test ne le signale : c'est precisement la classe
de defaut invisible que ce projet a passe sa journee a eliminer ailleurs.

DEUX BARRIERES, VOLONTAIREMENT REDONDANTES — symetriques du filtre TypeScript
(``apps/web/src/shared/lib/sentry-scrub.ts``) :

  1. par NOM de champ : precis, mais aveugle a ce qui n'existe pas encore ;
  2. par TAILLE : toute chaine anormalement longue est tronquee quel que soit
     son nom. Les charges utiles KiCad font des dizaines de kilo-octets, un
     message d'erreur utile quelques centaines. La seconde barriere rattrape
     donc ce que la premiere ignore.

Sans ``SENTRY_DSN``, ``init`` n'est jamais appele : aucun reseau, aucune donnee
qui sort. Meme contrat que le limiteur Upstash cote web — une integration
d'observabilite absente ne doit jamais empecher le service de tourner.
"""

from __future__ import annotations

import os
from typing import Any

REDACTED = "[expurge]"

#: Au-dela, une chaine est tronquee quel que soit son nom.
MAX_STRING_LENGTH = 512

_MAX_DEPTH = 8

#: Motifs cherches en SOUS-CHAINE dans les noms de champs, pas en egalite.
#:
#: L'egalite exacte a ete mesuree insuffisante le 2026-08-12 : elle listait les
#: noms de champs de l'API (``kicad_pcb_b64``…) alors que les VARIABLES du code
#: s'appellent ``pcb_bytes``, ``zip_bytes``, ``pcb_content``, ``updated_b64``.
#: Aucune ne correspondait, et le board partait en entier. Une liste de noms
#: exacts ne peut pas suivre le nommage reel d'un code qui evolue.
_REDACTED_PATTERNS = (
    "b64",
    "bytes",
    "content",
    "gerber",
    "netlist",
    "schema",
    "bom",
    "cpl",
    "pcb",
    "sch",
    "prompt",
    # Secrets — ne devraient jamais transiter, mais le cout d'un oubli est
    # trop eleve pour se fier a cette conviction.
    "authorization",
    "cookie",
    "token",
    "secret",
    "api_key",
    "password",
)


def _is_sensitive_key(key: object) -> bool:
    k = str(key).lower()
    return any(p in k for p in _REDACTED_PATTERNS)


def scrub(value: Any, depth: int = 0) -> Any:
    """Expurge recursivement une valeur destinee a Sentry.

    Ne modifie jamais l'entree : renvoie une copie nettoyee. Muter l'evenement
    en place corromprait l'objet que le service continue d'utiliser.
    """
    if depth > _MAX_DEPTH:
        return REDACTED

    # Les binaires ne sont JAMAIS transmis, meme tronques. Un payload binaire
    # n'a aucune valeur diagnostique dans une alerte, et la barriere par taille
    # ne s'appliquait pas a eux : ``bytes`` tombait jusqu'au ``return value``
    # final et repartait intact. Mesure du 2026-08-12 : c'est par la que
    # ``pcb_bytes`` sortait.
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"{REDACTED} ({len(value)} octets binaires)"

    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            return f"{value[:MAX_STRING_LENGTH]}… [tronque, {len(value)} caracteres]"
        return value

    if isinstance(value, dict):
        return {
            k: REDACTED if _is_sensitive_key(k) else scrub(v, depth + 1)
            for k, v in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [scrub(v, depth + 1) for v in value]

    return value


def scrub_event(event: dict, _hint: Any = None) -> dict | None:
    """``before_send`` : derniere barriere avant que l'evenement ne parte.

    Les en-tetes et cookies de requete sont supprimes EN BLOC plutot
    qu'expurges champ par champ : ils ne portent rien qu'une alerte exige, et
    tout ce qu'un jeton d'authentification ne doit pas quitter.

    Si le filtre echoue, l'evenement est ABANDONNE plutot qu'envoye non
    filtre : perdre une alerte est moins grave qu'exfiltrer un schema client.
    """
    try:
        cleaned = scrub(event)
        request = cleaned.get("request")
        if isinstance(request, dict):
            request.pop("headers", None)
            request.pop("cookies", None)
            request.pop("data", None)
        return cleaned
    except Exception:  # noqa: BLE001 — jamais d'envoi non filtre
        return None


def init_sentry() -> bool:
    """Active Sentry si ``SENTRY_DSN`` est pose. Renvoie True si initialise."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False

    try:
        import sentry_sdk
    except ImportError:  # SDK non installe : le service tourne quand meme
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
        release=os.environ.get("SENTRY_RELEASE"),
        # Pas de traces de performance : elles attachent URLs, corps de requete
        # et requetes SQL — une surface d'exfiltration bien plus large, pour un
        # besoin que nous n'avons pas.
        traces_sample_rate=0.0,
        send_default_pii=False,
        before_send=scrub_event,
        max_request_body_size="never",
        # LE reglage qui compte. Par defaut le SDK capture les variables
        # LOCALES de chaque frame de la pile. Mesure du 2026-08-12, en levant
        # une exception dans une fonction tenant un board :
        #
        #   SECRET_NET present dans l evenement : True
        #   frame export_gerbers -> vars: ['pcb_bytes', 'zip_bytes']
        #
        # Le filtre par nom ne pouvait rien : ces variables ne portent pas les
        # noms des champs d'API. Le message d'exception et la pile restent
        # conserves — on ne perd rien d'exploitable.
        include_local_variables=False,
        # Nom d'hote de l'instance : sans valeur diagnostique ici, et c'est de
        # la topologie interne.
        server_name=None,
    )
    return True

"""Un seul routage a la fois, sur toute la machine.

⚠️ MESURE DU 2026-09-03 : un routage monte a **6,2 Go de memoire residente**
(`stm32-baseline`, 17 composants, le PLUS PETIT board du banc). Deux en
parallele depassent les 7,6 Go disponibles et le noyau tue le processus :

    Out of memory: Killed process (python3)  anon-rss:6247616kB
    crete du cgroup : 7,2 Go

Le service tourne pourtant avec `--workers 4` : il annonce quatre requetes
simultanees quand la memoire n en autorise qu une. Le symptome, cote client,
est un `RemoteDisconnected` sans le moindre message applicatif ; cote journal,
un `Child process died`. Rien ne designe la cause.

⚠️ POURQUOI PAS UN SEUL WORKER, qui reglerait la memoire d un mot. Parce qu il
casserait tout le reste : `GET /route/progress` — la progression livree le meme
jour — attendrait la fin d un routage de vingt minutes, et `GET /health`, dont
Docker se sert pour juger le conteneur, resterait sans reponse pendant ce temps.
Le conteneur serait declare malade a chaque routage. On garde donc les quatre
workers pour les requetes legeres, et on serialise LE SEUL point couteux.

⚠️ ET UN VERROU DANS LE PROCESSUS NE SUFFIT PAS : les quatre workers sont des
processus separes, un `threading.Lock` n en verrouillerait qu un. Le verrou
porte donc sur un FICHIER, seule ressource que les quatre partagent — comme le
fichier de progression, et pour la meme raison.

⚠️ ON RENONCE APRES ATTENTE, ET ON LE DIT. Attendre sans borne ferait passer un
service occupe pour un service lent ; ce depot a deja paye cette confusion sur
la detection de stagnation. Un refus explicite vaut mieux qu une attente muette.

Decision produit `D-2026-09-03-b`, tranchee par l utilisateur le 2026-09-04
(« decide toi ») : voir `docs/DECISIONS.md`.

Garde : `tests/test_verrou_routage.py`.
"""
from __future__ import annotations

import contextlib
import logging
import os
import time
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

# Verrouillage de fichier : `fcntl` sous Linux (le conteneur), `msvcrt` sous
# Windows (la machine de developpement). Les deux sont dans la bibliotheque
# standard ; aucune dependance ajoutee.
try:  # pragma: no cover - depend de la plateforme
    import fcntl

    _VERROUILLEUR = "fcntl"
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]
    try:
        import msvcrt

        _VERROUILLEUR = "msvcrt"
    except ImportError:
        msvcrt = None  # type: ignore[assignment]
        _VERROUILLEUR = ""

VERROU_DISPONIBLE = bool(_VERROUILLEUR)

# Ou vit le verrou. Un seul fichier pour toute la machine : c est le point.
CHEMIN_PAR_DEFAUT = Path(
    os.environ.get("CIRQIX_VERROU_ROUTAGE", "/tmp/cirqix-routage.lock"))

# Combien de temps un routage patiente avant de renoncer. Genereux : un
# routage mesure dure jusqu a ~45 min sur `stm32-100`, et l appelant qui
# attend son tour prefere attendre que recommencer.
ATTENTE_PAR_DEFAUT_S: float = 3600.0

# Cadence de reprise. Assez fine pour ne pas gaspiller la place liberee,
# assez lache pour ne pas marteler le systeme de fichiers pendant une heure.
_PAS_S: float = 0.5


class RoutageOccupe(RuntimeError):
    """Un autre routage occupe la machine et n a pas rendu la place a temps."""

    def __init__(self, attente_s: float = 0.0) -> None:
        super().__init__(
            "un autre routage occupe la machine — un seul tient a la fois, "
            "car un routage consomme jusqu a 6,2 Go de memoire et deux en "
            "parallele font tuer le processus"
            + (" (attendu %.0f s)" % attente_s if attente_s else ""))


def _essayer_de_prendre(descripteur: int) -> bool:
    """Prise NON bloquante. `False` si un autre la detient deja."""
    try:
        if _VERROUILLEUR == "fcntl":
            fcntl.flock(descripteur, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif _VERROUILLEUR == "msvcrt":
            os.lseek(descripteur, 0, os.SEEK_SET)
            msvcrt.locking(descripteur, msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover - plateforme sans verrouillage
            return True
        return True
    except OSError:
        return False


def _rendre(descripteur: int) -> None:
    try:
        if _VERROUILLEUR == "fcntl":
            fcntl.flock(descripteur, fcntl.LOCK_UN)
        elif _VERROUILLEUR == "msvcrt":
            os.lseek(descripteur, 0, os.SEEK_SET)
            msvcrt.locking(descripteur, msvcrt.LK_UNLCK, 1)
    except OSError as exc:  # pragma: no cover
        # Le descripteur se ferme juste apres : le verrou tombe de toute
        # facon. On journalise sans faire echouer un routage deja rendu.
        logger.warning("verrou de routage non rendu proprement (%s)", exc)


@contextlib.contextmanager
def verrou_de_routage(
    attente_s: float = ATTENTE_PAR_DEFAUT_S,
    chemin: Optional[Path] = None,
) -> Iterator[None]:
    """Tient la place d un routage, ou leve `RoutageOccupe`.

    ⚠️ A prendre AVANT de calculer l echeance du routage : l attente ne doit
    pas etre deduite du budget de recherche, sinon un appelant qui patiente
    verrait son routage tronque par la faute d un autre.
    """
    if not VERROU_DISPONIBLE:  # pragma: no cover - plateforme sans verrou
        logger.warning(
            "aucun verrouillage de fichier sur cette plateforme — les "
            "routages ne sont PAS serialises")
        yield
        return

    cible = chemin if chemin is not None else CHEMIN_PAR_DEFAUT
    cible.parent.mkdir(parents=True, exist_ok=True)
    descripteur = os.open(str(cible), os.O_RDWR | os.O_CREAT, 0o644)
    debut = time.monotonic()
    try:
        while True:
            if _essayer_de_prendre(descripteur):
                break
            patiente = time.monotonic() - debut
            if patiente >= attente_s:
                raise RoutageOccupe(patiente)
            time.sleep(_PAS_S)
        attendu = time.monotonic() - debut
        if attendu >= _PAS_S:
            logger.info("routage demarre apres %.0f s d attente", attendu)
        try:
            yield
        finally:
            _rendre(descripteur)
    finally:
        os.close(descripteur)

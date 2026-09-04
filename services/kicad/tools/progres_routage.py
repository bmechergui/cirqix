"""Progression d'un routage en cours, publiee pour une AUTRE requete.

Le routeur sait a chaque instant ou il en est : `_route_with_freerouting_api`
relit le journal de la JVM toutes les deux secondes et en tire le numero de
passe et le nombre de nets non routes. Cette mesure servait uniquement, en
interne, a couper l'attente d'un job fige. Elle ne sortait pas du service, et
l'utilisateur voyait « routage en cours » pendant vingt minutes.

⚠️ POURQUOI UN FICHIER, ET PAS UNE VARIABLE DE MODULE. Le service tourne avec
4 workers uvicorn, qui sont des PROCESSUS separes (cf. CLAUDE.md, section
thread-safety). La requete qui route et celle qui demande la progression ne
tombent pas forcement sur le meme worker : une variable de module ne serait
visible que de celui qui l'a ecrite, et le sondage rendrait « rien » trois fois
sur quatre — un silence indistinguable d'un routeur qui n'a pas commence.

⚠️ LA CLE VIENT DU CLIENT et nomme un fichier. Sans validation, une valeur
comme `../../etc/passwd` ferait ecrire ou lire hors du dossier. Meme famille
que l'injection shell de `scripts/livrer_boards.py`, corrigee le 2026-09-03 :
une donnee du client qui atteint le systeme de fichiers se valide, toujours.

Garde : `tests/test_progres_routage.py`.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

# Ou vivent les fichiers de progression. Meme conteneur que le routeur ; le
# dossier est cree a la demande.
RACINE_PAR_DEFAUT = Path(
    os.environ.get("CIRQIX_PROGRES_DIR", "/tmp/cirqix-progres"))

# Un identifiant, pas un chemin : lettres, chiffres, tiret, souligne. Assez
# large pour un UUID de run ou un identifiant de projet, assez etroit pour
# qu'aucune valeur ne designe un autre dossier.
_CLE_LEGITIME = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")


class CleInvalide(ValueError):
    """La cle ne peut pas nommer un fichier de progression."""


def chemin_du_progres(cle: str, racine: Optional[Path] = None) -> Path:
    """Fichier portant la progression de `cle`, ou leve si la cle est hostile."""
    if not isinstance(cle, str) or not _CLE_LEGITIME.match(cle):
        raise CleInvalide(
            "cle de progression invalide : attendu 1 a 128 caracteres "
            "parmi [A-Za-z0-9_-]")
    return (racine if racine is not None else RACINE_PAR_DEFAUT) / (cle + ".json")


def publier_progres(cle: str, *, passe: int, non_routes: int, nets: int,
                    palier: int, racine: Optional[Path] = None) -> None:
    """Publie l'avancement du routage `cle`, en ecrasant le precedent.

    L'ecriture passe par un fichier temporaire puis un `os.replace` : le
    lecteur voit l'ancienne version ou la nouvelle, jamais un JSON tronque.
    """
    chemin = chemin_du_progres(cle, racine)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    etat = {
        "passe": int(passe),
        "non_routes": int(non_routes),
        "nets": int(nets),
        "palier": int(palier),
        # Calcule ICI : le lecteur n'a pas a refaire la division, et deux
        # lecteurs ne peuvent pas l'arrondir differemment.
        "pourcentage": _pourcentage(non_routes, nets),
        # Sans horodatage, un routeur mort et un routeur lent se lisent pareil.
        "mis_a_jour": time.time(),
    }
    # ⚠️ Effacer a l entree du routage ne borne PAS le disque : une cle par
    # run n est jamais reutilisee, donc son fichier n est efface par personne.
    # La purge se greffe ici parce que c est le seul moment ou l on ecrit.
    _purger_anciens(chemin.parent)
    fd, provisoire = tempfile.mkstemp(dir=str(chemin.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as sortie:
            json.dump(etat, sortie)
        os.replace(provisoire, chemin)
    except BaseException:
        Path(provisoire).unlink(missing_ok=True)
        raise


def lire_progres(cle: str, racine: Optional[Path] = None) -> Optional[dict]:
    """Derniere progression publiee, ou None si rien n'a encore ete publie.

    ⚠️ Un fichier illisible rend None, pas une exception : la progression est
    un CONFORT d'affichage, jamais un verdict. Elle ne doit pas pouvoir faire
    echouer la requete qui la consulte.
    """
    chemin = chemin_du_progres(cle, racine)
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def oublier_progres(cle: str, racine: Optional[Path] = None) -> None:
    """Retire la progression de `cle`. Silencieux si elle n'existe plus."""
    chemin_du_progres(cle, racine).unlink(missing_ok=True)


def _pourcentage(non_routes: int, nets: int) -> int:
    if nets <= 0:
        return 0
    return max(0, min(100, round(100 * (nets - non_routes) / nets)))


# Au-dela, une progression ne decrit plus aucun routage vivant : le plafond
# d attente du routeur est de 300 s par palier, et l escalade en enchaine
# quelques-uns. Une heure couvre le pire cas connu (`stm32-100`, ~44 min) avec
# de la marge.
_PEREMPTION_S: float = 3600.0


def _purger_anciens(racine: Path, peremption_s: float = _PEREMPTION_S) -> int:
    """Efface les progressions perimees. Rend le nombre de fichiers retires.

    ⚠️ Toute erreur est avalee : la purge est un entretien, jamais une
    condition du routage. Un fichier verrouille ou disparu entre le listage et
    la suppression ne doit pas faire echouer la publication qui l a declenchee.
    """
    limite = time.time() - peremption_s
    retires = 0
    try:
        for fichier in racine.glob("*.json"):
            try:
                if fichier.stat().st_mtime < limite:
                    fichier.unlink(missing_ok=True)
                    retires += 1
            except OSError:
                continue
    except OSError:
        return retires
    return retires

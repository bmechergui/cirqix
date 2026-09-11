"""Des réglages que le SERVICE relit à chaque appel — pour rendre l'A/B possible.

## Pourquoi un fichier, et pas une variable d'environnement

⚠️ **MESURE DU 2026-09-09.** Une campagne A/B entière n'a rien mesuré. Le
pipeline (`run_pipeline.py`) est un simple **client HTTP** : le placement
s'exécute dans le service FastAPI, un processus **séparé**, démarré au lancement
du conteneur. `CIRQIX_GRAINE_HIERARCHIQUE=1` posé dans le shell du pipeline ne
l'atteint jamais.

Les deux bras étaient donc **identiques** — 98 % contre 98 %, ce qui ressemble à
« aucun effet » et ne prouve rien. C'est la famille de défauts que ce dépôt
traque : **une règle jamais exécutée est indistinguable d'une règle sans effet.**

C'est exactement la raison qui a fait choisir un fichier pour le verrou de
routage (`tools/verrou_routage.py`) : les quatre workers uvicorn sont des
processus distincts, et un fichier est la seule ressource qu'ils partagent.

## Ce que ce module n'est pas

Ce n'est **pas** un mécanisme de configuration produit. C'est un instrument de
mesure : il permet de désarmer une règle sans éditer le code ni recréer le
conteneur, donc de produire un TÉMOIN. Sans témoin, on impute au dernier
changement une régression qu'il n'a pas causée — ce dépôt a déjà failli annuler
un correctif innocent faute d'en avoir lancé un.

⚠️ **RELU À CHAQUE APPEL, jamais mis en cache.** Un réglage lu une fois à
l'import serait figé pour la vie du service : le bras suivant hériterait du
précédent, et la campagne comparerait deux fois la même chose. C'est
précisément le défaut que ce module corrige — le reproduire ici serait
particulièrement ironique.

⚠️ **UN FICHIER ABSENT N'EST PAS UNE ERREUR** : c'est le cas normal, et les
défauts s'appliquent. Mais un fichier ILLISIBLE l'est, et on le dit — un
réglage silencieusement ignoré rendrait la mesure fausse sans le signaler.

Usage, depuis l'hôte ou le pipeline :

    echo '{"graine_hierarchique": true}' > /tmp/cirqix-reglages.json
    …
    rm -f /tmp/cirqix-reglages.json
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CHEMIN = Path(os.environ.get("CIRQIX_REGLAGES", "/tmp/cirqix-reglages.json"))


def _du_fichier() -> dict:
    """Le contenu du fichier de réglages, ou un dictionnaire vide."""
    try:
        if not _CHEMIN.is_file():
            return {}
        brut = json.loads(_CHEMIN.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        # ⚠️ On le DIT. Un fichier illisible traité comme absent ferait tourner
        # le bras A/B avec les valeurs par défaut, donc mesurer le témoin deux
        # fois en croyant comparer.
        logger.error("reglages: %s ILLISIBLE (%s) — les valeurs par defaut "
                     "s appliquent, la mesure de ce tirage ne vaut rien",
                     _CHEMIN, e)
        return {}
    if not isinstance(brut, dict):
        logger.error("reglages: %s ne contient pas un objet — ignore", _CHEMIN)
        return {}
    return brut


def reglages_actifs() -> dict:
    """Les réglages en vigueur, tels que lus MAINTENANT (dict vide = défauts)."""
    return dict(_du_fichier())


def journaliser_les_reglages(ou: str) -> dict:
    """Écrit dans le journal les réglages qui s appliquent à cet appel.

    ⚠️ Mesure du 2026-09-11 : `{"graine_hierarchique": true}` posé le 09/09
    pour un A/B est resté dans `/tmp/cirqix-reglages.json` DEUX JOURS et a
    piloté toutes les campagnes suivantes sans qu aucune ligne ne le dise —
    carte-08 livrée avec ses découplages à 13-32 mm du MCU. Un levier de
    banc actif se lit au journal, ou il n existe pas.
    """
    actifs = reglages_actifs()
    if actifs:
        logger.warning("%s : REGLAGES DE BANC ACTIFS %s (%s) — ce tirage n est "
                       "pas la production", ou, actifs, _CHEMIN)
    return actifs


def reglage(nom: str, defaut: Any) -> Any:
    """Rend le réglage `nom`, relu À CHAQUE APPEL.

    Ordre : le fichier, puis la variable d'environnement `CIRQIX_<NOM>`, puis
    le défaut. Le fichier passe en premier parce que c'est le seul canal qui
    atteint un service déjà démarré.
    """
    fichier = _du_fichier()
    if nom in fichier:
        return fichier[nom]

    brut = os.environ.get("CIRQIX_" + nom.upper())
    if brut is None:
        return defaut
    if isinstance(defaut, bool):
        return brut not in ("", "0", "false", "False")
    if isinstance(defaut, float):
        try:
            return float(brut)
        except ValueError:
            logger.error("reglages: CIRQIX_%s=%r n est pas un nombre — defaut",
                         nom.upper(), brut)
            return defaut
    return brut

# ⚠️ MESURE DU 2026-09-09, LE MEME JOUR QUE LE FICHIER DE REGLAGES. Une seconde
# campagne A/B n a rien mesure non plus, pour une raison DIFFERENTE : le service
# avait charge `tools/placement.py` a son demarrage, neuf heures avant que la
# regle n y soit ecrite.
#
#     demarrage du service    07:03
#     modification du module  16:15
#
# `tools/` est monte a chaud : le FICHIER change, le MODULE deja importe non.
# Les quatre workers uvicorn executaient l ancien code, et la campagne comparait
# encore deux bras identiques — « aucun effet », la reponse qu on attendait.
#
# Ce depot connaissait le piege (« Editions du service pendant un run — le
# runner ENFANT relit le fichier a chaque appel »). L exception porte sur les
# processus enfants ; le workflow de placement, lui, tourne DANS le worker.
#
# La regle : apres toute edition d un module que le service importe, il faut le
# REDEMARRER avant de mesurer quoi que ce soit.


def version_du_module(module) -> str:
    """Le moment ou le fichier d un module a ete modifie, tel que le processus
    COURANT le voit — pour comparer au demarrage du service.

    Rend une chaine vide si le module n a pas de fichier sur disque.
    """
    import datetime
    chemin = getattr(module, "__file__", None)
    if not chemin:
        return ""
    try:
        t = Path(chemin).stat().st_mtime
    except OSError:
        return ""
    return datetime.datetime.fromtimestamp(t).isoformat(timespec="seconds")


def avertir_si_module_plus_recent_que_le_processus(module) -> bool:
    """Journalise une ERREUR si le fichier est plus recent que ce processus.

    Rend `True` quand l ecart est detecte — c est-a-dire quand le code execute
    n est probablement PAS celui du disque, et qu aucune mesure ne vaut.
    """
    import os
    chemin = getattr(module, "__file__", None)
    if not chemin:
        return False
    try:
        mtime = Path(chemin).stat().st_mtime
        debut = Path("/proc/self/stat").stat().st_mtime
    except OSError:
        return False
    if mtime <= debut:
        return False
    logger.error(
        "reglages: %s a ete modifie APRES le demarrage de ce processus "
        "(pid %d) — le code execute n est pas celui du disque, redemarrer le "
        "service avant toute mesure", chemin, os.getpid())
    return True

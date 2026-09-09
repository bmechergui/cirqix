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

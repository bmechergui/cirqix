"""La progression sort-elle vraiment du service ?

⚠️ Deux questions distinctes, et la seconde a deja coute cher a ce depot :
le mecanisme est-il CORRECT, et est-il APPELE ? Un module de progression
parfait que personne n'invoque est indistinguable d'un module absent — c'est
ce qui a masque pendant des semaines le fait que le Geometre CMA-ES ne
tournait jamais en production.

⚠️ La route se verifie dans la TABLE DE ROUTES, jamais dans le fichier source :
`@router.post("/route/auto")` a decore `_armer_abandon` pendant toute sa vie
parce qu'une fonction s'etait glissee entre le decorateur et sa cible. Le
fichier avait l'air juste ; la route etait ailleurs.
"""
from __future__ import annotations

import inspect

from routers import routing as routage


def _routes_du_module() -> dict:
    """Chemin -> nom de l'endpoint REELLEMENT enregistre."""
    return {r.path: r.endpoint.__name__
            for r in routage.router.routes if hasattr(r, "endpoint")}


def test_la_route_de_progression_est_enregistree() -> None:
    routes = _routes_du_module()
    assert "/route/progress/{cle}" in routes, (
        "la route de progression n'est pas dans la table : "
        f"routes vues = {sorted(routes)}")


def test_la_route_de_progression_pointe_sur_la_bonne_fonction() -> None:
    """Une fonction glissee entre le decorateur et sa cible passerait ici."""
    assert _routes_du_module()["/route/progress/{cle}"] == "route_progress"


def test_le_routage_reste_joignable() -> None:
    """Garde jumelle : ne pas deplacer `/route/auto` en ajoutant la voisine."""
    assert _routes_du_module()["/route/auto"] == "route_auto"


def test_la_requete_de_routage_accepte_une_cle_de_progression() -> None:
    champs = routage.RouteAutoRequest.model_fields
    assert "progress_key" in champs
    # Optionnelle : tout appelant existant continue de fonctionner sans elle.
    req = routage.RouteAutoRequest(kicad_pcb_b64="", layers=2)
    assert req.progress_key is None


def test_la_boucle_de_sondage_publie_la_progression() -> None:
    """Le cablage : la boucle Freerouting appelle-t-elle la publication ?

    ⚠️ Garde ancree sur le CORPS de la fonction, pas sur une phrase de
    commentaire ni sur le nom d'un fichier : deux gardes du 2026-08-31 se sont
    mises a lever des qu'une fonction voisine a ete renommee.
    """
    source = inspect.getsource(routage._route_with_freerouting_api)
    assert "publier_progres(" in source, (
        "la boucle de sondage ne publie plus la progression — le service "
        "mesure toujours, mais plus personne ne peut la lire")


def test_le_routage_efface_la_progression_residuelle_avant_de_commencer() -> None:
    """Sinon un sondeur lirait l'avancement du routage PRECEDENT.

    ⚠️ Le nettoyage est a l'ENTREE, pas a la sortie. Une premiere version
    enveloppait `route_auto` dans un `try/finally` : la fonction longue prenait
    un autre nom, et les DIX gardes qui lisent son corps par `getsource` se
    mettaient a lire l'enveloppe — trois lignes ne contenant aucune des regles
    qu'elles verifient. Elles restaient justes, elles regardaient ailleurs.

    A l'entree, la propriete voulue tient quand meme : un run qui publie sous
    une cle efface d'abord ce qui trainait sous cette cle.
    """
    source = inspect.getsource(routage.route_auto)
    assert "oublier_progres(" in source


def test_les_progressions_anciennes_sont_purgees() -> None:
    """Nettoyer a l'entree ne suffit pas a borner le disque.

    Une cle par run (un UUID) n'est jamais reutilisee : son fichier ne serait
    efface par personne. La publication purge donc les fichiers perimes.
    """
    source = inspect.getsource(routage.publier_progres)
    assert "purger" in source

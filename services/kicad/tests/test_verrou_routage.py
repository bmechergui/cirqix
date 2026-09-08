"""Un seul routage a la fois — verrou entre PROCESSUS.

⚠️ MESURE DU 2026-09-03 : un routage monte a **6,2 Go de memoire residente**
(`stm32-baseline`, le plus petit board du banc). Deux en parallele depassent les
7,6 Go de la machine et le noyau tue le processus :

    Out of memory: Killed process (python3)  anon-rss:6247616kB

Le service tourne pourtant avec `--workers 4`, c est-a-dire qu il annonce quatre
requetes simultanees quand la memoire n en autorise qu une.

⚠️ POURQUOI UN VERROU PLUTOT QU UN SEUL WORKER. Ramener le service a 1 worker
reglerait la memoire et casserait tout le reste : `GET /route/progress` — la
progression livree le meme jour — attendrait la fin d un routage de vingt
minutes, et `GET /health`, dont Docker se sert pour juger le conteneur,
resterait sans reponse pendant ce temps. Le conteneur serait declare malade a
chaque routage. On garde donc les 4 workers pour les requetes legeres, et on
serialise LE SEUL point couteux.

⚠️ ET UN VERROU DANS LE PROCESSUS NE SUFFIT PAS. Les 4 workers sont des
processus separes : un `threading.Lock` en verrouillerait un seul, et quatre
routages resteraient possibles. Le verrou porte donc sur un FICHIER, seule
ressource que les quatre partagent.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from tools.verrou_routage import (
    RoutageOccupe,
    VERROU_DISPONIBLE,
    verrou_de_routage,
)


def test_un_routage_seul_obtient_le_verrou(tmp_path: Path) -> None:
    with verrou_de_routage(attente_s=1, chemin=tmp_path / "v.lock"):
        pass  # ne leve pas


def test_le_verrou_est_rendu_apres_usage(tmp_path: Path) -> None:
    chemin = tmp_path / "v.lock"
    with verrou_de_routage(attente_s=1, chemin=chemin):
        pass
    with verrou_de_routage(attente_s=1, chemin=chemin):
        pass  # le second passe : le premier a bien rendu


def test_le_verrou_est_rendu_meme_sur_exception(tmp_path: Path) -> None:
    """Un routage qui echoue ne doit pas condamner tous les suivants."""
    chemin = tmp_path / "v.lock"
    with pytest.raises(ValueError):
        with verrou_de_routage(attente_s=1, chemin=chemin):
            raise ValueError("le routage a echoue")
    with verrou_de_routage(attente_s=1, chemin=chemin):
        pass


@pytest.mark.skipif(not VERROU_DISPONIBLE,
                    reason="plateforme sans verrouillage de fichier")
def test_un_second_routage_attend_puis_renonce(tmp_path: Path) -> None:
    """Le coeur : deux routages simultanes ne coexistent pas.

    ⚠️ On RENONCE au lieu d attendre indefiniment, et on le DIT. Un routage
    qui attendrait sans borne ressemblerait a un routage lent — or ce depot a
    deja paye la confusion entre « lent » et « bloque » (cf. la detection de
    stagnation, qui suit le NUMERO de passe et non le pourcentage).
    """
    chemin = tmp_path / "v.lock"
    with verrou_de_routage(attente_s=1, chemin=chemin):
        debut = time.time()
        with pytest.raises(RoutageOccupe):
            with verrou_de_routage(attente_s=1, chemin=chemin):
                pass
        # Il a bien ATTENDU avant de renoncer, il n a pas refuse aussitot.
        assert time.time() - debut >= 0.5


@pytest.mark.skipif(not VERROU_DISPONIBLE,
                    reason="plateforme sans verrouillage de fichier")
def test_le_second_passe_des_que_le_premier_a_fini(tmp_path: Path) -> None:
    """Attendre doit SERVIR : le suivant part des que la place se libere."""
    import threading

    chemin = tmp_path / "v.lock"
    vus: list = []

    def second() -> None:
        try:
            with verrou_de_routage(attente_s=10, chemin=chemin):
                vus.append("obtenu")
        except RoutageOccupe:
            vus.append("renonce")

    with verrou_de_routage(attente_s=1, chemin=chemin):
        fil = threading.Thread(target=second)
        fil.start()
        time.sleep(0.5)          # il patiente pendant qu on tient le verrou
        assert vus == []
    fil.join(timeout=10)
    assert vus == ["obtenu"]


def test_le_message_dit_quoi_faire() -> None:
    """Un refus doit se lire, pas se deviner."""
    message = str(RoutageOccupe())
    assert "routage" in message.lower()
    assert "memoire" in message.lower() or "6,2" in message


# --- le cablage : la regle est-elle APPELEE ? -----------------------------

def test_la_route_de_routage_porte_le_verrou() -> None:
    """Une regle correcte que personne n invoque n existe pas.

    ⚠️ Et le decorateur doit rester COLLE a sa cible : `@router.post` a deja
    decore la mauvaise fonction dans ce fichier, parce qu une definition
    s etait glissee entre les deux. On interroge donc la table de routes.
    """
    from routers import routing as routage

    routes = {r.path: r.endpoint for r in routage.router.routes
              if hasattr(r, "endpoint")}
    endpoint = routes["/route/auto"]
    assert endpoint.__name__ == "route_auto"
    # `functools.wraps` a pose `__wrapped__` : la preuve que l enveloppe est la.
    assert hasattr(endpoint, "__wrapped__"), (
        "la route n est plus enveloppee : les routages ne sont plus serialises")


def test_les_gardes_lisant_le_corps_voient_toujours_le_corps() -> None:
    """Dix gardes lisent `getsource(route_auto)` — le decorateur ne doit pas
    les faire lire une enveloppe de trois lignes.

    C est exactement l erreur commise plus tot le 2026-09-03 en scindant la
    fonction : les gardes restaient justes, elles regardaient ailleurs.
    """
    import inspect

    from routers import routing as routage

    source = inspect.getsource(routage.route_auto)
    assert "_layer_ladder" in source or "meilleur" in source, (
        "getsource ne rend plus le corps du routage")
    assert len(source.splitlines()) > 100, (
        "getsource rend l enveloppe (%d lignes) et non le corps"
        % len(source.splitlines()))


def test_un_service_occupe_repond_503_et_pas_un_faux_succes() -> None:
    """⚠️ Jamais de `skipped` ni de `routed_percent: 0` : ils se liraient comme
    un verdict de routage alors qu aucun n a eu lieu. Le depot a deja paye
    cette confusion — « 0 % (aucun moteur) » n est pas un verdict, c est une
    panne.
    """
    import inspect

    from routers import routing as routage

    source = inspect.getsource(routage._un_seul_routage_a_la_fois)
    assert "503" in source
    assert "RoutageOccupe" in source

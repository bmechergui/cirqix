"""La session Freerouting est REUTILISEE, pas recreee a chaque routage.

⚠️ MESURE DU 2026-09-03 : `GET /v1/sessions/list` rendait **14 sessions**, une
par routage depuis le demarrage de la JVM, et la JVM annoncait 417 Mo utilises
sur 582 disponibles — son tas est FIXE (~400 Mo, cf. CLAUDE.md). Rien ne les
libere : la seule anomalie mesuree qui accompagne l instabilite du service.

⚠️ **L API NE SAIT PAS SUPPRIMER UNE SESSION.** Verifie sur la v2.1.0 embarquee,
avec les en-tetes d identite complets :

    DELETE /v1/sessions/{id}        -> 500 « HTTP 405 Method Not Allowed »
    POST   /v1/sessions/{id}/delete -> 404
    GET    /v1/sessions/{id}        -> 200   (elle existe bien)

C est la meme famille que `PUT /jobs/{id}/cancel` qui repond 501 : Freerouting
cree, il ne defait pas. Le seul levier est donc de **ne pas en creer plus
d une**. On garde la session ouverte et on y enfile les jobs suivants.

⚠️ 4 workers uvicorn = 4 processus = au plus 4 sessions, contre une par
routage. Le compte devient BORNE, ce qui est le point.
"""
from __future__ import annotations

import routers.routing as routage


class _FauxAppel:
    """Enregistre les appels et rend des reponses plausibles."""

    def __init__(self, sessions_valides: set[str] | None = None) -> None:
        self.appels: list[tuple[str, str]] = []
        self.sessions_creees = 0
        self._valides = sessions_valides if sessions_valides is not None else set()

    def __call__(self, methode: str, chemin: str, payload=None, base=None):
        self.appels.append((methode, chemin))
        if chemin.endswith("/sessions/create"):
            self.sessions_creees += 1
            sid = "session-%d" % self.sessions_creees
            self._valides.add(sid)
            return {"id": sid}
        if "/sessions/" in chemin:
            sid = chemin.rsplit("/", 1)[-1]
            if sid not in self._valides:
                raise RuntimeError("session inconnue")
            return {"id": sid}
        raise AssertionError("appel inattendu : %s %s" % (methode, chemin))


def _reinitialiser() -> None:
    routage._SESSION_FREEROUTING = None


def test_la_premiere_demande_cree_une_session(monkeypatch) -> None:
    _reinitialiser()
    faux = _FauxAppel()
    monkeypatch.setattr(routage, "_api", faux)
    assert routage._session_freerouting("/v1") == "session-1"
    assert faux.sessions_creees == 1


def test_la_seconde_demande_REUTILISE_la_meme(monkeypatch) -> None:
    """Le coeur du correctif : une session par PROCESSUS, pas par routage."""
    _reinitialiser()
    faux = _FauxAppel()
    monkeypatch.setattr(routage, "_api", faux)
    premiere = routage._session_freerouting("/v1")
    seconde = routage._session_freerouting("/v1")
    assert premiere == seconde
    assert faux.sessions_creees == 1, (
        "une seconde session a ete creee : le compte redevient non borne")


def test_une_session_disparue_est_recreee(monkeypatch) -> None:
    """La JVM redemarre, ou purge ses sessions : on ne doit pas rester bloque.

    ⚠️ Sans cette reprise, un redemarrage de Freerouting condamnerait TOUS les
    routages suivants du worker — un cache qui survit a ce qu il cache.
    """
    _reinitialiser()
    faux = _FauxAppel()
    monkeypatch.setattr(routage, "_api", faux)
    routage._session_freerouting("/v1")
    faux._valides.clear()  # la JVM a redemarre
    seconde = routage._session_freerouting("/v1")
    assert seconde == "session-2"
    assert faux.sessions_creees == 2


def test_la_verification_precede_la_reutilisation(monkeypatch) -> None:
    """On VERIFIE avant de reutiliser, on ne suppose pas.

    Une session morte reutilisee sans controle ferait echouer l enfilement du
    job, plus loin et avec un message sans rapport.
    """
    _reinitialiser()
    faux = _FauxAppel()
    monkeypatch.setattr(routage, "_api", faux)
    routage._session_freerouting("/v1")
    faux.appels.clear()
    routage._session_freerouting("/v1")
    assert any(m == "GET" and "/sessions/" in c for m, c in faux.appels), (
        "la session est reutilisee sans avoir ete verifiee")


def test_le_routeur_passe_par_le_cache_de_session() -> None:
    """Le cablage : `_route_with_freerouting_api` ne cree plus en direct.

    ⚠️ Un cache correct que l appelant contourne est indistinguable d un cache
    absent — la lecon du Geometre CMA-ES, qui ne tournait jamais en production.
    """
    import inspect

    source = inspect.getsource(routage._route_with_freerouting_api)
    assert "_session_freerouting(" in source
    assert "sessions/create" not in source, (
        "le routeur cree encore une session en direct, court-circuitant le cache")


def test_deux_threads_ne_creent_qu_une_session(monkeypatch) -> None:
    """Le verrou : sans lui, chacun cree la sienne et l une devient orpheline.

    ⚠️ Les routes du service sont declarees `def`, donc executees dans le POOL
    DE THREADS de FastAPI : deux routages recus par le meme worker touchent la
    meme variable de module. Le perdant rendrait l id de l autre, et sa propre
    session — que l API ne sait pas supprimer — ne serait plus jamais reclamee.
    """
    import threading
    import time

    _reinitialiser()
    faux = _FauxAppel()
    creation_reelle = faux.__call__

    def _api_lent(methode, chemin, payload=None, base=None):
        if chemin.endswith("/sessions/create"):
            # La creation est LENTE : sans verrou, le second thread a tout le
            # temps d entrer ici pendant que le premier y est. Une barriere
            # serait un piege — elle exigerait que les DEUX y entrent, donc
            # ferait echouer le code correct, qui n en laisse passer qu un.
            time.sleep(0.3)
        return creation_reelle(methode, chemin, payload, base)

    monkeypatch.setattr(routage, "_api", _api_lent)
    vus: list = []
    fils = [threading.Thread(target=lambda: vus.append(
        routage._session_freerouting("/v1"))) for _ in range(2)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=10)

    assert faux.sessions_creees == 1, (
        "%d sessions creees : le verrou ne serialise pas la creation, et la "
        "session perdante est ORPHELINE — l API ne sait pas la supprimer"
        % faux.sessions_creees)
    assert vus == [vus[0], vus[0]]


def test_une_creation_sans_identifiant_leve_un_message_lisible(monkeypatch) -> None:
    """`KeyError: 'id'` remonte tel quel se lit « Freerouting API echoue ('id') »."""
    import pytest

    _reinitialiser()
    monkeypatch.setattr(routage, "_api", lambda *a, **k: {"erreur": "quota"})
    with pytest.raises(RuntimeError, match="sans identifiant"):
        routage._session_freerouting("/v1")

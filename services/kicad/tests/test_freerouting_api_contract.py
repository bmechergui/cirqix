"""Le client de l'API Freerouting parlait une API qui n'existe pas.

La JVM persistante (~400 Mo, port 37864) tourne depuis toujours et répond
correctement. Le Niveau 2 de `route_auto` n'a pourtant JAMAIS été emprunté :
`_find_freerouting_api` sondait `/api/v1/system/status`, un chemin que
Freerouting v2.1.0 ne sert pas. La sonde renvoyait donc toujours `None`, et
chaque routage repartait sur le Niveau 3 — un `java -jar` complet, démarrage de
JVM compris, pendant que la JVM persistante attendait pour rien.

Contrat mesuré le 2026-08-20 contre l'instance de PRODUCTION (port 37864) :

    GET  /api/v1/system/status          -> 404
    GET  /v1/system/status              -> 200  {"status": "OK", ...}
    POST /v1/sessions/create  sans en-têtes
                                        -> 500  « Freerouting-Profile-ID or
                                           Freerouting-Profile-Email ... must be set »
    POST /v1/sessions/create  avec en-têtes
                                        -> 200  {id, user_id, host}
    POST /v1/jobs/enqueue               -> 200  {"state": "QUEUED"}   (MAJUSCULES)
    POST /v1/jobs/{id}/input  multipart -> 500  HTTP 415 Unsupported Media Type
    POST /v1/jobs/{id}/input  {"data"}  -> 200
    PUT  /v1/jobs/{id}/start            -> 200
    POST /v1/jobs/{id}/start            -> 500  HTTP 405 Method Not Allowed
    GET  /v1/jobs/{id}/output           -> 400  « The job hasn't finished yet. »

Quatre erreurs indépendantes du client, chacune suffisante à elle seule :
préfixe `/api`, absence d'authentification, envoi en multipart, et comparaison
d'état en minuscules.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402

SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")


def _code_seul(source: str) -> str:
    """Retire les lignes de commentaire — elles CITENT le mauvais chemin exprès."""
    lignes = [
        ligne for ligne in source.splitlines() if not ligne.lstrip().startswith("#")
    ]
    return chr(10).join(lignes)


class TestChemins:
    def test_aucun_appel_ne_prefixe_par_api(self):
        # `/api/v1/...` n'existe pas en v2.1.0 : les contrôleurs JAX-RS sont
        # montés sous `/v1/...`. Un seul `/api` résiduel suffit à faire 404.
        assert "/api/v1" not in _code_seul(SOURCE)

    def test_la_sonde_interroge_le_vrai_chemin(self):
        assert "/v1/system/status" in SOURCE


class TestAuthentification:
    def test_les_en_tetes_d_authentification_sont_envoyes(self):
        # Sans eux, `POST /v1/sessions/create` répond 500 avec un message
        # explicite : le serveur exige une identité, même en local.
        for entete in (
            "Freerouting-Profile-ID",
            "Freerouting-Profile-Email",
            "Freerouting-Environment-Host",
        ):
            assert entete in SOURCE, f"en-tête manquant : {entete}"

    def test_les_en_tetes_accompagnent_chaque_appel(self):
        entetes = routing_router._freerouting_api_headers()
        assert entetes["Freerouting-Profile-ID"]
        assert entetes["Freerouting-Environment-Host"]
        # `Content-Type` est ajouté par appel ; l'identité, elle, est constante.
        assert "Freerouting-Profile-Email" in entetes


class TestEnvoiDuDsn:
    def test_le_dsn_part_en_json_et_non_en_multipart(self):
        # Le multipart renvoie 415 : le serveur attend un `BoardFilePayload`.
        assert "multipart/form-data" not in SOURCE
        assert "Content-Disposition" not in SOURCE

    def test_le_payload_porte_le_champ_data(self):
        payload = routing_router._freerouting_input_payload(b"(pcb x)")
        assert "data" in payload
        import base64
        assert base64.b64decode(payload["data"]) == b"(pcb x)"


class TestEtatsDuJob:
    def test_l_etat_est_compare_sans_tenir_compte_de_la_casse(self):
        # Le serveur sérialise l'enum en MAJUSCULES ("QUEUED", "COMPLETED").
        # L'ancien client comparait à "completed" : la boucle de sondage ne
        # sortait donc jamais et finissait en timeout, sur un job pourtant fini.
        assert routing_router._freerouting_job_done("COMPLETED") is True
        assert routing_router._freerouting_job_done("completed") is True
        assert routing_router._freerouting_job_done("QUEUED") is False

    def test_les_etats_d_echec_sont_reconnus_dans_les_deux_casses(self):
        for etat in ("FAILED", "failed", "CANCELLED", "cancelled"):
            assert routing_router._freerouting_job_failed(etat) is True
        assert routing_router._freerouting_job_failed("RUNNING") is False

    def test_le_demarrage_utilise_PUT(self):
        # `POST /v1/jobs/{id}/start` répond 405.
        assert re.search(r'"PUT",\s*f?"[^"]*jobs/\{job_id\}/start"', SOURCE)

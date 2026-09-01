"""Quand la recuperation ne rend rien, elle doit DIRE pourquoi.

⚠️ Mesure du 2026-08-31, banc a placement fige, `stm32-100` : six tirages
figes (56, 78, 57 % a 2 couches ; 81, 41 % a 4), puis budget epuise, puis
`_recuperer_jobs_abandonnes` appelee — et la carte sort en ECHEC total.

Le journal ne permet pas de savoir POURQUOI la recuperation a echoue. Trois
causes possibles, indistinguables :

    aucun job n a ete enregistre dans `_JOBS_ABANDONNES`
    les jobs existent mais tournent encore (state != COMPLETED)
    les jobs ont fini mais leur sortie est vide

Seule la deuxieme serait normale — un job abandonne finit seul, mais pas
forcement avant qu on le lui demande. Les deux autres seraient des defauts. Ne
pas pouvoir les separer, c est ne pas pouvoir corriger.

⚠️ Ce fichier ne change AUCUN comportement : il n ajoute que le compte. La
regle du projet est constante — « un message qui n a pas compte peut mentir »,
et un silence ne dit pas si l on a mesure zero ou si l on n a jamais mesure.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestApiJoignableDepuisLeModule:
    """⚠️ NEUVIEME DEFAUT, et le plus net : `_api` etait IMBRIQUEE.

    `_recuperer_jobs_abandonnes`, au niveau module, appelait `_api(...)` — une
    fonction definie a l interieur de `_route_with_freerouting_api`. Chaque
    appel levait `NameError: name '_api' is not defined`, avale par son
    `except Exception` et rendu comme un `None` ordinaire.

    Le dernier recours de la chaine n a donc JAMAIS fonctionne. Il est reste
    invisible parce que son echec est indistinguable de son cas normal : les
    deux rendent `None`. Il n est apparu qu une fois le diagnostic ajoute.
    """

    def test_api_est_appelable_depuis_le_module(self):
        assert callable(getattr(R, "_api", None)), (
            "_api n est pas au niveau module : tout appelant exterieur a "
            "`_route_with_freerouting_api` levera NameError")

    def test_aucune_fonction_imbriquee_ne_l_ombrage(self):
        source = (_SERVICE_ROOT / "routers" / "routing.py").read_text(
            encoding="utf-8")
        # Une definition INDENTEE de `_api` reintroduirait l ombrage.
        assert "    def _api(" not in source


class TestDiagnostic:
    def test_aucun_job_enregistre_est_DIT(self, caplog, monkeypatch):
        monkeypatch.setattr(R, "_JOBS_ABANDONNES", [])
        with caplog.at_level(logging.INFO, logger="routers.routing"):
            assert R._recuperer_jobs_abandonnes(b"(kicad_pcb)") is None
        assert "aucun job abandonne" in caplog.text

    def test_un_job_encore_en_cours_est_DIT(self, caplog, monkeypatch):
        monkeypatch.setattr(R, "_JOBS_ABANDONNES",
                            [{"pre": "http://x/v1", "job_id": "j1", "percent": 72}])
        monkeypatch.setattr(R, "_api", lambda *a, **k: {"state": "RUNNING"})
        with caplog.at_level(logging.INFO, logger="routers.routing"):
            assert R._recuperer_jobs_abandonnes(b"(kicad_pcb)") is None
        assert "1 job(s)" in caplog.text
        assert "en cours" in caplog.text

    def test_une_sortie_vide_est_DITE(self, caplog, monkeypatch):
        monkeypatch.setattr(R, "_JOBS_ABANDONNES",
                            [{"pre": "http://x/v1", "job_id": "j1", "percent": 72}])

        def faux_api(methode, url, *a, **k):
            return {"state": "COMPLETED"} if not url.endswith("output") else {}

        monkeypatch.setattr(R, "_api", faux_api)
        with caplog.at_level(logging.INFO, logger="routers.routing"):
            assert R._recuperer_jobs_abandonnes(b"(kicad_pcb)") is None
        assert "sortie vide" in caplog.text

    def test_le_succes_reste_annonce_comme_avant(self, caplog, monkeypatch):
        monkeypatch.setattr(R, "_JOBS_ABANDONNES",
                            [{"pre": "http://x/v1", "job_id": "j1", "percent": 72}])

        def faux_api(methode, url, *a, **k):
            if url.endswith("output"):
                return {"data": "AAAA"}
            return {"state": "COMPLETED"}

        monkeypatch.setattr(R, "_api", faux_api)
        monkeypatch.setattr(R, "_specctra_roundtrip", lambda pcb, ses: b"(board)")
        with caplog.at_level(logging.INFO, logger="routers.routing"):
            assert R._recuperer_jobs_abandonnes(b"(kicad_pcb)") == b"(board)"
        assert "RECUPERE" in caplog.text

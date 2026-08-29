"""Couper l ATTENTE d un job fige — pas le job, qu on ne peut pas tuer.

Mesure du 2026-08-29 : sur `stm32-100` a 2 couches, Freerouting fait tout son
travail a la passe 4 puis repete 995 passes identiques — 44 minutes dont une
dizaine de secondes utiles. `cancel` repond 501, `max_passes` est ignore, et
les parametres du routeur sont interdits (decision utilisateur).

Ce qui reste, et qui suffit : son JOURNAL, une ligne par passe avec score et
nets non routes. Sur 461 jobs mesures, le plus grand ecart entre deux progres
est de 144 passes — une fenetre de 150 ne coupe aucun job vivant.

⚠️ On coupe l ATTENTE, jamais le job : la JVM le digere en fond, et elle
EXECUTE DEUX JOBS EN PARALLELE (verifie le 2026-08-29, deux jobs RUNNING
simultanement) — le palier suivant demarre donc sans attendre le cadavre.

Grok, consulte : « le stall EST la preuve que 2c a echoue » — la regle
utilisateur « partir de 2, escalader sur preuve » est respectee ; seule
l attente de la preuve raccourcit.
"""
from __future__ import annotations

import pytest

from routers.routing import (_passes_sans_progres, _STAGNATION_PASSES,
                             RoutageFige)


def _log(job: str, seq: list) -> str:
    return "\n".join(
        f"2026-08-29 15:00:{i%60:02d}.000 INFO   [{job}] Auto-router pass #{i+1} "
        f"on board 'x' was completed in 2.00 seconds with the score of "
        f"{score:.2f} ({unrouted} unrouted), using 1.0 CPU seconds and 1 MB memory."
        for i, (score, unrouted) in enumerate(seq))


class TestDetection:
    def test_un_job_qui_progresse_ne_stagne_pas(self):
        seq = [(100.0 + i, 50 - i) for i in range(60)]
        assert _passes_sans_progres(_log("AAAAAA", seq), "AAAAAA") == 0

    def test_les_passes_plates_sont_comptees(self):
        seq = [(100.0, 50)] * 3 + [(200.0, 40)] + [(200.0, 40)] * 30
        assert _passes_sans_progres(_log("AAAAAA", seq), "AAAAAA") == 30

    def test_le_journal_d_un_autre_job_ne_compte_pas(self):
        """Deux jobs tournent en PARALLELE : filtrer est obligatoire."""
        seq_fige = [(100.0, 50)] * 40
        log = _log("AAAAAA", seq_fige) + "\n" + _log("BBBBBB", [(1.0 + i, 9 - i) for i in range(9)])
        assert _passes_sans_progres(log, "BBBBBB") == 0

    def test_un_journal_illisible_rend_zero(self):
        """Fail-safe : sans mesure on ATTEND, on n abandonne pas a l aveugle."""
        assert _passes_sans_progres("pas un journal", "AAAAAA") == 0


class TestFenetre:
    def test_la_fenetre_ne_coupe_aucun_job_vivant_mesure(self):
        """Plus grand ecart mesure entre deux progres : 144 passes."""
        assert _STAGNATION_PASSES > 144

    def test_la_fenetre_reste_utile(self):
        """A 2,7 s la passe, 200 passes ~ 9 min : au-dela on repaye l attente."""
        assert _STAGNATION_PASSES <= 200


class TestException:
    def test_l_exception_porte_l_estimation(self):
        exc = RoutageFige(unrouted=46, nets=79)
        assert exc.routed_percent == 42   # round(100 * (79-46) / 79)
        assert "46" in str(exc)

    def test_sans_nets_l_estimation_est_nulle_pas_fausse(self):
        assert RoutageFige(unrouted=5, nets=0).routed_percent == 0

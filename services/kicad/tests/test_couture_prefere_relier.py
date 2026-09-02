"""La couture PRÉFÈRE un point qui relie vraiment — sans jamais l'exiger.

⚠️ Mesure du 2026-09-02, board final de `nucleo-f401`. Les signaux sont routés
à 100 % ; ce qui bloque le 100 % global est la masse, et il reste huit ruptures
`plan ↔ plan` sur les quatre cartes. Analyse des dix îlots de `nucleo-f401` :

    F.Cu  11002 mm²   cuivre en face = oui
    B.Cu  11002 mm²   cuivre en face = oui
    F.Cu   1480 mm²   cuivre en face = oui
    B.Cu    238 mm²   cuivre en face = NON      <- via borgne
    F.Cu    128 mm²   cuivre en face = NON      <- via borgne
    F.Cu     75 · 60 · 50 · 8 · 4 mm²  cuivre en face = oui

Deux îlots reçoivent un via qui traverse vers **du vide** : il ne relie rien.
Les autres sont bien reliés.

⚠️ **CE PIÈGE A DÉJÀ ÉTÉ TENDU, ET LA MESURE L'A RÉFUTÉ.** Le 2026-09-01,
j'avais ajouté la condition « ne percer que si la face opposée porte du
cuivre ». Empiriquement MAUVAIS :

    couture d'origine (sans la condition)   1 connexion manquante
    avec la condition                       4 connexions manquantes

Parce qu'elle **refusait** des sites sans en chercher d'autres : moins de vias
posés, donc moins d'îlots reliés. Le test de l'époque a été inversé pour
interdire son retour, et il reste en vigueur.

LA BONNE FORME N'EST PAS UN FILTRE, C'EST UN ORDRE. On essaie d'abord les
points qui relieront vraiment ; si aucun ne convient, on se rabat sur les
autres — exactement le comportement d'avant. La couture ne peut donc que
s'améliorer : à pire égal, elle pose les mêmes vias qu'aujourd'hui.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as RUN  # noqa: E402


class TestOrdreDesCandidats:
    def test_les_points_qui_RELIENT_passent_devant(self):
        # (x, y) -> le point relie-t-il ?
        relient = {(1, 1): False, (2, 2): True, (3, 3): False, (4, 4): True}
        ordre = RUN._candidats_par_preference(
            list(relient), lambda p: relient[p])
        assert ordre[:2] == [(2, 2), (4, 4)]

    def test_AUCUN_candidat_n_est_perdu(self):
        # ⚠️ Le point qui a fait échouer la version de 2026-09-01 : refuser un
        # site, c'est poser moins de vias, donc relier moins d'îlots.
        pts = [(1, 1), (2, 2), (3, 3)]
        ordre = RUN._candidats_par_preference(pts, lambda p: p == (2, 2))
        assert sorted(ordre) == sorted(pts)

    def test_sans_aucun_point_qui_relie_l_ordre_est_CONSERVE(self):
        # Comportement strictement identique à celui d'avant.
        pts = [(1, 1), (2, 2), (3, 3)]
        assert RUN._candidats_par_preference(pts, lambda p: False) == pts

    def test_si_TOUS_relient_l_ordre_est_conserve(self):
        pts = [(1, 1), (2, 2), (3, 3)]
        assert RUN._candidats_par_preference(pts, lambda p: True) == pts

    def test_l_ordre_relatif_est_STABLE_dans_chaque_groupe(self):
        # La direction du GA porte une information de placement : on ne la
        # brouille pas, on ne fait que remonter un groupe devant l'autre.
        pts = [(1, 1), (2, 2), (3, 3), (4, 4)]
        ordre = RUN._candidats_par_preference(
            pts, lambda p: p in {(3, 3), (1, 1)})
        assert ordre == [(1, 1), (3, 3), (2, 2), (4, 4)]

    def test_une_liste_vide_ne_casse_rien(self):
        assert RUN._candidats_par_preference([], lambda p: True) == []

    def test_un_predicat_qui_LEVE_ne_fait_pas_echouer_la_couture(self):
        # ⚠️ Un test de cuivre en panne ne doit pas éteindre la couture : on
        # retombe sur l'ordre d'origine, jamais sur zéro via.
        def _explose(_p):
            raise RuntimeError("polygone illisible")
        pts = [(1, 1), (2, 2)]
        assert RUN._candidats_par_preference(pts, _explose) == pts


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8")

    def _stitch(self) -> str:
        i = self.SOURCE.index("def _stitch_zones(")
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        return self.SOURCE[i:j if j != -1 else len(self.SOURCE)]

    def test_la_couture_utilise_REELLEMENT_la_preference(self):
        assert "_candidats_par_preference(" in self._stitch()

    def test_la_couture_ne_REFUSE_toujours_pas_sur_l_absence_de_cuivre(self):
        # ⚠️ Garde héritée du 2026-09-01, conservée telle quelle : la condition
        # réfutée ne doit pas revenir sous une autre forme. On ORDONNE, on ne
        # filtre pas.
        # ⚠️ La garde vise l'INTENTION : la préférence ne doit servir qu'à
        # ORDONNER. Une première version interdisait tout `continue` dans une
        # fenêtre — elle attrapait les `continue` légitimes du corps de boucle
        # et ne mesurait donc rien de ce qu'elle visait.
        corps = self._stitch()
        code = [l.strip() for l in corps.split(chr(10))
                if not l.strip().startswith("#")]
        # `_relie` ne doit apparaître QUE comme argument de la préférence,
        # jamais dans une condition qui écarte un candidat.
        fautifs = [l for l in code
                   if "_relie(" in l and "_candidats_par_preference" not in l
                   and not l.startswith("def _relie")]
        assert not fautifs, (
            "la préférence sert à écarter, pas seulement à ordonner : %s"
            % fautifs)

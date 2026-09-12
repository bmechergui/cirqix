"""Un réglage doit atteindre le SERVICE, et être relu à chaque appel.

⚠️ MESURE DU 2026-09-09. Une campagne A/B entière n'a rien mesuré.

`run_pipeline.py` est un simple **client HTTP** : le placement s'exécute dans le
service FastAPI, un processus **séparé**, démarré au lancement du conteneur.
`CIRQIX_GRAINE_HIERARCHIQUE=1` posé dans le shell du pipeline ne l'atteint
jamais. Les deux bras étaient donc identiques :

    temoin1  routed=98
    hier1    routed=98      ← même chose, et ça ressemblait à « aucun effet »

C'est la famille de défauts que ce dépôt traque depuis une semaine, appliquée
cette fois à l'instrument de mesure lui-même : **une règle jamais exécutée est
indistinguable d'une règle sans effet.** J'avais écrit la garde qui devait le
dire — et je l'ai cherchée dans le mauvais journal (celui du client, quand la
trace du service va dans `docker logs`).

Le remède suit le motif déjà en place pour le verrou de routage : un FICHIER,
seule ressource que des processus séparés partagent.

⚠️ ET IL DOIT ÊTRE RELU À CHAQUE APPEL. Un réglage figé à l'import serait
constant pour la vie du service : le second bras hériterait du premier, et la
campagne comparerait deux fois la même chose. Reproduire ici le défaut qu'on
corrige serait particulièrement coûteux, parce qu'il ne se voit pas.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))


@pytest.fixture()
def reglages(tmp_path, monkeypatch):
    """Un fichier de réglages isolé, relu par le module à chaque appel."""
    fichier = tmp_path / "reglages.json"
    monkeypatch.setenv("CIRQIX_REGLAGES", str(fichier))
    import tools.reglages_banc as R
    importlib.reload(R)
    return fichier, R


class TestLeFichierFaitFoi:
    def test_absent_le_defaut_s_applique(self, reglages):
        _, R = reglages
        assert R.reglage("graine_hierarchique", False) is False
        assert R.reglage("rayon_paire_mm", 5.0) == 5.0

    def test_present_il_l_emporte(self, reglages):
        fichier, R = reglages
        fichier.write_text(json.dumps({"graine_hierarchique": True,
                                       "rayon_paire_mm": 0.0}), encoding="utf-8")
        assert R.reglage("graine_hierarchique", False) is True
        assert R.reglage("rayon_paire_mm", 5.0) == 0.0

    def test_il_l_emporte_sur_l_ENVIRONNEMENT(self, reglages, monkeypatch):
        """Le fichier passe en premier : c'est le seul canal qui atteint un
        service DÉJÀ DÉMARRÉ."""
        fichier, R = reglages
        monkeypatch.setenv("CIRQIX_RAYON_PAIRE_MM", "9.0")
        fichier.write_text(json.dumps({"rayon_paire_mm": 1.0}), encoding="utf-8")
        assert R.reglage("rayon_paire_mm", 5.0) == 1.0


class TestReluAChaqueAppel:
    def test_un_changement_pendant_la_vie_du_processus_est_VU(self, reglages):
        """⚠️ LE CŒUR DU DÉFAUT. Sans cela, le second bras d'un A/B hérite du
        premier et la campagne compare deux fois la même chose."""
        fichier, R = reglages
        assert R.reglage("graine_hierarchique", False) is False

        fichier.write_text(json.dumps({"graine_hierarchique": True}),
                           encoding="utf-8")
        assert R.reglage("graine_hierarchique", False) is True, (
            "le reglage a ete fige — tout A/B serait inerte")

        fichier.unlink()
        assert R.reglage("graine_hierarchique", False) is False, (
            "le retrait du fichier n'a pas ete vu")


class TestUnReglageIGNORE_SE_DIT:
    def test_un_fichier_illisible_est_signale(self, reglages, caplog):
        """Un réglage silencieusement ignoré ferait tourner le bras avec les
        valeurs par défaut — donc mesurer le témoin deux fois en croyant
        comparer."""
        fichier, R = reglages
        fichier.write_text("{ceci n'est pas du json", encoding="utf-8")
        with caplog.at_level("ERROR"):
            assert R.reglage("graine_hierarchique", False) is False
        assert any("ILLISIBLE" in m for m in caplog.messages), (
            "un fichier illisible est passe sans un mot")

    def test_un_contenu_qui_n_est_pas_un_objet_est_signale(self, reglages, caplog):
        fichier, R = reglages
        fichier.write_text("[1, 2, 3]", encoding="utf-8")
        with caplog.at_level("ERROR"):
            assert R.reglage("rayon_paire_mm", 5.0) == 5.0
        assert any("objet" in m for m in caplog.messages)


class TestCablage:
    """⚠️ Une règle correcte jamais appelée est indistinguable d'une absente —
    et c'est précisément ce qui vient d'arriver."""

    def test_le_placement_relit_les_reglages_au_lieu_de_les_figer(self):
        import inspect
        from tools import placement as P
        src = inspect.getsource(P)
        # On ne lit que le CODE : un commentaire citant l'ancienne forme ne
        # doit pas faire passer la garde.
        code = "\n".join(l.split("#")[0] for l in src.splitlines())
        assert "def _grille_mm(" in code
        assert "def _graine_hierarchique(" in code
        assert 'os.environ.get("CIRQIX_GRILLE_MM"' not in code, (
            "la grille est encore lue une seule fois, a l import")

    def test_les_appelants_utilisent_les_FONCTIONS(self):
        import inspect
        from tools import placement as P
        code = "\n".join(l.split("#")[0]
                         for l in inspect.getsource(P._auto_place_une_fois).splitlines())
        assert "_grille_mm()" in code, "la grille figee est encore transmise"
        assert "_graine_hierarchique()" in code, "la graine est encore figee"

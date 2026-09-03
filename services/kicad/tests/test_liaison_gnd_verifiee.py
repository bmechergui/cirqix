"""LIER NE SUFFIT PAS — il faut VERIFIER que la liaison a pris.

⚠️ REGLE POSEE PAR L UTILISATEUR le 2026-09-01 :

    « avant de router il faut verifier tous les GND colles, et si pas colles
      on doit les lier ET verifier que la liaison est deja la — c est notre
      objectif de pipeline »

L etape ③ posait une piste et un via, puis lisait le compte rendu du runner :

    {"escaped": 1, "renonces": 0}

`escaped` dit qu un cuivre a ete POSE. Il ne dit RIEN de ce qui compte : que la
broche touche desormais le cuivre de masse. Un via peut etre pose et ne relier
personne — c est la definition meme d un via borgne, et le projet a deja mesure
qu il en existe.

⚠️ Le voisin `_stitch_islands` porte cette verification depuis toujours
(`_est_relie` reconstruit la connectivite et refuse le via qui ne joint rien) ;
`escape_pads`, non. Deux mecanismes qui posent du cuivre, un seul qui verifie.

On mesure donc l isolement AVANT et APRES la liaison, avec le meme instrument
(`_pads_isolees_du_plan` sur un rapport `kicad-cli`), et on le DIT.

⚠️ Un board place dont le plan est coule ne porte AUCUNE broche GND isolee —
mesure du 2026-08-31. La verification est donc normalement muette : elle sert a
attraper le jour ou elle ne le sera plus, et a prouver que la liaison posee
tient. Une garde qui ne se declenche jamais reste utile ; une garde absente ne
prouve rien.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestVerdict:
    def test_aucune_isolee_apres_est_un_SUCCES(self):
        assert R._liaison_a_pris(avant=[("U1", "8")], apres=[]) is True

    def test_une_isolee_qui_demeure_est_un_ECHEC_PARTIEL(self):
        assert R._liaison_a_pris(avant=[("U1", "8"), ("U1", "23")],
                                 apres=[("U1", "23")]) is False

    def test_aucune_isolee_au_depart_reste_un_succes(self):
        # Cas normal mesure : plan coule, rien d isole. Ne pas crier au loup.
        assert R._liaison_a_pris(avant=[], apres=[]) is True

    def test_une_isolee_APPARUE_est_un_echec(self):
        # Poser du cuivre ne doit jamais DEconnecter une broche.
        assert R._liaison_a_pris(avant=[], apres=[("U2", "5")]) is False


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_l_etape_3_mesure_l_isolement_avant_et_apres(self):
        i = self.SOURCE.index("def _relier_gnd_avant_routage(")
        j = self.SOURCE.index("def ", i + 40)
        # La fenetre s arrete a la fonction suivante : une taille fixe rate la
        # fin d une fonction longue — piege deja paye quatre fois ce mois-ci.
        corps = self.SOURCE[i:self.SOURCE.index(chr(10) + "def ", j)]
        assert corps.count("_pads_isolees_du_plan(") >= 2, (
            "l etape ③ pose du cuivre sans verifier qu il relie quoi que ce soit")

    def test_le_verdict_est_journalise(self):
        i = self.SOURCE.index("def _relier_gnd_avant_routage(")
        corps = self.SOURCE[i:i + 8000]
        assert "_liaison_a_pris(" in corps
        assert "toujours isolee" in corps

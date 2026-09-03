"""Un via dans une pastille CMS pose du cuivre NEUF sur les autres couches.

⚠️ Mesure du 2026-09-02, `stm32-100`, board final. Le fanout relie une des deux
dernières pastilles de masse — et ajoute une erreur :

    Clearance violation ( clearance 0.2000 mm; actual 0.0481 mm)
       - Track [GPIO46] on B.Cu, length 18.2149 mm
       - Via   [GND]    on F.Cu - B.Cu

La dispense de dégagement du via en pastille repose sur un raisonnement juste,
mais incomplet, inscrit dans le code :

    « Un via qui TIENT dans la pastille herite de SON isolement : exiger un
      degagement autour de lui reviendrait a demander deux fois la meme chose. »

C'est vrai **sur la couche de la pastille**. Une pastille CMS n'existe que sur
F.Cu ; le via, lui, traverse jusqu'à B.Cu, où il pose du cuivre que **personne
n'a vérifié**. La piste GPIO46 est précisément sur B.Cu.

C'est la signature de ce dépôt : une garde qui raisonne sur une couche pour un
objet qui en traverse plusieurs — comme le rapport DRC lu chez un seul lecteur
(2026-08-27), ou le compteur de nets aveugle à la forme de KiCad 10.

⚠️ ON NE SUPPRIME PAS LA DISPENSE : elle est nécessaire, et son retrait
refusait les trois pastilles orphelines du banc qui surplombaient le plan de
B.Cu. On la **borne à la couche de la pastille**, et on vérifie les autres.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as RUN  # noqa: E402


class TestCouchesANeRienDevoir:
    """Quelles couches le via traverse-t-il SANS que la pastille l'y couvre."""

    def test_une_pastille_CMS_ne_couvre_pas_la_face_opposee(self):
        # Le cas mesuré : pastille sur F.Cu (0), via jusqu'a B.Cu.
        # ⚠️ B.Cu vaut 2 en KiCad 10, pas 31 — le board du banc l'a dit
        # lui-meme (`couches nues=[2]`). Une garde qui ecrit un numero
        # faux enseigne un fait faux, meme quand elle passe.
        assert RUN._couches_traversees_hors_pastille({0}, {0, 2}) == {2}

    def test_une_pastille_TRAVERSANTE_ne_doit_rien(self):
        # Elle occupe deja toutes les couches : la dispense vaut partout.
        assert RUN._couches_traversees_hors_pastille({0, 2}, {0, 2}) == set()

    def test_un_empilage_a_QUATRE_couches_expose_les_internes(self):
        assert RUN._couches_traversees_hors_pastille(
            {0}, {0, 1, 2, 3}) == {1, 2, 3}

    def test_une_pastille_sur_la_face_arriere_expose_la_face_avant(self):
        assert RUN._couches_traversees_hors_pastille({2}, {0, 2}) == {0}

    def test_une_pastille_sans_couche_lisible_n_obtient_AUCUNE_dispense(self):
        # ⚠️ Fail-closed : sans mesure, on verifie tout plutot que rien.
        assert RUN._couches_traversees_hors_pastille(set(), {0, 2}) == {0, 2}


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8")

    def _corps_escape(self) -> str:
        i = self.SOURCE.index("def _escape_pads(")
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        return self.SOURCE[i:j]

    def test_le_recours_CONSULTE_les_couches_non_couvertes(self):
        # Une regle correcte jamais appelee est indistinguable d une absente.
        assert "_couches_traversees_hors_pastille(" in self._corps_escape()

    def test_la_dispense_SUBSISTE(self):
        # On la borne, on ne la retire pas : elle relie les pastilles du banc.
        assert "_via_in_pad_dispense_de_clearance(" in self._corps_escape()

    def test_les_obstacles_savent_se_FILTRER_par_couche(self):
        i = self.SOURCE.index("def _obstacles_d_un_autre_net(")
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        assert "couches" in self.SOURCE[i:j], (
            "la liste d obstacles ignore encore les couches")

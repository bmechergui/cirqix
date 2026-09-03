"""Un placement qui livre un board en conflit doit le DIRE.

Mesure du 2026-08-26, ESP32 du banc. Le board rendu portait :

    courtyards_overlap    9
    shorting_items        8
    pth_inside_courtyard  2

...et le placement ne signalait RIEN. La reponse ne porte que
`kicad_pcb_b64`, `placed_count` et `positions` — aucun mot sur les conflits
qu il n a pas su resoudre.

⚠️ Ce n est pas un probleme de taille de carte : la carte fait 93 x 70 mm et le
plus gros courtyard 41 x 48. Il tient largement. Le placeur pose des composants
par-dessus, et le livre quand meme.

L appelant ne peut donc pas savoir qu il route un board deja casse — il decouvre
les degats au DRC, trois etapes plus loin, sans pouvoir les imputer.

Le placement expose desormais `conflits_restants`. Il ne LEVE pas : un board
imparfait vaut mieux qu aucun board, et l orchestrateur sait deja re-tirer. Mais
il ne ment plus par omission.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import placement as placement_router  # noqa: E402


class TestContrat:
    def test_la_reponse_porte_le_compte_de_conflits(self):
        champs = placement_router.AutoPlacementResponse.model_fields
        assert "conflits_restants" in champs

    def test_le_compte_a_une_valeur_par_defaut(self):
        # Un service plus ancien, ou un chemin qui ne sait pas compter, ne doit
        # pas faire echouer la validation du modele.
        r = placement_router.AutoPlacementResponse(
            kicad_pcb_b64="", placed_count=0, positions=[])
        assert r.conflits_restants == 0


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_auto_place_compte_les_conflits_restants(self):
        corps = self.SOURCE[self.SOURCE.index("def auto_place("):]
        assert "conflits_restants" in corps

    def test_un_board_en_conflit_est_journalise_en_ERREUR(self):
        # Un avertissement se noie dans le bruit ; c est une erreur de
        # fabricabilite qui attend trois etapes plus loin.
        #
        # ⚠️ On cherche dans TOUTE l enveloppe, pas dans une fenetre autour de
        # la premiere occurrence : le re-tirage borne (2026-08-27) a deplace le
        # journal sans rien changer a l intention.
        corps = self.SOURCE[self.SOURCE.index("def auto_place("):]
        corps = corps[: corps.index(chr(10) + "def _auto_place_une_fois")]
        assert "conflits_restants" in corps
        assert "logger.error" in corps

"""Le via d echappement doit regarder ce qu il traverse.

Mesure du 2026-08-23, board STM32 : pose a l aveugle — direction opposee au
centre du boitier, sans verifier le trajet — le fanout ajoutait 6 ERREURS dont
DEUX `shorting_items` entre GND et +3.3V. La garde de
`_fanout_pads_isolees` rendait alors le board d origine, donc les broches
restaient orphelines : la reparation ne reparait rien.

La decision geometrique est ici PURE — pas de pcbnew — pour etre testable :
choisir une direction de sortie, c est de la geometrie, pas de la manipulation
de board.

Principe : on essaie d abord la direction naturelle (a l oppose du centre, le
canal que le halo d escape du placement a reserve), puis on tourne autour du
pad. On garde la PREMIERE direction dont le trajet entier reste a distance des
obstacles d un autre net. Si aucune ne convient, on ne pose RIEN — une broche
orpheline se voit au DRC et bloque la commande ; un court-circuit peut partir
en fabrication.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as runner  # noqa: E402


MM = 1_000_000


class TestDistanceAuxObstacles:
    def test_un_point_dans_la_boite_est_a_distance_nulle(self):
        boite = (0, 0, 10 * MM, 10 * MM)
        assert runner._dist_point_boite(5 * MM, 5 * MM, boite) == 0

    def test_un_point_a_cote_mesure_l_ecart_reel(self):
        boite = (0, 0, 10 * MM, 10 * MM)
        assert runner._dist_point_boite(13 * MM, 5 * MM, boite) == 3 * MM

    def test_un_point_en_diagonale_mesure_l_hypotenuse(self):
        boite = (0, 0, 10 * MM, 10 * MM)
        d = runner._dist_point_boite(13 * MM, 14 * MM, boite)
        assert abs(d - 5 * MM) < 1000  # 3-4-5


class TestTrajet:
    OBSTACLE = (5 * MM, -1 * MM, 6 * MM, 1 * MM)  # barre verticale en x=5..6

    def test_un_trajet_degage_passe(self):
        assert runner._trajet_libre(0, 0, 0, 4 * MM, [self.OBSTACLE], marge=MM // 2)

    def test_un_trajet_qui_traverse_est_refuse(self):
        # C est exactement le cas mesure : la sortie coupe une piste d un autre
        # net et cree un court-circuit.
        assert not runner._trajet_libre(0, 0, 10 * MM, 0, [self.OBSTACLE], marge=MM // 2)

    def test_la_marge_est_respectee_meme_sans_contact(self):
        # Frôler n est pas traverser, mais un DRC de clearance echoue quand meme :
        # la mesure fautive etait 0,0181 mm pour 0,2 exige.
        assert not runner._trajet_libre(0, 0, 4 * MM, 0, [self.OBSTACLE], marge=2 * MM)


class TestChoixDeLaSortie:
    def test_la_direction_naturelle_est_preferee_quand_elle_est_libre(self):
        # Ne pas tourner sans raison : le canal reserve par le placement est le
        # meilleur choix quand rien ne l occupe.
        sortie = runner._choisir_sortie(0, 0, 1.0, 0.0, 2 * MM, [], marge=MM // 2)
        assert sortie is not None
        x, y = sortie
        assert x > 0 and abs(y) < MM // 10

    def test_une_direction_bloquee_fait_tourner(self):
        obstacle = (1 * MM, -3 * MM, 3 * MM, 3 * MM)
        sortie = runner._choisir_sortie(0, 0, 1.0, 0.0, 2 * MM, [obstacle], marge=MM // 2)
        assert sortie is not None
        x, _ = sortie
        assert x < 1 * MM, "la sortie devrait avoir quitte la direction bloquee"

    def test_un_pad_totalement_encercle_ne_recoit_rien(self):
        # Le cas qui compte : ne RIEN poser vaut mieux qu un court-circuit.
        mur = [
            (-9 * MM, -9 * MM, 9 * MM, -1 * MM),
            (-9 * MM, 1 * MM, 9 * MM, 9 * MM),
            (-9 * MM, -9 * MM, -1 * MM, 9 * MM),
            (1 * MM, -9 * MM, 9 * MM, 9 * MM),
        ]
        assert runner._choisir_sortie(0, 0, 1.0, 0.0, 2 * MM, mur, marge=MM // 2) is None


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8"
    )

    def test_la_pose_consulte_le_choix(self):
        corps = self.SOURCE[self.SOURCE.index("def _escape_pads(") :]
        corps = corps[: corps.index(chr(10) + "def ")]
        assert "_choisir_sortie(" in corps, "la pose ignore encore son environnement"

    def test_les_pads_non_sortis_sont_comptes(self):
        # Un fanout qui renonce silencieusement laisserait croire a une
        # reparation complete.
        corps = self.SOURCE[self.SOURCE.index("def _escape_pads(") :]
        corps = corps[: corps.index(chr(10) + "def ")]
        assert "renonces" in corps

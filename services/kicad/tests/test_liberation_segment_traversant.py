"""Une piste qui TRAVERSE la zone de libération doit être libérée, même si ses
deux extrémités sont loin.

⚠️ Mesuré sur `nucleo-f401` le 2026-09-24, board réel sorti d'une campagne de
production. La connexion manquante est `U1.37 [MORPHO_R_6]`, et le couloir qui
y mène est barré par :

    MORPHO_R_5  B.Cu  (169.004,110.826) -> (159.287,101.109)
                passe à 0,533 mm du point non relié   ->  PROTÉGÉ

Un segment qui passe à un demi-millimètre de la pastille non reliée restait
protégé, parce que la règle testait ses DEUX EXTRÉMITÉS — et celui-ci est une
diagonale de 13,7 mm dont les bouts sont ailleurs.

Ce n'est pas un seuil mal choisi : c'est la règle qui ne fait pas ce qu'elle
dit. « Libérer ce qui est à moins de 1,2 mm » doit inclure une piste qui passe
à 0,5 mm. Le rayon ne change PAS — la mesure, oui.

⚠️ Conséquence à retenir : la réfutation du rayon à 2,5 mm (« 159 des 372
segments libérés, 92 % -> 79 % », 2026-09-11) a été mesurée AVEC ce défaut.
Elle sous-estimait donc ce qui aurait dû être libéré, et son chiffre mériterait
d'être refait avant de rouvrir la question du rayon.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


def _board_avec_diagonale() -> bytes:
    """Un board où une longue diagonale frôle le point non relié.

    Géométrie reprise du vrai `nucleo-f401` : le point non relié est en
    (167.675, 110.25) et la diagonale va de (169.004, 110.826) à
    (159.287, 101.109), passant à 0,533 mm de ce point.

    ⚠️ Il FAUT des pistes lointaines en nombre. La libération est plafonnée à
    `_PART_LIBERATION_MAX` (25 %) : sur un board de trois éléments, libérer la
    seule diagonale fait 33 % et déclenche le repli « on protège TOUT ». Le
    filet est juste — c'est la fixture qui mentirait, en faisant passer un
    correctif correct pour un échec.
    """
    loin = "".join(
        '  (segment (start %d 200) (end %d 210) (width 0.25) (layer "F.Cu") (uuid "l%d") (net 4))\n'
        % (200 + 3 * i, 210 + 3 * i, i) for i in range(20))
    return ("""(kicad_pcb (version 20240108) (generator "pcbnew")
  (net 0 "")
  (net 3 "MORPHO_R_5")
  (net 4 "MORPHO_R_7")
  (net 5 "GND")
  (segment (start 169.004 110.826) (end 159.287 101.109) (width 0.25) (layer "B.Cu") (uuid "diag") (net 3))
  (segment (start 169.004 110.826) (end 159.287 101.109) (width 0.25) (layer "B.Cu") (uuid "gnd") (net 5))
""" + loin + ")").encode()


# Le point non relié mesuré sur le vrai board.
_PASTILLE = (167.675, 110.25)


class TestUnSegmentQuiTRAVERSELaZoneEstLibere:
    def test_la_diagonale_qui_frole_la_pastille_est_liberee(self):
        """Le cœur du défaut : 0,533 mm de la pastille, bouts à 1,9 et 13 mm."""
        bloc = R._bloc_wiring_pistes(_board_avec_diagonale(), liberer=[_PASTILLE])
        assert "(net MORPHO_R_5)" not in bloc, (
            "la diagonale passe a 0,533 mm de la pastille non reliee : elle doit "
            "etre LIBEREE, pas protegee — c est tout l objet de la zone"
        )

    def test_une_piste_reellement_loin_reste_protegee(self):
        """La libération ne doit pas devenir un blanc-seing."""
        bloc = R._bloc_wiring_pistes(_board_avec_diagonale(), liberer=[_PASTILLE])
        assert "(net MORPHO_R_7)" in bloc, (
            "un segment a 40 mm de la zone n a aucune raison d etre libere"
        )

    def test_un_net_confie_au_plan_n_est_JAMAIS_libere(self):
        """⚠️ Règle du 2026-09-14 : GND est absent du DSN, donc un tronçon GND
        libéré n'est pas rendu au routeur — il est PERDU."""
        bloc = R._bloc_wiring_pistes(_board_avec_diagonale(), liberer=[_PASTILLE])
        assert "(net GND)" in bloc, (
            "meme en plein dans la zone, un net confie au plan reste protege : "
            "personne ne le reposerait"
        )


class TestLaMesureEstUneDistanceAuSEGMENT:
    def test_un_point_du_milieu_compte(self):
        """La distance se mesure au segment entier, pas à ses deux bouts."""
        a, b = (0.0, 0.0), (10.0, 0.0)
        # Un point au-dessus du MILIEU : les deux extremites sont a 5 mm,
        # le segment lui-meme a 0,5 mm.
        assert R._segment_pres_d_une_zone(a, b, [(5.0, 0.5)], 1.2) is True
        assert R._segment_pres_d_une_zone(a, b, [(5.0, 3.0)], 1.2) is False

    def test_une_extremite_dans_la_zone_compte_toujours(self):
        """Le comportement historique ne doit pas régresser."""
        a, b = (0.0, 0.0), (10.0, 0.0)
        assert R._segment_pres_d_une_zone(a, b, [(0.3, 0.3)], 1.2) is True

    def test_un_segment_degenere_ne_leve_pas(self):
        """⚠️ start == end existe dans de vrais boards : une division par la
        longueur y lèverait `ZeroDivisionError` au milieu d'un routage."""
        assert R._segment_pres_d_une_zone((5.0, 5.0), (5.0, 5.0), [(5.0, 5.5)], 1.2) is True
        assert R._segment_pres_d_une_zone((5.0, 5.0), (5.0, 5.0), [(9.0, 9.0)], 1.2) is False

    def test_sans_zone_rien_n_est_pres(self):
        assert R._segment_pres_d_une_zone((0.0, 0.0), (1.0, 1.0), [], 1.2) is False


class TestLeCABLAGE:
    """⚠️ Une règle correcte jamais appelée est indistinguable d'une règle
    absente. On vérifie que `_bloc_wiring_pistes` utilise bien la mesure au
    segment, et non plus le test des deux extrémités."""

    def test_le_site_d_appel_mesure_au_segment(self):
        import inspect

        src = inspect.getsource(R._bloc_wiring_pistes)
        assert "_segment_pres_d_une_zone" in src, (
            "le site d appel doit mesurer la distance au SEGMENT ; sans cela "
            "une piste qui traverse la zone reste protegee en silence"
        )

"""UNE regle pour toutes les ruptures de masse, au lieu de cinq mecanismes.

⚠️ EXIGENCE DE L UTILISATEUR le 2026-09-01 : « on veut une solution generale,
pas du bricolage — une solution qui marche sur toutes les cartes, meme
principe. »

La chaine empilait cinq mecanismes, un par cas : lier avant le routage,
reposer les vias reserves, fanouter les pastilles isolees, coudre les ilots
d une face, replier sur un routage incluant GND. Chaque cas nouveau echappait
donc a tous.

Or les quatre ruptures mesurees le 2026-09-01 sur les boards livres, que le
rapport `kicad-cli` nomme sans ambiguite, posent TOUTES la meme question :

    Pad 8 [GND] of U1   <->  Zone [GND] on F.Cu    (broche piegee, stm32-60)
    Zone [GND] on F.Cu  <->  Zone [GND] on F.Cu    (deux ilots, stm32-30/100)
    Zone [GND] on F.Cu  <->  Zone [GND] on B.Cu    (deux faces, nucleo-f401)

« Deux morceaux de cuivre de masse ne se touchent pas. »

LA REGLE GENERALE, en une phrase :

    Tout morceau de cuivre de masse doit posseder au moins un via vers le
    plan de la face opposee.

Elle couvre les trois cas sans les distinguer : deux ilots d une meme face se
rejoignent PAR-DESSOUS, deux faces se rejoignent directement, et une pastille
piegee n a plus besoin de sortie laterale.

⚠️ LA CONDITION QUI FAIT TOUT. Un via pose dans un ilot ne relie RIEN si la
face opposee n a pas de cuivre a cet endroit. C est la difference entre
« poser un via » et « relier », et c est ce que la couture ne verifiait pas.

⚠️ La regle porte sa propre verification : apres elle, le DRC doit annoncer
zero rupture de masse. Sinon elle a echoue, et on le sait tout de suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as RUN  # noqa: E402


class TestPointUtile:
    """Un via n est utile qu ou les DEUX faces portent du cuivre du meme net."""

    def test_les_deux_faces_ont_du_cuivre_le_point_sert(self):
        assert RUN._via_relie_vraiment(sur_cette_face=True,
                                       sur_la_face_opposee=True) is True

    def test_la_face_opposee_est_vide_le_via_ne_relie_rien(self):
        # ⚠️ Le defaut exact de la couture : elle posait le via sans regarder
        # en face. Un via vers du vide est un via borgne.
        assert RUN._via_relie_vraiment(sur_cette_face=True,
                                       sur_la_face_opposee=False) is False

    def test_hors_du_cuivre_de_depart_rien_a_relier(self):
        assert RUN._via_relie_vraiment(sur_cette_face=False,
                                       sur_la_face_opposee=True) is False


class TestCouverture:
    """La regle doit viser TOUS les morceaux, pas seulement les ilots."""

    def test_un_ilot_unique_sur_deux_faces_est_vise(self):
        assert RUN._faut_coudre(ilots_sur_la_couche=1, couches_du_net=2) is True

    def test_plusieurs_ilots_sont_vises(self):
        assert RUN._faut_coudre(ilots_sur_la_couche=3, couches_du_net=1) is True

    def test_une_carte_a_une_seule_face_n_a_rien_a_coudre(self):
        assert RUN._faut_coudre(ilots_sur_la_couche=1, couches_du_net=1) is False


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8")

    def test_la_couture_verifie_la_face_opposee(self):
        # ⚠️ Une regle correcte que personne n applique est indistinguable
        # d une regle absente — la faute la plus repetee de ce projet.
        i = self.SOURCE.index("def _stitch_zones(")
        corps = self.SOURCE[i:i + 6000]
        assert "_via_relie_vraiment(" in corps, (
            "la couture pose encore des vias sans regarder la face opposee")

    def test_le_cuivre_de_la_face_opposee_est_calcule(self):
        i = self.SOURCE.index("def _stitch_zones(")
        corps = self.SOURCE[i:i + 6000]
        assert "_cuivre_du_net_sur" in corps


class TestUneZoneParFace:
    r"""⚠️ Le cuivre d en face vit dans une AUTRE zone, pas dans la meme.

    Notre generateur ecrit UNE ZONE PAR FACE (`routers/routing.py`, boucle sur
    les couches) : deux objets distincts, chacun a une seule couche. Chercher
    « les autres couches de la zone courante » ne trouve donc JAMAIS rien.

    Mesure du 2026-09-01, `nucleo-f401`, board livre :

        F.Cu : 7 ilots — 11023, 2785, 1956, 136, 115, 79, 13 mm2
        B.Cu : 2 ilots — 11023, 6 mm2

    Le grand plan de B.Cu couvre la carte entiere : chaque ilot de F.Cu a du
    cuivre en face, un via par ilot suffisait. UN SEUL a ete pose, et la carte
    est sortie a 6 connexions manquantes au lieu d une — toutes GND, aucune de
    signal. J avais remplace un via aveugle par un via jamais pose.

    La recherche parcourt donc TOUT le board, filtre sur le NET, et exclut la
    seule couche courante.
    """

    def test_la_recherche_prend_le_board_en_premier_argument(self):
        import inspect
        params = list(inspect.signature(RUN._cuivre_du_net_sur).parameters)
        assert params[0] == "board", (
            "la recherche interroge encore la zone courante, qui n a qu une "
            "couche : elle ne trouvera jamais le cuivre d en face")

    def test_le_cablage_passe_bien_le_board(self):
        i = RUN.__file__ and 0
        src = TestCablage.SOURCE
        j = src.index("def _stitch_zones(")
        assert "_cuivre_du_net_sur(board," in src[j:j + 6000]

"""Une piste diagonale n'occupe pas son rectangle englobant.

⚠️ Mesure du 2026-09-02, `stm32-30`, après la correction du pas
d'échantillonnage. Les trois îlots non reliés reçoivent enfin des points
candidats — et **tous** sont rejetés :

    îlot 23,9 mm²   3 points dans le polygone   3 bloqués par obstacle
    îlot 12,4 mm²   2 points                    2 bloqués
    îlot 21,2 mm²   6 points                    6 bloqués

100 % des candidats refusés. La couture ne peut donc rien poser, et le DRC
signale les ruptures `plan ↔ plan` correspondantes.

CAUSE. `_obstacles_d_un_autre_net` rend des BOÎTES ENGLOBANTES :

    b = item.GetBoundingBox()
    boites.append((b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom()))

Pour une piste **diagonale**, ce rectangle couvre toute la diagonale — une
surface sans commune mesure avec le cuivre réel, large de 0,25 mm. Un petit
îlot coincé entre deux pistes tombe entièrement dans l'un de ces rectangles,
et chacun de ses points est déclaré obstrué alors que le cuivre passe à côté.

Le symptôme avait déjà été vu sans être compris : lors du diagnostic des
pastilles orphelines, l'obstacle le plus proche de `D3.2` et `C3.2` était
mesuré à **0,000 mm** — le centre de la pastille était « dans » la boîte d'une
piste éloignée.

⚠️ Ce n'est pas un réglage à assouplir : c'est une **mesure fausse**. Relâcher
le dégagement masquerait le défaut en acceptant de vrais conflits ailleurs. On
corrige l'instrument, pas le seuil.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as RUN  # noqa: E402

MM = 1_000_000


class TestDistanceAuSegment:
    def test_un_point_sur_le_segment_est_a_zero(self):
        assert RUN._dist_point_segment(5 * MM, 5 * MM,
                                       0, 0, 10 * MM, 10 * MM) == 0

    def test_le_cas_qui_bloquait_la_couture(self):
        # Une piste diagonale de (0,0) à (10,10). Le point (10,0) est dans sa
        # BOÎTE englobante — distance boîte = 0 — mais à 7,07 mm du cuivre.
        d = RUN._dist_point_segment(10 * MM, 0, 0, 0, 10 * MM, 10 * MM)
        assert abs(d - 7.071 * MM) < 0.01 * MM, d / MM

    def test_la_boite_englobante_dit_ZERO_au_meme_endroit(self):
        # ⚠️ La preuve du défaut, côte à côte avec sa correction.
        assert RUN._dist_point_boite(10 * MM, 0,
                                     (0, 0, 10 * MM, 10 * MM)) == 0

    def test_un_point_au_dela_d_une_extremite(self):
        # La projection tombe hors du segment : c'est l'extrémité qui compte.
        d = RUN._dist_point_segment(0, -3 * MM, 0, 0, 0, 10 * MM)
        assert abs(d - 3 * MM) < 1

    def test_un_segment_degenere_se_comporte_comme_un_point(self):
        d = RUN._dist_point_segment(3 * MM, 4 * MM, 0, 0, 0, 0)
        assert abs(d - 5 * MM) < 1

    def test_une_piste_horizontale_reste_correcte(self):
        # Le cas où boîte et segment coïncident : aucun changement.
        d = RUN._dist_point_segment(5 * MM, 2 * MM, 0, 0, 10 * MM, 0)
        assert abs(d - 2 * MM) < 1


class TestDistanceAUnObstacle:
    """L'aiguillage : un segment est mesuré comme segment, une boîte comme boîte."""

    def test_un_obstacle_SEGMENT_est_mesure_au_cuivre(self):
        obs = ("segment", 0, 0, 10 * MM, 10 * MM, 0.25 * MM)
        d = RUN._distance_a_obstacle(10 * MM, 0, obs)
        assert d > 6 * MM, d / MM

    def test_un_obstacle_BOITE_garde_son_calcul(self):
        obs = (0, 0, 10 * MM, 10 * MM)
        assert RUN._distance_a_obstacle(10 * MM, 0, obs) == 0

    def test_la_LARGEUR_de_la_piste_est_retranchee(self):
        # Le cuivre s'étend d'une demi-largeur de part et d'autre de l'axe.
        mince = ("segment", 0, 0, 0, 10 * MM, 0.0)
        epais = ("segment", 0, 0, 0, 10 * MM, 2.0 * MM)
        assert (RUN._distance_a_obstacle(5 * MM, 5 * MM, mince)
                - RUN._distance_a_obstacle(5 * MM, 5 * MM, epais)) == 1.0 * MM

    def test_une_distance_n_est_jamais_negative(self):
        # Un point DANS le cuivre est a distance nulle, pas negative.
        obs = ("segment", 0, 0, 10 * MM, 0, 2.0 * MM)
        assert RUN._distance_a_obstacle(5 * MM, 0, obs) == 0


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8")

    def test_les_obstacles_portent_la_forme_des_PISTES(self):
        i = self.SOURCE.index("def _obstacles_d_un_autre_net(")
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        corps = self.SOURCE[i:j]
        assert '"segment"' in corps, (
            "les pistes sont encore reduites a leur boite englobante")

    def test_la_couture_MESURE_par_l_aiguillage(self):
        i = self.SOURCE.index("def _stitch_zones(")
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        assert "_distance_a_obstacle(" in self.SOURCE[i:j]


class TestTousLesConsommateurs:
    """⚠️ LA GARDE QUI MANQUAIT, et qui a laissé passer une régression.

    En donnant aux obstacles une forme nouvelle — `("segment", x1, y1, x2, y2,
    largeur)`, six éléments — j'ai basculé trois sites d'appel sur
    `_distance_a_obstacle` et j'en ai oublié trois autres, qui appelaient
    encore `_dist_point_boite`. Ceux-là déballent quatre valeurs :

        gauche, haut, droite, bas = boite
        ValueError: too many values to unpack

    Le fanout plantait donc à CHAQUE broche, sur les quatre cartes. Aucun test
    ne l'a vu : ils n'exerçaient ces chemins qu'avec des boîtes.

    Une forme de donnée nouvelle doit être passée à TOUS ses consommateurs,
    et c'est exactement ce que ces tests vérifient.
    """

    OBSTACLES = [
        ("segment", 0, 0, 10 * MM, 10 * MM, 0.25 * MM),
        (20 * MM, 20 * MM, 22 * MM, 22 * MM),
    ]

    def test_la_sortie_reservee_accepte_les_deux_formes(self):
        # `_sortie_reservee_valide` parcourt la liste d'obstacles : elle doit
        # survivre à un segment, pas lever `too many values to unpack`.
        assert RUN._sortie_reservee_valide(
            50 * MM, 50 * MM, 51 * MM, 50 * MM, self.OBSTACLES,
            0.5 * MM) is True

    def test_choisir_sortie_survit_aux_segments(self):
        # Le chemin du fanout, celui qui plantait à chaque broche.
        sortie = RUN._choisir_sortie(
            50 * MM, 50 * MM, 1.0, 0.0, 1.2 * MM, self.OBSTACLES, 0.5 * MM)
        assert sortie is not None

    def test_aucun_consommateur_ne_deballe_une_boite_a_l_aveugle(self):
        # ⚠️ Garde structurelle : tout parcours d'une LISTE d'obstacles doit
        # passer par l'aiguillage, jamais par `_dist_point_boite` directement.
        src = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
            encoding="utf-8")
        code = [l for l in src.split(chr(10)) if not l.strip().startswith("#")]
        fautifs = [l.strip() for l in code
                   if "_dist_point_boite(" in l and "for o in obstacles" in l]
        assert not fautifs, (
            "un consommateur deballe encore l obstacle en boite : %s" % fautifs)

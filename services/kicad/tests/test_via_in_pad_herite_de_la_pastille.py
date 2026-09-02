"""Un via qui tient DANS la pastille hérite de son isolement — on ne le redemande pas.

⚠️ Mesure du 2026-09-02, boards finaux du banc. Les quatre cartes sont routées
à 96-99 %, et **aucune connexion de signal ne manque**. Ce qui bloque le 100 %
est entièrement la masse, en deux familles :

    carte          manquantes   plan↔plan   pastille↔plan
    nucleo-f401         2           1             1
    stm32-30            3           2             1
    stm32-60            3           2             1
    stm32-100           8           3             3

Les pastilles orphelines sont **posées pile au-dessus du cuivre de masse de la
face arrière** :

    C5.2  pastille 0,56 mm  CMS  ·  F.Cu sans cuivre  ·  B.Cu CUIVRE GND
    D3.2  pastille 0,88 mm  CMS  ·  F.Cu sans cuivre  ·  B.Cu CUIVRE GND
    C3.2  pastille 0,56 mm  CMS  ·  F.Cu sans cuivre  ·  B.Cu CUIVRE GND

Un via dans la pastille les relierait instantanément, et il tient
géométriquement — 0,56 mm de pastille donne 0,56 mm de via. Il était pourtant
refusé, par cette condition du site d'appel :

    any(_dist_point_boite(pos.x, pos.y, o) < d / 2 + clearance for o in obstacles)

    C5.2  obstacle le plus proche 0,395 mm  ·  exigé 0,480 mm  ->  REFUSÉ
    D3.2  obstacle le plus proche 0,000 mm  ·  exigé 0,500 mm  ->  REFUSÉ
    C3.2  obstacle le plus proche 0,000 mm  ·  exigé 0,480 mm  ->  REFUSÉ

⚠️ **LE CODE ÉCRIT L'ARGUMENT ET FAIT LE CONTRAIRE.** La docstring de
`_diametre_via_in_pad` dit, mot pour mot :

    « Le via ne doit JAMAIS dépasser la pastille. Tout l'argument tient là :
      un via aussi large qu'elle hérite de SA clearance, celle que la carte
      accepte déjà. »

Un via qui ne dépasse pas la pastille occupe du cuivre que la pastille occupe
déjà. Il ne peut donc violer aucun isolement que la pastille ne violerait pas
elle-même — et le board est accepté avec cette pastille. Redemander un
dégagement autour de lui, c'est exiger deux fois la même chose.

⚠️ Les `0,000 mm` mesurés révèlent au passage la fragilité de l'instrument :
les obstacles sont des BOÎTES ENGLOBANTES, et celle d'une piste diagonale
couvre un rectangle énorme. Elle « contient » le centre de la pastille alors
que le cuivre réel passe à distance. Cette sur-estimation est un second travers,
non corrigé ici.

⚠️ Ce qui reste vérifié : le TROU. Un perçage est physique, et deux trous au
même endroit restent impossibles quel que soit le raisonnement sur le cuivre.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as RUN  # noqa: E402

MM = 1_000_000


class TestLaRegle:
    def test_un_via_qui_TIENT_dans_la_pastille_n_exige_pas_de_degagement(self):
        # Le cas mesuré : C5.2, via 0,56 mm dans une pastille de 0,56 mm,
        # obstacle à 0,395 mm.
        assert RUN._via_in_pad_dispense_de_clearance(
            diametre_via=0.56 * MM, largeur_pad=0.56 * MM) is True

    def test_un_via_PLUS_LARGE_que_la_pastille_l_exige_toujours(self):
        # ⚠️ La condition inverse. Un via plus large déborde du cuivre de la
        # pastille : il redevient un obstacle pour les voisines, et son
        # dégagement doit être vérifié.
        assert RUN._via_in_pad_dispense_de_clearance(
            diametre_via=0.80 * MM, largeur_pad=0.56 * MM) is False

    def test_a_egalite_exacte_la_dispense_s_applique(self):
        assert RUN._via_in_pad_dispense_de_clearance(
            diametre_via=0.60 * MM, largeur_pad=0.60 * MM) is True

    def test_un_via_nul_ne_dispense_de_rien(self):
        # Pas de via : il n y a rien à dispenser, et rendre True masquerait
        # un refus légitime.
        assert RUN._via_in_pad_dispense_de_clearance(
            diametre_via=0.0, largeur_pad=0.56 * MM) is False

    def test_une_pastille_de_largeur_nulle_ne_dispense_de_rien(self):
        assert RUN._via_in_pad_dispense_de_clearance(
            diametre_via=0.56 * MM, largeur_pad=0.0) is False


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8")

    def _recours(self) -> str:
        # ⚠️ ANCRER SUR LA FIN DU BLOC, PAS SUR UNE LONGUEUR. Une tranche de
        # 1400 caracteres a lache des qu une verification de couche s est
        # inseree dans le recours : `_trou_libre` etait toujours appele, mais
        # hors de la fenetre. C est la sixieme ancre fragile de cette suite —
        # toutes ecrites par moi, toutes du meme motif.
        i = self.SOURCE.index("Dernier recours : le via DANS la pastille")
        j = self.SOURCE.index("via = pcbnew.PCB_VIA(board)", i)
        return self.SOURCE[i:j]

    def test_le_dernier_recours_CONSULTE_la_dispense(self):
        # ⚠️ Une règle correcte jamais appelée est indistinguable d'une règle
        # absente.
        assert "_via_in_pad_dispense_de_clearance(" in self._recours()

    def test_le_TROU_reste_verifie(self):
        # ⚠️ Un perçage est physique : la dispense porte sur le CUIVRE, jamais
        # sur le trou. Deux trous au même endroit restent impossibles.
        assert "_trou_libre(" in self._recours()

    def test_la_dispense_ne_supprime_PAS_le_test_d_obstacle(self):
        # Il doit rester, pour les vias qui débordent de leur pastille.
        # ⚠️ Ancré sur la MESURE, pas sur le nom : `_dist_point_boite` a été
        # remplacé par `_distance_a_obstacle` le 2026-09-02, quand les pistes
        # ont cessé d'être réduites à leur boîte englobante. Quatrième ancrage
        # fragile de la session — un nom de fonction n'est pas un invariant.
        assert "_distance_a_obstacle(" in self._recours()


class TestPercageMinimal:
    """Le perçage doit satisfaire la contrainte que le DRC APPLIQUE.

    ⚠️ Mesure du 2026-09-02, après la dispense de clearance ci-dessus : les
    vias posés reliaient bien la pastille, mais introduisaient une erreur —

        drill_out_of_range
        Hole size out of range (board setup constraints min hole 0.3000 mm;
                                actual 0.2800 mm)

    Le perçage était calculé comme la moitié du via (0,56 / 2 = 0,28 mm), avec
    pour seul plancher `_VIA_MIN_MM = 0,2 mm`. Or cette constante vient de la
    limite JLCPCB sur le DIAMÈTRE DE VIA — ce n'est pas le perçage minimal, et
    KiCad applique 0,3 mm par défaut.

    ⚠️ Encore une constante choisie là où une contrainte existait. Reproduire
    la règle du juge n'est pas une décision produit : c'est lui obéir.
    """

    def test_le_percage_ne_descend_jamais_sous_le_minimum_de_KiCad(self):
        p = RUN._percage_pour_via(0.56 * MM)
        assert p >= RUN._PERCAGE_MIN_KICAD_MM, p / MM

    def test_un_via_large_garde_un_percage_proportionne(self):
        # Sur un via confortable, la moitié reste la règle.
        assert RUN._percage_pour_via(1.0 * MM) == 0.5 * MM

    def test_le_cas_mesure_remonte_a_0_3_mm(self):
        # 0,56 / 2 = 0,28 mm -> refusé par le DRC. On remonte à 0,30.
        assert RUN._percage_pour_via(0.56 * MM) == 0.30 * MM

    def test_une_pastille_trop_etroite_pour_le_percage_minimal_est_REFUSEE(self):
        # ⚠️ Si le perçage minimal ne tient pas dans la pastille, poser le via
        # ferait déborder le trou : mieux vaut renoncer que livrer un board
        # non fabricable.
        assert RUN._via_in_pad_possible(0.25 * MM, 0.6 * MM, 0.0) == 0

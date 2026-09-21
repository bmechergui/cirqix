"""Un amas de plan ORPHELIN qui porte une pastille se RELIE — il ne se retire pas.

⚠️ Mesure du 2026-09-21, carte-07, meme placement gele, trois tirages :

    tirage propre  : 10 ilots GND, UN amas
    tirage fautif  :  7 ilots GND, DEUX amas
                      amas orphelin = F.Cu 6,48 mm2 + B.Cu 14,97 mm2,
                      et il porte la pastille de masse de D16

Les deux remedes existants s ANNULENT sur ce cas, et c est la cause exacte
(diagnostic convergent de Codex et de GLM, consultes ce jour) :

  - `_stitch_zones` pose un via dans l ilot ; ce via atteint SON JUMEAU de
    l autre face. Un site a ete trouve, donc l ilot n entre pas dans `perdus`
    et le board change — mais rien n est raccorde au plan principal ;
  - `_retirer_ilots_flottants` voit ce meme via toucher du cuivre du net en
    face (le jumeau) : `reliants >= 1`, l amas n est donc jamais retire.

Les jumeaux se portent garants l un de l autre.

⚠️ RETIRER EST INTERDIT ICI, et c est deja mesure : le 2026-09-19, juger par
composante a fait passer carte-09 de 2 a 3 connexions manquantes — le retrait
otait le jumeau et laissait l ilot a pastille isole. On ne refait pas cette
mesure.

REGLE : un amas non relie au principal qui porte une pastille du net se
raccorde par une COURTE PISTE, sur la face ou le couloir est libre.

⚠️ CE N EST PAS L « AMORCE SUR LA FACE OPPOSEE » REFUTEE LE 2026-09-02 : celle-ci
se posait AVANT le routage et etait protegee dans le DSN, ce qui bouchait le
routeur (2798 s contre 901). Ici on repare APRES, sur un board fini, et rien
n est protege.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_runner_amas", RACINE / "tools" / "routing_pcbnew_runner.py")
R = importlib.util.module_from_spec(_spec)
sys.modules["_runner_amas"] = R
_spec.loader.exec_module(R)


class TestLeSegmentDeRaccord:
    """`_segment_de_raccord(depart, arrivee, obstacles, demi_largeur)` : le
    couloir est-il libre ? Fonction PURE, sans pcbnew."""

    def test_un_couloir_libre_est_accepte(self):
        assert R._couloir_libre((0.0, 0.0), (10.0, 0.0), [], 0.125, 0.2) is True

    def test_un_obstacle_sur_le_trajet_le_refuse(self):
        # Un point du net voisin, pile au milieu du segment.
        assert R._couloir_libre((0.0, 0.0), (10.0, 0.0), [(5.0, 0.0, 0.3)],
                                0.125, 0.2) is False

    def test_un_obstacle_ECARTE_ne_gene_pas(self):
        assert R._couloir_libre((0.0, 0.0), (10.0, 0.0), [(5.0, 9.0, 0.3)],
                                0.125, 0.2) is True

    def test_le_degagement_est_respecte_au_millimetre(self):
        # Obstacle a 0,30 mm de l axe : demi-piste 0,125 + degagement 0,2 = 0,325.
        assert R._couloir_libre((0.0, 0.0), (10.0, 0.0), [(5.0, 0.30, 0.0)],
                                0.125, 0.2) is False
        assert R._couloir_libre((0.0, 0.0), (10.0, 0.0), [(5.0, 0.35, 0.0)],
                                0.125, 0.2) is True


class TestLaRegle:
    SOURCE = (RACINE / "tools" / "routing_pcbnew_runner.py").read_text(encoding="utf-8")

    def test_un_amas_a_pastille_n_est_jamais_retire(self):
        corps = self.SOURCE[self.SOURCE.index("def _relier_les_amas_orphelins("):]
        assert "Remove(" not in corps[:corps.index("\ndef ")], \
            "relier, pas retirer — le retrait a deja ete mesure et refute"

    def test_le_raccord_contourne_au_lieu_d_aller_tout_droit(self):
        corps = _bloc(self.SOURCE, "_relier_les_amas_orphelins")
        assert "_chemin_de_contournement(" in corps,             "la ligne droite a ete mesuree et refutee"

    def test_l_operation_est_exposee_au_service(self):
        assert '"relier_amas"' in self.SOURCE, "operation non declaree"



def _bloc(source: str, nom: str) -> str:
    debut = source.index(f"def {nom}(")
    return source[debut:source.index(chr(10) + "def ", debut + 1)]


class TestCablage:
    ROUTING = (RACINE / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_relier_avant_retirer(self):
        raccord = self.ROUTING.rindex("final = _relier_les_amas_orphelins(final)")
        retrait = self.ROUTING.rindex("final = _retirer_ilots_flottants(final)")
        assert raccord < retrait, "on retire avant d avoir essaye de relier"

    def test_aucun_raccord_possible_se_DIT(self):
        corps = _bloc(self.ROUTING, "_relier_les_amas_orphelins")
        i = corps.index("if not relies:")
        assert "logger.warning" in corps[i:i + 400],             "« rien a faire » et « rien n a marche » rendent la meme trace"

    def test_ne_peut_qu_ameliorer(self):
        assert "_aggrave_le_board(" in _bloc(self.ROUTING, "_relier_les_amas_orphelins")


class TestLaCoutureViseLePlanPRINCIPAL:
    """⚠️ Ce que les trois agents ont pointé, et que la preuve à froid confirme :
    `_stitch_zones` ORDONNE ses candidats par « ce point touche-t-il du cuivre
    du net sur la face opposée ? », et `_cuivre_du_net_sur` rend TOUT le cuivre
    du net — le jumeau de la paire orpheline compris. Un via place « au mieux »
    peut donc ne rejoindre que le jumeau : les deux moities se portent garantes,
    et l amas reste coupe du plan.

    La preference doit viser le cuivre du PLAN PRINCIPAL, pas n importe quel
    cuivre du net.

    ⚠️ On ORDONNE, on ne FILTRE pas — exiger du cuivre en face a ete mesure et
    REFUTE le 2026-09-01 (1 -> 4 connexions manquantes) : la condition refusait
    des sites sans en chercher d autres.

    ⚠️ Un raccord par PISTE DROITE a ete mesure et refute le 2026-09-21 : un
    ilot est isole PAR une piste qui le coupe, donc toute ligne droite vers le
    plan la retraverse. « 5 amas vus, AUCUN raccorde. »
    """

    SOURCE = (RACINE / "tools" / "routing_pcbnew_runner.py").read_text(encoding="utf-8")

    def test_un_moyen_de_viser_le_seul_plan_principal_existe(self):
        assert "def _cuivre_principal_en_face(" in self.SOURCE

    def test_la_couture_s_en_sert(self):
        corps = _bloc(self.SOURCE, "_stitch_zones")
        i = corps.index("en_face = ")
        assert "principal" in corps[i:i + 300], \
            "la preference vise encore n importe quel cuivre du net"


class TestLeCheminDeContournement:
    """⚠️ La ligne droite est REFUTEE (mesure du 2026-09-21 : « 5 amas vus, AUCUN
    raccorde ») — un ilot est isole PAR une piste, donc toute droite vers le
    plan la retraverse. Avis convergents de Codex et de GLM : il faut un COURT
    CHEMIN qui contourne. « Une piste n est un mur que d un cote. »

    `_chemin_de_contournement(depart, buts, libre, pas, portee)` : A* sur une
    grille, `libre(x, y)` decide, `buts` est l ensemble d arrivee. Rend la
    liste des points, ou None. Fonction PURE — aucun pcbnew."""

    def test_une_ligne_droite_quand_rien_ne_gene(self):
        chemin = R._chemin_de_contournement((0.0, 0.0), [(4.0, 0.0)],
                                            lambda x, y: True, 1.0, 20.0)
        assert chemin is not None
        assert chemin[0] == (0.0, 0.0) and chemin[-1] == (4.0, 0.0)

    def test_il_CONTOURNE_un_mur_ouvert_d_un_cote(self):
        # Mur vertical en x = 2, de y = -10 a y = 1 : il faut passer par le haut.
        def libre(x, y):
            return not (abs(x - 2.0) < 0.5 and -10.0 <= y <= 1.0)
        chemin = R._chemin_de_contournement((0.0, 0.0), [(4.0, 0.0)],
                                            libre, 0.5, 30.0)
        assert chemin is not None, "l A* n a pas contourne le bout du mur"
        assert all(libre(x, y) for x, y in chemin)
        assert max(y for _x, y in chemin) > 1.0, "il est passe a travers le mur"

    def test_un_mur_INFRANCHISSABLE_rend_None(self):
        chemin = R._chemin_de_contournement((0.0, 0.0), [(4.0, 0.0)],
                                            lambda x, y: abs(x - 2.0) >= 0.5,
                                            0.5, 12.0)
        assert chemin is None

    def test_le_TRAVAIL_est_borne_aussi(self):
        """⚠️ Une portee geometrique ne borne pas le travail : chaque noeud
        interroge tous les obstacles. Sans plafond de noeuds, une grande carte
        fait geler `route_auto` (revue du 2026-09-21)."""
        vus = []

        def libre(x, y):
            vus.append((x, y))
            return not (abs(x - 2.0) < 0.5 and -1000.0 <= y <= 1000.0)

        assert R._chemin_de_contournement((0.0, 0.0), [(4.0, 0.0)], libre,
                                          0.05, 500.0, noeuds_max=200) is None
        assert len(vus) < 5000, "le plafond de noeuds ne borne rien"

    def test_la_portee_borne_la_recherche(self):
        # Portee courte : le detour ne tient pas dedans, on renonce vite.
        def libre(x, y):
            return not (abs(x - 2.0) < 0.5 and -10.0 <= y <= 1.0)
        assert R._chemin_de_contournement((0.0, 0.0), [(4.0, 0.0)],
                                          libre, 0.5, 1.0) is None

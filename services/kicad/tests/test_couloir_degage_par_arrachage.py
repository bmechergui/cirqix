"""Quand UN segment enferme un amas de masse, on DEPLACE le segment.

⚠️ Mesure du 2026-09-22, `carte-10`, sur le board qui porte VRAIMENT la
connexion manquante (`/tmp/livr/carte-10-maximale/route.kicad_pcb` — le board
versionne du 21, lui, est propre et se pretait a toutes les demonstrations) :

    ilots GND, deux faces          23
    orphelins                       2, et ce sont des JUMEAUX
    ilot F.Cu   1,30 mm2  porte la pastille C35.2
    ilot B.Cu   0,99 mm2  aucune pastille
    vis-a-vis avec le plan principal        0 point, sur les deux
    sites refuses par la couture            23 et 18, TOUS
    distance au plan principal   0,862 mm (F.Cu) · 0,781 mm (B.Cu)
    segments coupant le couloir  **1 par face** (EXT2_1, EXT4_1)

Les deux remedes existants ne peuvent rien : un via ne tient pas dans un
millimetre carre (« obstacle », « trou trop pres »), et l A* de contournement
rend `sans_chemin` — l amas est ENCERCLE, pas mal cherche.

REGLE : si un petit nombre de SEGMENTS d autres nets suffit a rouvrir le
couloir, on les arrache, on pose le raccord de masse, puis on les reroute
localement. Si l un d eux ne peut pas etre reroute, on remet TOUT en place.

⚠️ BORNE OBLIGATOIRE. Sans plafond, « quels segments oter » est une recherche
combinatoire ouverte — exactement ce que `_NOEUDS_MAX_CONTOURNEMENT` interdit
deja pour l A*. On ne considere que les segments qui bloquent le couloir DROIT,
et jamais plus de `_SEGMENTS_ARRACHABLES`.

⚠️ ON NE DEPLACE QU UN SEGMENT. Une pastille, un via, un percage ne bougent
pas : ils appartiennent a une empreinte ou a une liaison verticale. Un obstacle
qui n est pas un segment interdit donc le degagement, quel qu en soit le compte.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

_spec = importlib.util.spec_from_file_location(
    "_runner_couloir", RACINE / "tools" / "routing_pcbnew_runner.py")
R = importlib.util.module_from_spec(_spec)
sys.modules["_runner_couloir"] = R
_spec.loader.exec_module(R)

SOURCE = (RACINE / "tools" / "routing_pcbnew_runner.py").read_text(encoding="utf-8")

# Toutes les valeurs en millimetres, comme les autres tests purs du fichier.
LARGEUR = 0.125          # demi-largeur d une piste de 0,25 mm
DEGAGEMENT = 0.2


def _code_seul(source: str) -> str:
    """Retire commentaires ET docstrings — ils CITENT les noms exprès."""
    lignes = []
    dans_doc = False
    for ligne in source.splitlines():
        nue = ligne.strip()
        if dans_doc:
            if nue.endswith('"""') or nue.endswith("'''"):
                dans_doc = False
            continue
        if nue.startswith('"""') or nue.startswith("'''"):
            # docstring d une seule ligne ?
            if not (len(nue) > 3 and (nue.endswith('"""') or nue.endswith("'''"))):
                dans_doc = True
            continue
        if nue.startswith("#"):
            continue
        lignes.append(ligne)
    return chr(10).join(lignes)


def _segment(x1, y1, x2, y2, largeur=0.25):
    return ("segment", x1, y1, x2, y2, largeur)


class TestLesSegmentsQuiBloquent:
    """`_segments_qui_bloquent` : QUI, tout seul, ferme ce couloir."""

    def test_un_couloir_libre_ne_designe_personne(self):
        obstacles = [_segment(0.0, 5.0, 10.0, 5.0)]     # loin du trajet
        assert R._segments_qui_bloquent(
            (0.0, 0.0), (1.0, 0.0), obstacles, LARGEUR, DEGAGEMENT) == []

    def test_le_segment_en_travers_est_designe(self):
        # Une piste perpendiculaire, pile au milieu : c est elle qui ferme.
        obstacles = [_segment(0.5, -1.0, 0.5, 1.0)]
        assert R._segments_qui_bloquent(
            (0.0, 0.0), (1.0, 0.0), obstacles, LARGEUR, DEGAGEMENT) == [0]

    def test_seuls_les_segments_sont_candidats(self):
        # Une boite (pastille, via) n est JAMAIS candidate au deplacement.
        boite = (0.4, -1.0, 0.6, 1.0)
        assert R._segments_qui_bloquent(
            (0.0, 0.0), (1.0, 0.0), [boite], LARGEUR, DEGAGEMENT) == []


class TestLeCouloirDegageable:
    """`_couloir_degageable` : rend la LISTE a arracher, ou None — et un None
    se lit « on ne sait pas degager », jamais « rien a faire »."""

    def test_un_seul_segment_a_arracher(self):
        obstacles = [_segment(0.5, -1.0, 0.5, 1.0)]
        assert R._couloir_degageable(
            (0.0, 0.0), (1.0, 0.0), obstacles, LARGEUR, DEGAGEMENT,
            plafond=3) == [0]

    def test_un_couloir_deja_libre_ne_demande_aucun_arrachage(self):
        # Rien a arracher : la fonction rend une liste VIDE, pas None. Le cas
        # normal et l echec ne doivent pas rendre la meme valeur.
        assert R._couloir_degageable(
            (0.0, 0.0), (1.0, 0.0), [], LARGEUR, DEGAGEMENT, plafond=3) == []

    def test_au_dela_du_plafond_on_renonce(self):
        obstacles = [_segment(x, -1.0, x, 1.0) for x in (0.2, 0.4, 0.6, 0.8)]
        assert R._couloir_degageable(
            (0.0, 0.0), (1.0, 0.0), obstacles, LARGEUR, DEGAGEMENT,
            plafond=3) is None

    def test_une_pastille_en_travers_interdit_le_degagement(self):
        # On ne deplace pas une empreinte pour faire passer de la masse.
        boite = (0.4, -1.0, 0.6, 1.0)
        assert R._couloir_degageable(
            (0.0, 0.0), (1.0, 0.0), [boite], LARGEUR, DEGAGEMENT,
            plafond=3) is None

    def test_un_segment_retire_qui_ne_suffit_pas_rend_None(self):
        # Le segment bloque, mais une pastille bloque AUSSI : l arracher ne
        # rouvrirait rien. On ne paie pas un arrachage inutile.
        obstacles = [_segment(0.3, -1.0, 0.3, 1.0), (0.6, -1.0, 0.8, 1.0)]
        assert R._couloir_degageable(
            (0.0, 0.0), (1.0, 0.0), obstacles, LARGEUR, DEGAGEMENT,
            plafond=3) is None


class TestLaBorne:
    def test_le_plafond_est_une_constante_du_module(self):
        assert isinstance(R._SEGMENTS_ARRACHABLES, int)
        assert 1 <= R._SEGMENTS_ARRACHABLES <= 5


class TestLeCablage:
    """Une regle correcte JAMAIS APPELEE est indistinguable d une regle
    absente — c est ce qui a masque des semaines que le Geometre ne tournait
    pas. On teste le comportement ET le cablage."""

    def test_le_raccord_des_amas_tente_le_degagement(self):
        code = _code_seul(SOURCE)
        debut = code.index("def _relier_les_amas_orphelins")
        corps = code[debut:]
        assert "_degager_le_couloir" in corps, (
            "le raccord des amas orphelins doit TENTER le degagement quand "
            "l A* ne trouve aucun chemin")

    def test_le_degagement_est_borne_par_la_regle(self):
        # La borne vit a UN endroit : `_degager_le_couloir` doit passer par
        # `_couloir_degageable`, jamais decider lui-meme quoi arracher.
        code = _code_seul(SOURCE)
        debut = code.index("def _degager_le_couloir")
        fin = code.index("def _relier_les_amas_orphelins")
        assert "_couloir_degageable" in code[debut:fin]

    def test_un_arrachage_rate_remet_tout_en_place(self):
        # Tout ou rien : un reroutage a moitie fait echangerait une masse
        # manquante contre une ALIMENTATION manquante.
        code = _code_seul(SOURCE)
        debut = code.index("def _degager_le_couloir")
        fin = code.index("def _relier_les_amas_orphelins")
        corps = code[debut:fin]
        assert "board.Remove" in corps and "_poser_piste" in corps

    def test_un_arrachage_rate_est_compte(self):
        # Trois causes indistinguables valent zero cause : le rapport doit
        # distinguer « pas de couloir degageable » du reste.
        code = _code_seul(SOURCE)
        assert "sans_degagement" in code
        assert "reroutage_impossible" in code


class TestLeDetourParLAutreFace:
    """Quand le raccord de masse barre le couloir sur TOUTE sa largeur, le
    signal arraché ne peut pas revenir sur la même face — c'est arithmétique.
    Il passe par l'autre face, deux vias.

    ⚠️ Mesure du 2026-09-22, `carte-10` : couloir 0,862 mm, raccord 0,65 mm
    (cuivre + dégagement des deux côtés), signal 0,65 mm à son tour. Total
    exigé 1,30 mm. Il manque 0,44 mm et aucune finesse ne les rattrape.

    Résultat du détour, mesuré sur ce board, zones recoulées :
    **33 violations, 0 erreur, 0 connexion manquante** — contre 1 manquante
    avant. Le défaut est refermé.
    """

    def test_le_reroutage_tente_l_autre_face(self):
        code = _code_seul(SOURCE)
        debut = code.index("def _rerouter_un_segment")
        fin = code.index("def _site_de_via")
        assert "_detour_par_l_autre_face" in code[debut:fin], (
            "un segment que la même face ne peut plus accueillir doit "
            "changer de face, pas être abandonné")

    def test_le_via_voit_TOUTES_les_couches(self):
        # Un via TRAVERSE : prendre ses obstacles sur la seule couche de la
        # piste le ferait percer à l'aveugle dans le cuivre d'en face.
        code = _code_seul(SOURCE)
        debut = code.index("def _site_de_via")
        fin = code.index("def _chemin_sur_couche")
        corps = code[debut:fin]
        assert "_obstacles_d_un_autre_net(board, int(netcode))" in corps
        assert "couches=" not in corps
        assert "_trou_libre" in corps

    def test_aucun_site_rend_None_jamais_un_repli(self):
        # « pas de place » et « voilà une place » ne doivent pas se ressembler.
        code = _code_seul(SOURCE)
        debut = code.index("def _site_de_via")
        fin = code.index("def _chemin_sur_couche")
        # La fonction s'arrête à la def suivante, pas à une fonction voisine.
        suite = code.index(chr(10) + "def ", debut + 1)
        corps = code[debut:suite].rstrip()
        # Sa dernière instruction est un `return None` nu : aucun point de
        # repli ne peut sortir par le bas.
        assert corps.splitlines()[-1].strip() == "return None"


class TestLaRecouleeApresDegagement:
    """Le détour traverse le plan coulé : sans recoulée, le board porte de
    vraies violations (51 erreurs mesurées) que la coulée efface en découpant
    le cuivre autour de la piste neuve. Juger sans recouler ferait REJETER un
    board qui, recoulé, est parfait."""

    def test_le_router_recoule_quand_il_a_degage(self):
        source = (RACINE / "routers" / "routing.py").read_text(encoding="utf-8")
        code = _code_seul(source)
        debut = code.index("def _relier_les_amas_orphelins")
        fin = code.index("def _retirer_ilots_flottants")
        corps = code[debut:fin]
        assert "degages" in corps
        assert "_fill_zones(recousu)" in corps
        # La recoulée vient AVANT le jugement, sinon elle ne sert à rien.
        assert corps.index("_fill_zones(recousu)") < corps.index("_aggrave_le_board")


class TestLeResumeDesEchecs:
    """⚠️ Le DIAGNOSTIC ne doit jamais tuer son appelant.

    Mesure du 2026-09-23, `carte-09` : `motifs_reroutage` est un DICTIONNAIRE
    de raisons, et le résumé formatait toutes les valeurs en `%d`. Le
    `TypeError` remontait jusqu'à un **HTTP 500** et le routage entier était
    perdu — la carte sortait sans board.

    C'est la faute déjà inscrite pour `_recuperer_jobs_abandonnes` : le compteur
    qu'on ajoute pour comprendre un échec devient lui-même la panne.
    """

    def _resume(self):
        import importlib.util as iu
        spec = iu.spec_from_file_location(
            "_routers_routing_resume", RACINE / "routers" / "routing.py")
        # Le module importe pcbnew et consorts : on lit la fonction seule.
        source = (RACINE / "routers" / "routing.py").read_text(encoding="utf-8")
        debut = source.index("def _resume_des_echecs")
        fin = source.index(chr(10) + "def ", debut + 1)
        espace: dict = {}
        exec(compile(source[debut:fin], "<resume>", "exec"), espace)
        return espace["_resume_des_echecs"]

    def test_un_compteur_dictionnaire_ne_leve_pas(self):
        resume = self._resume()
        texte = resume({"sans_chemin": 2,
                        "motifs_reroutage": {"reroutage : sans_chemin": 1}})
        assert "sans_chemin=2" in texte
        assert "reroutage : sans_chemin:1" in texte

    def test_aucun_echec_rend_une_chaine_vide(self):
        # Vide, pas None : l'appelant y substitue « raison inconnue ».
        resume = self._resume()
        assert resume({}) == ""
        assert resume(None) == ""

    def test_les_zeros_ne_polluent_pas_la_ligne(self):
        resume = self._resume()
        assert resume({"sans_cible": 0, "sans_chemin": 3}) == "sans_chemin=3"


class TestLeViaDuDetourRespecteLaFABRICATION:
    """⚠️ Trouvé par la revue avant fusion, et invisible à tout le reste.

    `_site_de_via` passait `float(perc_d)` — 0,30 mm — comme écart entre
    perçages, là où les six autres poses de via du fichier passent
    `_ECART_TROUS_MM` (0,50 mm, règle JLCPCB). Un via de détour était donc
    accepté à 0,30 mm bord-à-bord d'un trou voisin.

    Et le défaut ne se voyait NULLE PART : `hole_to_hole` sort en **warning**,
    `_aggrave_le_board` ne compte que les `error`. Le board partait donc
    « 0 erreur » et se faisait refuser au perçage. C'est la famille que ce
    dépôt traque — un échec qui rend la valeur du cas normal.
    """

    def _bloc(self, nom):
        code = _code_seul(SOURCE)
        debut = code.index("def %s" % nom)
        fin = code.index(chr(10) + "def ", debut + 1)
        return code[debut:fin]

    def test_le_site_de_via_utilise_la_regle_de_fabrication(self):
        corps = self._bloc("_site_de_via")
        assert "_ECART_TROUS_MM" in corps, (
            "l'écart entre perçages est une règle de fabrication, pas le "
            "diamètre du trou")

    def test_le_percage_passe_par_le_plancher_kicad(self):
        corps = self._bloc("_site_de_via")
        assert "_percage_pour_via" in corps, (
            "le perçage doit passer par le plancher KiCad, comme les six "
            "autres poses de via du fichier")

    def test_les_deux_vias_de_la_paire_gardent_le_meme_ecart(self):
        corps = self._bloc("_detour_par_l_autre_face")
        assert "_ECART_TROUS_MM" in corps, (
            "le garde-fou entre les deux vias mesurait perc_d * 2.0 entre "
            "CENTRES, soit 0,30 mm bord-à-bord — la moitié de la règle")


class TestLeRapportNeSeContreditPas:
    """Un amas perdu était compté DEUX fois : `_degager_le_couloir` incrémente
    déjà sa propre raison, et l'appelant rajoutait `sans_chemin`."""

    def test_l_appelant_ne_recompte_pas_un_echec_deja_compte(self):
        code = _code_seul(SOURCE)
        debut = code.index("def _relier_les_amas_orphelins")
        corps = code[debut:]
        i = corps.index("_degager_le_couloir(")
        suite = corps[i:i + 800]
        assert "sans_degagement" in suite and "reroutage_impossible" in suite, (
            "l'appelant doit vérifier que l'échec n'a pas déjà été compté")

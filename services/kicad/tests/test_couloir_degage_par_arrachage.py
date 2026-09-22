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

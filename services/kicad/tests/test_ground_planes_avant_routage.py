"""Plans de masse coulés AVANT le routage, sur les deux faces extérieures.

Deux défauts corrigés d'un coup.

**1. Le plan arrivait APRÈS le routage.** `handleRouting` appelait
`addGroundPlane` sur le board déjà routé : le routeur n'avait jamais su que le
plan existait, et tirait donc des pistes GND à travers toute la carte au lieu de
relier chaque pad par un moignon. Vérifié le 2026-08-21 : l'export DSN rend bien
la zone sous forme de `(plane GND (polygon B.Cu …))`, donc Freerouting SAIT s'y
raccorder — encore faut-il la lui donner.

**2. Le polygone était dessiné à l'ORIGINE.** La version TypeScript trace
`(xy 0 0) … (xy largeur hauteur)`. Or le contour du board STM32 réel est à
`(gr_rect (start 100 100) (end 160 140))` : le plan tombait **entièrement hors
de la carte**. Un plan hors contour ne relie rien et ne se voit pas.

⚠️ Décision produit (2026-08-21) : les plans vont sur les deux faces
EXTÉRIEURES — `F.Cu` et `B.Cu` — quel que soit le nombre de couches. Sur un
board 4 couches cela donne `GND / SIG / SIG / GND`, un empilage blindé ; les
couches internes restent aux signaux. Le coût assumé est un via par broche de
signal, puisque les composants sont montés sur les faces.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _board(contour: str, gnd: str = '\t(net 3 "GND")') -> bytes:
    return (
        "(kicad_pcb\n"
        '\t(version 20260206)\n'
        "\t(layers\n"
        '\t\t(0 "F.Cu" signal)\n'
        '\t\t(31 "B.Cu" signal)\n'
        '\t\t(44 "Edge.Cuts" user)\n'
        "\t)\n"
        f"{gnd}\n"
        f"{contour}\n"
        ")"
    ).encode("utf-8")


RECT = (
    "\t(gr_rect\n"
    "\t\t(start 100.0 100.0)\n"
    "\t\t(end 160.0 140.0)\n"
    '\t\t(layer "Edge.Cuts")\n'
    "\t)"
)

LIGNES = "\n".join(
    f'\t(gr_line (start {x1} {y1}) (end {x2} {y2}) (layer "Edge.Cuts"))'
    for x1, y1, x2, y2 in [
        (10, 20, 70, 20), (70, 20, 70, 60), (70, 60, 10, 60), (10, 60, 10, 20)
    ]
)


class TestContourDuBoard:
    def test_lit_un_contour_rectangulaire(self):
        assert routing_router._board_outline(_board(RECT)) == (100.0, 100.0, 160.0, 140.0)

    def test_lit_un_contour_en_segments(self):
        assert routing_router._board_outline(_board(LIGNES)) == (10.0, 20.0, 70.0, 60.0)

    def test_sans_contour_ne_devine_pas(self):
        # Un plan place au hasard ne relierait rien. Mieux vaut ne rien couler.
        assert routing_router._board_outline(_board("")) is None


class TestPlansDeMasse:
    def test_coule_sur_la_face_arriere_en_deux_couches(self):
        """Ce test exigeait LES DEUX faces jusqu au 2026-08-22.

        La mesure l a infirme : sur 2 couches, un plan sur la face composants
        laisse 2 a 6 connexions manquantes, jamais 0. Voir TestRegleDeCouche
        pour la geometrie qui l explique. On corrige le test, pas la mesure.
        """
        out = routing_router._add_ground_planes(_board(RECT)).decode("utf-8")
        zones = re.findall(r'\(zone[^\n]*\(net_name "GND"\)[^\n]*\(layer "([^"]+)"', out)
        assert zones == ["B.Cu"]

    def test_le_polygone_epouse_le_contour_reel(self):
        # LE défaut : un polygone à l'origine tomberait hors de la carte.
        out = routing_router._add_ground_planes(_board(RECT)).decode("utf-8")
        assert "(xy 100" in out and "(xy 160" in out
        assert "(xy 0 0)" not in out

    def test_reste_sur_les_faces_meme_en_quatre_couches(self):
        quatre = routing_router._expand_stackup(_board(RECT), 4)
        out = routing_router._add_ground_planes(quatre).decode("utf-8")
        zones = sorted(re.findall(r'\(zone[^\n]*\(net_name "GND"\)[^\n]*\(layer "([^"]+)"', out))
        assert zones == ["B.Cu", "F.Cu"]
        assert not any("In" in z for z in zones)

    def test_ne_touche_pas_un_board_sans_gnd(self):
        sans = _board(RECT, gnd='\t(net 1 "VCC")')
        assert routing_router._add_ground_planes(sans) == sans

    def test_n_empile_pas_un_second_plan(self):
        # `kct route` coule lui-même ses zones power : deux remplissages
        # concurrents sur la même couche seraient un conflit, pas une sécurité.
        une_fois = routing_router._add_ground_planes(_board(RECT))
        deux_fois = routing_router._add_ground_planes(une_fois)
        assert deux_fois == une_fois

    def test_reconnait_le_gnd_ecrit_par_kicad_10(self):
        # `(net "GND")` sans numéro — la forme que produit pcbnew 10.
        nomme = _board(RECT, gnd='\t\t(pad "1" smd rect (net "GND"))')
        out = routing_router._add_ground_planes(nomme).decode("utf-8")
        assert '(net_name "GND")' in out


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_les_plans_sont_coules_avant_le_routage(self):
        code = self.SOURCE
        pose = code.index("_add_ground_planes(")
        route = code.index("_route_auto_once(tentative)")
        assert pose < route, (
            "les plans doivent exister AVANT que le routeur reçoive le board — "
            "sinon il route GND en pistes, faute de savoir qu'un plan existe"
        )


class TestIsolementDeLaZone:
    """0,5 mm d isolement vide le cuivre entre les broches d un boitier fine-pitch.

    Mesure du 2026-08-21, board STM32 (LQFP-48, pas de 0,5 mm) :

        clearance 0.5  -> 6 connexions manquantes
        clearance 0.25 -> 3 connexions manquantes
        clearance 0.2  -> 3 connexions manquantes

    Les broches restantes sont celles du LQFP-48 : entre deux pattes distantes de
    0,5 mm il n y a place pour aucun cuivre de plan, quel que soit l isolement.
    Ces broches-la demandent un routage de sortie (fanout), pas un plan plus
    agressif — mais 0,25 mm est meilleur dans tous les cas, sans contrepartie.

    La valeur 0,5 venait de la version TypeScript, ecrite pour un board simple.
    """

    def test_l_isolement_est_realiste_pour_du_fine_pitch(self):
        out = routing_router._add_ground_planes(_board(RECT)).decode("utf-8")
        assert "(clearance 0.25)" in out, (
            "0,5 mm repousse le plan hors d atteinte des boitiers a pas fin"
        )

    def test_le_gap_thermique_suit(self):
        out = routing_router._add_ground_planes(_board(RECT)).decode("utf-8")
        assert "(thermal_gap 0.25)" in out


class TestRegleDeCouche:
    """Sur 2 couches, le plan de la face composants ne peut pas etre raccorde.

    Geometrie mesuree sur le LQFP-48 du board STM32 :

        taille de pad : 1,475 x 0,3 mm
        pas           : 0,5 mm
        -> espace entre deux pattes : 0,2 mm

    Un isolement de 0,25 mm de chaque cote en demanderait 0,5. Meme a 0,1 mm de
    chaque cote il resterait ZERO. Le cuivre du plan ne passe pas entre les
    pattes — ce n est pas un reglage, c est la geometrie.

    Et sur 2 couches, chaque piste de sortie DECOUPE le plan de la face qu elle
    traverse : on ne peut pas exiger a la fois un plan continu et un routage
    dense sur la meme face.

    Mesures (Freerouting, board STM32) :

        aucun plan            -> 0 connexion manquante
        plan B.Cu seul        -> 0 connexion manquante
        plans F.Cu + B.Cu     -> 2 a 6 selon l isolement, jamais 0

    Trois sources concordantes : la geometrie ci-dessus, kicad-tools upstream
    (« sur un empilage 2 couches chaque masse recoit une priorite distincte sur
    B.Cu »), et une revue externe.

    ⚠️ A partir de 4 couches la regle S INVERSE : les signaux vivent a
    l interieur, les deux faces exterieures restent continues, et le fanout
    reprend tout son sens. C est le choix produit de l utilisateur, conserve.
    """

    def test_deux_couches_ne_coule_que_le_dessous(self):
        out = routing_router._add_ground_planes(_board(RECT)).decode("utf-8")
        zones = re.findall(r'\(zone[^\n]*\(net_name "GND"\)[^\n]*\(layer "([^"]+)"', out)
        assert zones == ["B.Cu"], f"attendu B.Cu seul, obtenu {zones}"

    def test_quatre_couches_coule_les_deux_faces(self):
        quatre = routing_router._expand_stackup(_board(RECT), 4)
        out = routing_router._add_ground_planes(quatre).decode("utf-8")
        zones = sorted(
            re.findall(r'\(zone[^\n]*\(net_name "GND"\)[^\n]*\(layer "([^"]+)"', out)
        )
        assert zones == ["B.Cu", "F.Cu"], f"attendu les deux faces, obtenu {zones}"

    def test_les_couches_internes_ne_recoivent_jamais_de_plan(self):
        six = routing_router._expand_stackup(_board(RECT), 6)
        out = routing_router._add_ground_planes(six).decode("utf-8")
        zones = re.findall(r'\(zone[^\n]*\(net_name "GND"\)[^\n]*\(layer "([^"]+)"', out)
        assert not any("In" in z for z in zones), "les internes sont pour les signaux"

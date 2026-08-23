"""Ne jamais couler un second plan sur une couche qui en porte deja un.

Trouve le 2026-08-24 en telechargeant le board d un run reel. Il portait QUATRE
zones GND — deux sur F.Cu, deux sur B.Cu — d ou 3 erreurs DRC :

    « Copper zones intersect (intersecting zones must have distinct priorities) »
    severity: error

Aucun re-tirage de placement ne corrige cela : le run rebouclait
PLACEMENT -> ROUTING -> DRC six fois avec 18 violations IDENTIQUES avant
d epuiser ses iterations. Le defaut venait de notre propre coulee.

⚠️ La garde existait et ne s est JAMAIS declenchee :

    re.findall(r'\(zone[^\n]*\(layer "([^"]+)"', text)

`[^\n]*` exige `(zone` et `(layer` sur la MEME ligne. KiCad les ecrit sur des
lignes separees :

    (zone
        (net "GND")
        (layer "F.Cu")

L ensemble des couches deja couvertes ressortait donc toujours VIDE.

Pourquoi invisible en local : notre propre generateur ecrit ses zones sur une
seule ligne, et la fixture `examples/stm32-validation` en heritait. Le defaut
n apparaissait que sur un board reecrit par pcbnew — c est-a-dire tout board
sorti du round-trip Specctra, donc tout board route.

Meme famille que le bug `_NET_DECL_RE` du 2026-08-20 : un motif qui ne connait
qu une seule des deux ecritures valides.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _board(zones: str, net_decl: str = '(net 3 "GND")') -> bytes:
    return (
        "(kicad_pcb\n\t(version 20240108)\n"
        '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)\n'
        '\t\t(44 "Edge.Cuts" user)\n\t)\n'
        f"\t{net_decl}\n"
        '\t(gr_rect (start 0 0) (end 100 80) (layer "Edge.Cuts"))\n'
        f"{zones}\n)"
    ).encode("utf-8")


ZONE_MULTILIGNE = (
    "\t(zone\n"
    '\t\t(net "GND")\n'
    '\t\t(layer "F.Cu")\n'
    "\t\t(hatch edge 0.5)\n"
    "\t)"
)
ZONE_UNE_LIGNE = '\t(zone (net 3 "GND") (layer "B.Cu") (hatch edge 0.5))'


class TestDetectionDesZones:
    def test_une_zone_ecrite_sur_PLUSIEURS_lignes_est_vue(self):
        # Le cas qui a echappe a la garde pendant des semaines.
        assert "F.Cu" in routing_router._couches_deja_couvertes(
            _board(ZONE_MULTILIGNE).decode("utf-8"))

    def test_une_zone_ecrite_sur_UNE_ligne_est_vue(self):
        # Ne pas casser l ancien format en corrigeant le nouveau.
        assert "B.Cu" in routing_router._couches_deja_couvertes(
            _board(ZONE_UNE_LIGNE).decode("utf-8"))

    def test_un_board_sans_zone_ne_rend_rien(self):
        assert routing_router._couches_deja_couvertes(_board("").decode("utf-8")) == set()


class TestCoulee:
    def test_aucun_second_plan_sur_une_couche_deja_couverte(self):
        out = routing_router._add_ground_planes(_board(ZONE_MULTILIGNE)).decode("utf-8")
        # Une seule zone GND sur F.Cu : celle qui existait deja.
        f_cu = [b for b in out.split("(zone") if '(layer "F.Cu")' in b[:200]]
        assert len(f_cu) == 1, f"{len(f_cu)} zones sur F.Cu — plan empile"

    def test_la_face_libre_recoit_bien_son_plan(self):
        # La garde ne doit pas devenir un refus global : B.Cu est libre.
        out = routing_router._add_ground_planes(_board(ZONE_MULTILIGNE)).decode("utf-8")
        assert '(layer "B.Cu")' in out

    def test_deux_faces_deja_couvertes_ne_changent_rien(self):
        deja = ZONE_MULTILIGNE + "\n" + ZONE_UNE_LIGNE
        entree = _board(deja)
        assert routing_router._add_ground_planes(entree) == entree

"""A l escalade, la liberation des pistes protegees autour d une pastille non
reliee EPARGNE les nets confies au plan.

Le routeur ne route jamais ces nets (GND est absent du DSN, « pris en charge par
le plan ») : un troncon de dogbone ou un via de masse libere n est donc jamais
rebati — il est simplement PERDU, et sa broche redevient orpheline du plan.
Mesure du 2026-09-14, carte-10 : « 51 segment(s)/via(s) LIBERE(S) autour de
8 pastille(s) » a chaque palier, puis « Pad 8 [GND] of U1 <-> Via [GND] » au DRC
final — le via reste, le troncon a disparu. Liberer du cuivre que personne ne
reposera ne libere rien : ce n est pas une place rendue au routeur, c est une
connexion jetee.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402

_BOARD = b"""(kicad_pcb (version 20240108) (generator "pcbnew")
  (net 0 "")
  (net 3 "SIG")
  (net 4 "GND")
  (segment (start 10 20) (end 12 20) (width 0.25) (layer "F.Cu") (uuid "a") (net 3))
  (via (at 12 20) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (uuid "b") (net 3))
  (segment (start 10 20.5) (end 11.2 20.5) (width 0.25) (layer "F.Cu") (uuid "c") (net 4))
  (via (at 11.2 20.5) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (uuid "d") (net 4))
  (segment (start 50 50) (end 52 50) (width 0.25) (layer "F.Cu") (uuid "e") (net 3))
  (segment (start 53 50) (end 55 50) (width 0.25) (layer "F.Cu") (uuid "f") (net 3))
  (segment (start 56 50) (end 58 50) (width 0.25) (layer "F.Cu") (uuid "g") (net 3))
  (segment (start 59 50) (end 61 50) (width 0.25) (layer "F.Cu") (uuid "h") (net 3))
  (segment (start 62 50) (end 64 50) (width 0.25) (layer "F.Cu") (uuid "i") (net 3))
  (segment (start 65 50) (end 67 50) (width 0.25) (layer "F.Cu") (uuid "j") (net 3))
  (segment (start 68 50) (end 70 50) (width 0.25) (layer "F.Cu") (uuid "k") (net 3))
  (segment (start 71 50) (end 73 50) (width 0.25) (layer "F.Cu") (uuid "l") (net 3))
)"""


class TestLiberation:
    def test_le_dogbone_gnd_pres_de_la_pastille_reste_protege(self):
        assert "GND" in R._NETS_CONFIES_AU_PLAN
        bloc = R._bloc_wiring_pistes(_BOARD, liberer=[(11.0, 20.5)])
        # Le signal voisin (segment + via) est libere : le routeur y reprend la main.
        assert bloc.count("(net SIG)") == 8                 # les 8 pistes lointaines seulement
        assert bloc.count("(via ") == 1                     # celui de GND ; celui de SIG est libere
        # Le troncon ET le via de masse restent proteges : personne ne les reposerait.
        assert bloc.count("(net GND)") == 2

    def test_sans_liberation_tout_est_protege(self):
        assert R._bloc_wiring_pistes(_BOARD).count("(type protect)") == 12

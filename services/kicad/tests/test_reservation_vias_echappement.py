"""Reserver les vias d echappement AVANT le routage des signaux.

Mesure du 2026-08-23 : apres le routage, l echappement ne pose plus RIEN. 504
candidats essayes autour des pattes orphelines du LQFP-48 — 21 distances x
24 directions, jusqu a 12,7 mm — aucun ne passe, le voisinage comptant alors
182 obstacles (les pistes de signal).

Ce n est donc pas un probleme de reglage mais d ORDRE : il n y a de la place
qu AVANT que les signaux soient routes.

D ou la reservation : on calcule les positions de via sur le board PLACE, ou la
place abonde, on les DECLARE dans le DSN pour que Freerouting route les signaux
autour, et on les repose apres l aller-retour Specctra — qui efface tout ce qui
le precede (17 vias poses avant routage, 4 apres, mesure du 2026-08-21).

⚠️ pcbnew ecrit un bloc `(wiring)` VIDE meme sur un board portant 160 segments.
On l ecrit donc nous-memes — mais seulement pour quelques vias, pas pour tout le
routage.

Unites du DSN, verifiees sur un export reel :
    (resolution um 10) ; les coordonnees sont en MICROMETRES et Y est NEGATIF
    U1 a 118,8265 / 120,4134 mm  ->  (place U1 118826.522 -120413.36 ...)
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


DSN_VIDE = """(pcb board
  (resolution um 10)
  (network
    (net GND
      (pins U1-2)
    )
  )
  (wiring
  )
)"""


class TestBlocWiring:
    def test_une_position_en_nm_devient_des_micrometres(self):
        bloc = routing_router._bloc_wiring([(118_826_522, 120_413_360)], "GND")
        assert "118826.5" in bloc

    def test_l_axe_y_est_inverse(self):
        # Specctra oriente Y vers le haut, KiCad vers le bas. Oublier le signe
        # placerait chaque via en miroir de sa vraie position — un board
        # syntaxiquement valide et geometriquement faux.
        bloc = routing_router._bloc_wiring([(1_000_000, 2_000_000)], "GND")
        assert "-2000.0" in bloc

    def test_le_via_porte_son_net(self):
        bloc = routing_router._bloc_wiring([(0, 0)], "GND")
        assert "(net GND)" in bloc

    def test_le_via_est_protege(self):
        # Sans `protect`, le routeur peut deplacer ou supprimer le via qu on
        # vient de reserver — la reservation ne reserverait rien.
        bloc = routing_router._bloc_wiring([(0, 0)], "GND")
        assert "(type protect)" in bloc

    def test_aucun_via_donne_un_bloc_vide(self):
        assert routing_router._bloc_wiring([], "GND") == ""


class TestInjection:
    def test_le_bloc_remplace_le_wiring_vide(self):
        out = routing_router._injecter_wiring(DSN_VIDE, [(1_000_000, 2_000_000)], "GND")
        assert "(via" in out
        assert out.count("(wiring") == 1, "on ne doit pas empiler deux blocs"

    def test_le_dsn_reste_equilibre(self):
        # Un DSN desequilibre est refuse par Freerouting : on remplacerait un
        # routage imparfait par une absence de routage.
        out = routing_router._injecter_wiring(DSN_VIDE, [(0, 0)], "GND")
        assert out.count("(") == out.count(")")

    def test_le_reste_du_dsn_est_intact(self):
        out = routing_router._injecter_wiring(DSN_VIDE, [(0, 0)], "GND")
        assert "(net GND" in out and "(pins U1-2)" in out
        assert "(resolution um 10)" in out

    def test_sans_via_le_dsn_ne_change_pas(self):
        assert routing_router._injecter_wiring(DSN_VIDE, [], "GND") == DSN_VIDE

    def test_un_dsn_sans_bloc_wiring_est_rendu_tel_quel(self):
        # Ne jamais fabriquer une structure qu on n a pas comprise : mieux vaut
        # un routage sans reservation qu un DSN corrompu.
        sans = "(pcb board\n  (resolution um 10)\n)"
        assert routing_router._injecter_wiring(sans, [(0, 0)], "GND") == sans

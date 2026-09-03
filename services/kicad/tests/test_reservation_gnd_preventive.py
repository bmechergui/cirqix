"""Reserver la sortie des broches GND AVANT le routage, pas apres.

Sequence demandee par l utilisateur :

    ① plan de masse coule
    ② coller les GND qui touchent le plan
    ③ router les GND qui NE touchent PAS le plan   <- AVANT les signaux
    ④ router les signaux
    ⑤ si insuffisant : escalader en gardant cuivre et pistes
    ⑥ jusqu a 100 %
    ⑦ fine-tuning + vias GND a la fin

⚠️ Son etape ③, prise au pied de la lettre, ne trouve RIEN a faire. Mesure du
2026-08-31 : au moment ou l on regarde, sur le board place avec son plan coule,
AUCUNE broche GND n est isolee. Le journal de `stm32-60` ne porte meme pas de
ligne « reservation » — `_vias_a_reserver` rend [] faute de cible.

Les broches GND deviennent orphelines PENDANT le routage : les pistes de signal
decoupent le plan autour d elles. C est un effet du routage, pas un etat
initial.

⚠️ La forme correcte de ③ est donc PREVENTIVE : reserver la sortie des broches
GND des boitiers fine-pitch AVANT de router, qu elles soient deja isolees ou
non — exactement ce qu on fait deja pour les SIGNAUX
(`_vias_signaux_a_reserver`), et exactement la pratique de conception PCB :
on fanoute TOUTES les broches d un BGA avant de router quoi que ce soit.

La mesure soutient ce choix : sur la carte ou la reservation a eu lieu,
« 21 via(s) d echappement places avant routage, 0 renonce(s) ». Avant le
routage, la place existe. Apres, 504 candidats essayes, aucun ne passe.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


_BOARD = b"""(kicad_pcb
  (footprint "QFP"
    (property "Reference" "U1")
""" + b"".join(
    b'    (pad "%d" smd rect (at 0 0) (net %d "SIG%d"))\n' % (i, i, i)
    for i in range(1, 17)
) + b"""    (pad "17" smd rect (at 0 0) (net 90 "GND"))
    (pad "18" smd rect (at 0 0) (net 90 "GND"))
  )
  (footprint "R"
    (property "Reference" "R1")
    (pad "1" smd rect (at 0 0) (net 1 "SIG1"))
    (pad "2" smd rect (at 0 0) (net 90 "GND"))
  )
)"""


class TestSelection:
    def test_les_GND_d_un_boitier_fine_pitch_sont_retenus(self):
        cibles = R._pads_gnd_fine_pitch(_BOARD, {"GND"})
        assert ("U1", "17") in cibles and ("U1", "18") in cibles

    def test_les_signaux_ne_sont_PAS_retenus(self):
        # Ils ont deja leur propre reservation ; les reprendre ici
        # occuperait deux fois les memes sites.
        cibles = R._pads_gnd_fine_pitch(_BOARD, {"GND"})
        assert not [c for c in cibles if c[1] not in ("17", "18")]

    def test_un_boitier_PEU_dense_est_ignore(self):
        """⚠️ R1 a 2 pastilles : le plan l atteint sans peine. Reserver pour
        lui gaspillerait des sites dont les boitiers denses ont besoin."""
        cibles = R._pads_gnd_fine_pitch(_BOARD, {"GND"})
        assert not [c for c in cibles if c[0] == "R1"]

    def test_sans_net_de_plan_il_n_y_a_rien_a_reserver(self):
        assert R._pads_gnd_fine_pitch(_BOARD, set()) == []

    def test_un_board_illisible_ne_LEVE_pas(self):
        # La reservation est un BONUS : sans elle le routage se deroule.
        assert R._pads_gnd_fine_pitch(b"", {"GND"}) == []


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_reservation_preventive_est_APPELEE_avant_le_routage(self):
        corps = self.SOURCE[self.SOURCE.index("def route_auto("):]
        i = corps.index("_vias_gnd_preventifs(")
        j = corps.index("tentative = RouteAutoRequest(")
        assert i < j, "on reserve APRES avoir lance le routage : trop tard"

    def test_elle_journalise_sa_TENTATIVE(self):
        """⚠️ Ne tracer que le succes rend indistinguables « aucune cible » et
        « des cibles mais aucune place » — c est ce qui a masque une premiere
        version inerte du fanout signal pendant une heure de mesure."""
        i = self.SOURCE.index("def _vias_gnd_preventifs(")
        j = self.SOURCE.index(chr(10) + "def ", i + 5)
        assert "logger.info" in self.SOURCE[i:j]

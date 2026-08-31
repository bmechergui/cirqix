"""RELIER les GND non colles au plan, avant le routage — pas seulement reserver.

Sequence demandee par l utilisateur, etape ③ dans sa formulation definitive :

    « lier les GND qui ne sont pas colles au plan de masse, avec une piste
      routee ou avec un via — AVANT le routage des signaux »

⚠️ RESERVER N EST PAS RELIER, et c est la distinction qu il a imposee.
`_vias_gnd_preventifs` calcule une POSITION de via et la declare dans le DSN ;
la broche n est reliee qu apres coup, si la repose aboutit. Rien ne le verifie,
et la garde de repose est TOUT OU RIEN : une seule erreur ajoutee fait perdre
les 21 vias, GND compris.

⚠️ Pourquoi on ne posait pas la liaison directement : l aller-retour Specctra
EFFACE tout ce qui precede — 17 vias poses avant routage, 4 apres (mesure du
2026-08-23). D ou la « reservation ».

Ce n est plus une fatalite depuis l injection de pistes protegees
(`_bloc_wiring_pistes`, validee le 2026-08-31 : 426 fils, 88 % -> 98 %). On
peut donc POSER la liaison, puis la PROTEGER dans le DSN pour qu elle survive.

⚠️ La liaison ne doit JAMAIS degrader : si la poser ajoute des erreurs, on rend
le board recu. Une broche orpheline bloque la commande au DRC ; un
court-circuit peut partir en fabrication.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestFonction:
    def test_elle_existe(self):
        assert callable(R._relier_gnd_avant_routage)

    def test_sans_net_de_plan_le_board_est_INCHANGE(self):
        board = b"(kicad_pcb)"
        assert R._relier_gnd_avant_routage(board, set()) is board

    def test_un_board_sans_boitier_dense_est_INCHANGE(self):
        board = b'(kicad_pcb (footprint "R" (property "Reference" "R1")))'
        assert R._relier_gnd_avant_routage(board, {"GND"}) is board


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def _corps(self) -> str:
        i = self.SOURCE.index("def _relier_gnd_avant_routage(")
        j = self.SOURCE.index(chr(10) + "def ", i + 5)
        return self.SOURCE[i:j]

    def test_elle_POSE_la_liaison_et_ne_la_calcule_pas_seulement(self):
        # `escape_pads` pose piste + via ; `plan_escape` ne fait que calculer.
        assert '"escape_pads"' in self._corps(), (
            "on calcule une position au lieu de poser la liaison")

    def test_elle_ne_peut_pas_DEGRADER(self):
        """⚠️ Une broche orpheline bloque la commande au DRC ; un
        court-circuit peut partir en fabrication. Au moindre doute on rend le
        board recu."""
        corps = self._corps()
        assert "_compte_erreurs" in corps
        i = corps.index("_compte_erreurs")
        assert "return pcb_bytes" in corps[i:i + 700]

    def test_elle_journalise_sa_TENTATIVE(self):
        assert "logger.info" in self._corps()

    def test_elle_est_APPELEE_avant_le_routage(self):
        corps = self.SOURCE[self.SOURCE.index("def route_auto("):]
        i = corps.index("_relier_gnd_avant_routage(")
        j = corps.index("tentative = RouteAutoRequest(")
        assert i < j, "on relie APRES avoir lance le routage : trop tard"

    def test_la_liaison_posee_est_PROTEGEE_dans_le_DSN(self):
        """⚠️ Sans cela, l aller-retour Specctra l efface — 17 vias poses
        avant routage, 4 apres (mesure du 2026-08-23)."""
        corps = self.SOURCE[self.SOURCE.index("def route_auto("):]
        i = corps.index("_relier_gnd_avant_routage(")
        assert "_PISTES_A_PROTEGER" in corps[i:i + 900], (
            "la liaison posee ne survivra pas au round-trip Specctra")


# ⚠️ LA FORME REELLE d un board, relevee le 2026-08-31 sur `nucleo-f401` : la
# propriete `Reference` s etale sur PLUSIEURS LIGNES —
#
#     (property "Reference" "U1"
#         (at 0 -7.4 0)
#         (layer "F.SilkS")
#         ...
#     )
#
# Ma premiere fixture tenait sur une seule ligne, `(property "Reference" "U1")`,
# et la regex exigeait la parenthese fermante. Sur le vrai board elle ne
# reconnaissait AUCUN boitier : zero cible, etape ③ totalement inerte, tests
# verts. Neuvieme piege de format de la session, et toujours le meme
# mecanisme — une fixture dit ce qu on a imagine, un board dit ce qui est.
_BOARD_MULTILIGNE = b'''(kicad_pcb
	(footprint "LQFP-64_10x10mm_P0.5mm"
		(layer "F.Cu")
		(property "Reference" "U1"
			(at 0 -7.4 0)
			(layer "F.SilkS")
		)
		(pad "1" smd rect (at 0 0) (net 1 "SIG1"))
		(pad "2" smd rect (at 0 0) (net 2 "SIG2"))
		(pad "3" smd rect (at 0 0) (net 3 "SIG3"))
		(pad "4" smd rect (at 0 0) (net 4 "SIG4"))
		(pad "5" smd rect (at 0 0) (net 5 "SIG5"))
		(pad "6" smd rect (at 0 0) (net 6 "SIG6"))
		(pad "7" smd rect (at 0 0) (net 7 "SIG7"))
		(pad "8" smd rect (at 0 0) (net 8 "SIG8"))
		(pad "9" smd rect (at 0 0) (net 9 "SIG9"))
		(pad "10" smd rect (at 0 0) (net 10 "SIG10"))
		(pad "11" smd rect (at 0 0) (net 11 "SIG11"))
		(pad "12" smd rect (at 0 0) (net 12 "SIG12"))
		(pad "13" smd rect (at 0 0) (net 13 "SIG13"))
		(pad "14" smd rect (at 0 0) (net 14 "SIG14"))
		(pad "15" smd rect (at 0 0) (net 15 "SIG15"))
		(pad "16" smd rect (at 0 0) (net 16 "SIG16"))
		(pad "17" smd rect (at 0 0) (net 90 "GND"))
	)
)'''


class TestFormeReelleDuBoard:
    def test_la_reference_MULTILIGNE_est_reconnue(self):
        cibles = R._pads_gnd_fine_pitch(_BOARD_MULTILIGNE, {"GND"})
        assert cibles == [("U1", "17")], (
            "la reference sur plusieurs lignes n est pas reconnue : "
            "l etape 3 serait inerte sur un vrai board")

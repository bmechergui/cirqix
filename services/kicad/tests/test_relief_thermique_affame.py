"""Une pastille que le relief thermique ne tient que par UN pont passe en plein.

⚠️ Mesure du 2026-09-01, `nucleo-f401`, board `18_cousu` du pipeline reel, apres
l elimination des vias superposes. Ventilation face au board place :

    holes_co_located     116 -> 0     (corrige)
    silk_over_copper      44 -> 44    (vient du placement)
    silk_overlap          27 -> 27    (vient du placement)
    starved_thermal        0 -> 4     <- LES SEULES ERREURS RESTANTES

Le rapport les nomme sans ambiguite :

    Thermal relief connection to zone incomplete
    (layer F.Cu; zone min spoke count 2; actual 1)
    Pad 2 [GND] of D1  ·  D15  ·  D14  ·  D13

KiCad exige au moins DEUX ponts thermiques ; ces quatre pastilles n en
obtiennent qu un. La pastille est reliee, mais par un seul pont — fragile
mecaniquement, et le DRC a raison de refuser.

⚠️ PASSER TOUT LE PLAN EN CONNEXION PLEINE EST EXCLU. L utilisateur a tranche
le 2026-09-01, capture a l appui : le plan garde le relief thermique de KiCad,
comme dans `stm32-validation`. La decision est inscrite dans le commentaire de
`(connect_pads (clearance 0.25))`. On ne l annule pas pour faire taire un DRC.
Un plan entierement plein poserait d ailleurs un vrai probleme de refusion :
un 0402 noye dans le cuivre chauffe de facon inegale et se dresse sur une patte.

On promeut donc en connexion PLEINE les SEULES pastilles mesurees comme
affamees — `(zone_connect 2)` sur elles, rien ailleurs. C est une regle
generale : elle se mesure sur chaque board, elle ne recolle aucune carte a la
main.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


_RAPPORT = {
    "violations": [
        {
            "type": "starved_thermal",
            "severity": "error",
            "description": "Thermal relief connection to zone incomplete "
                           "(layer F.Cu; zone min spoke count 2; actual 1)",
            "items": [
                {"description": "Zone [GND] on F.Cu, priority 1"},
                {"description": "Pad 2 [GND] of D1 on F.Cu"},
            ],
        },
        {
            "type": "starved_thermal",
            "severity": "error",
            "description": "Thermal relief connection to zone incomplete",
            "items": [
                {"description": "Zone [GND] on F.Cu, priority 1"},
                {"description": "Pad 2 [GND] of D15 on F.Cu"},
            ],
        },
        {
            "type": "silk_overlap",
            "severity": "warning",
            "items": [{"description": "Pad 1 [VCC] of U9 on F.Cu"}],
        },
    ]
}


class TestLecture:
    def test_elle_nomme_les_pastilles_affamees(self):
        assert R._pastilles_affamees(_RAPPORT) == [("D1", "2"), ("D15", "2")]

    def test_elle_ignore_les_autres_violations(self):
        # ⚠️ `silk_overlap` cite AUSSI une pastille. Ne retenir que le type.
        assert ("U9", "1") not in R._pastilles_affamees(_RAPPORT)

    def test_un_rapport_vide_ne_nomme_personne(self):
        assert R._pastilles_affamees({}) == []

    def test_un_rapport_sans_violations_ne_nomme_personne(self):
        assert R._pastilles_affamees({"violations": []}) == []


_BOARD = """(kicad_pcb
  (footprint "LED_0603" (at 10 10)
    (property "Reference" "D1")
    (pad "1" smd roundrect (at -0.8 0) (size 0.9 0.95) (layers "F.Cu") (net 4 "LED1"))
    (pad "2" smd roundrect (at 0.8 0) (size 0.9 0.95) (layers "F.Cu") (net 1 "GND"))
  )
  (footprint "LED_0603" (at 20 10)
    (property "Reference" "D2")
    (pad "2" smd roundrect (at 0.8 0) (size 0.9 0.95) (layers "F.Cu") (net 1 "GND"))
  )
)
"""


class TestPromotion:
    def test_elle_pose_la_connexion_pleine_sur_la_bonne_pastille(self):
        out = R._connexion_pleine(_BOARD.encode(), [("D1", "2")]).decode()
        d1 = out[out.index('"D1"'):out.index('"D2"')]
        pad2 = d1[d1.index('(pad "2"'):]
        assert "(zone_connect 2)" in pad2

    def test_elle_ne_touche_PAS_les_autres_pastilles(self):
        out = R._connexion_pleine(_BOARD.encode(), [("D1", "2")]).decode()
        assert out.count("(zone_connect 2)") == 1, (
            "la promotion a deborde sur d autres pastilles")
        # La pastille 1 de D1 et la pastille 2 de D2 restent en relief.
        d1 = out[out.index('"D1"'):out.index('"D2"')]
        assert "(zone_connect" not in d1[d1.index('(pad "1"'):d1.index('(pad "2"')]

    def test_elle_traite_plusieurs_pastilles(self):
        out = R._connexion_pleine(_BOARD.encode(), [("D1", "2"), ("D2", "2")]).decode()
        assert out.count("(zone_connect 2)") == 2

    def test_sans_pastille_le_board_est_rendu_INTACT(self):
        # ⚠️ Un no-op doit etre un vrai no-op : re-ecrire le fichier pour rien
        # est une occasion de le corrompre.
        assert R._connexion_pleine(_BOARD.encode(), []) == _BOARD.encode()

    def test_une_pastille_absente_ne_casse_rien(self):
        out = R._connexion_pleine(_BOARD.encode(), [("D99", "2")])
        assert out == _BOARD.encode()

    def test_une_pastille_deja_pleine_n_est_pas_doublee(self):
        deja = _BOARD.replace(
            '(pad "2" smd roundrect (at 0.8 0) (size 0.9 0.95) (layers "F.Cu") '
            '(net 1 "GND"))',
            '(pad "2" smd roundrect (at 0.8 0) (size 0.9 0.95) (layers "F.Cu") '
            '(net 1 "GND") (zone_connect 2))', 1)
        out = R._connexion_pleine(deja.encode(), [("D1", "2")]).decode()
        assert out.count("(zone_connect 2)") == 1

    def test_le_board_reste_equilibre(self):
        out = R._connexion_pleine(_BOARD.encode(), [("D1", "2")]).decode()
        assert out.count("(") == out.count(")")


class TestReparation:
    """La regle doit AMELIORER, sinon le board d origine est conserve."""

    def _sans_kicad_cli(self, monkeypatch, rapports, rempli=b"(rempli)"):
        suite = list(rapports)
        monkeypatch.setattr(R, "_rapport_drc", lambda b: suite.pop(0))
        monkeypatch.setattr(R, "_fill_zones", lambda b: rempli)

    def test_sans_pastille_affamee_le_board_est_rendu_tel_quel(self, monkeypatch):
        self._sans_kicad_cli(monkeypatch, [{"violations": []}])
        assert R._reparer_reliefs_affames(_BOARD.encode()) == _BOARD.encode()

    def test_une_promotion_qui_AMELIORE_est_retenue(self, monkeypatch):
        apres = {"violations": []}
        self._sans_kicad_cli(monkeypatch, [_RAPPORT, apres])
        assert R._reparer_reliefs_affames(_BOARD.encode()) == b"(rempli)"

    def test_une_promotion_qui_N_AMELIORE_PAS_est_refusee(self, monkeypatch):
        # ⚠️ Meme nombre d erreurs : on garde l existant. Promouvoir change le
        # remplissage autour de la pastille — rien ne garantit un gain.
        self._sans_kicad_cli(monkeypatch, [_RAPPORT, _RAPPORT])
        assert R._reparer_reliefs_affames(_BOARD.encode()) == _BOARD.encode()


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_reparation_est_REELLEMENT_appelee(self):
        # ⚠️ Une regle correcte jamais invoquee est indistinguable d une regle
        # absente — c est ce qui a masque des semaines que le Geometre ne
        # tournait jamais en production.
        appels = self.SOURCE.count("_reparer_reliefs_affames(")
        assert appels >= 2, (
            "definie mais jamais appelee (%d occurrence(s))" % appels)

    def test_elle_est_appelee_AVANT_l_encodage_du_board_rendu(self):
        i = self.SOURCE.rindex("_reparer_reliefs_affames(final)")
        j = self.SOURCE.index("res.kicad_pcb_b64 = base64.b64encode(final)", i)
        assert j > i, "la reparation arrive apres que le board a ete rendu"

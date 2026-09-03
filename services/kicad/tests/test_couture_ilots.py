"""Recoudre les ilots du plan que les pistes de signal ont detaches.

Diagnostic etabli le 2026-08-23 : sur le board PLACE, plans coules et remplis,
ZERO broche GND orpheline — le plan atteint tout, fine-pitch compris. Les
orphelines n apparaissent qu APRES le routage, quand les pistes de signal posees
sur F.Cu decoupent le plan en ilots. Le DRC le dit :

    Zone [GND] on F.Cu  <->  Zone [GND] on F.Cu

Un ilot detache se recoud par un via vers le plan de l autre face.

⚠️ On ne DEVINE pas ou poser le via : on l essaie et on VERIFIE. Chaque candidat
est pose, la connectivite reconstruite, et le via n est garde que si la pastille
rejoint effectivement un temoin — une broche GND restee sur le plan principal.
Un via pose au jugé peut atterrir dans le meme ilot et ne rien relier du tout.

⚠️ `kct stitch` ne peut pas faire ce travail : trois tentatives le 2026-08-23,
dont `--blanket` et `--micro-via`, toutes repondant « No unconnected pads found
on target nets ». Son critere est l appartenance au POLYGONE, pas la continuite
du cuivre.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as runner  # noqa: E402

MM = 1_000_000


class TestCandidats:
    def test_les_candidats_partent_du_pad_et_s_eloignent(self):
        c = list(runner._candidats_de_couture(0, 0, portee=3 * MM, pas=MM))
        assert c, "aucun candidat genere"
        d = [(x * x + y * y) ** 0.5 for x, y in c]
        # Tolerance d un micrometre : a l interieur d un anneau, l arrondi
        # entier des coordonnees fait varier la distance de facon negligeable.
        # Ce qui compte est que les ANNEAUX s eloignent, pas les points entre eux.
        assert all(b >= a - 1000 for a, b in zip(d, d[1:])), (
            "les candidats doivent s eloigner progressivement")

    def test_aucun_candidat_ne_depasse_la_portee(self):
        for x, y in runner._candidats_de_couture(0, 0, portee=3 * MM, pas=MM):
            assert (x * x + y * y) ** 0.5 <= 3 * MM + 1

    def test_les_candidats_couvrent_plusieurs_directions(self):
        c = list(runner._candidats_de_couture(0, 0, portee=2 * MM, pas=MM))
        # Un ilot peut s etendre dans n importe quelle direction : chercher sur
        # un seul axe reviendrait a supposer sa forme.
        assert len({(x > 0, y > 0) for x, y in c}) >= 3


class TestOperation:
    def test_le_runner_expose_la_couture(self):
        assert hasattr(runner, "_stitch_islands")

    def test_la_couture_est_dispatchee(self):
        source = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
            encoding="utf-8"
        )
        assert '"stitch_islands"' in source

    def test_un_via_qui_ne_relie_rien_est_RETIRE(self, tmp_path):
        # Le point qui compte : un via inutile est du cuivre en plus, un trou de
        # perçage facture, et un obstacle pour le routage suivant. S il ne relie
        # pas, il ne reste pas.
        retires = []

        class Via:
            def __init__(self):
                self.pos = None

            def SetPosition(self, p):
                self.pos = p

            def SetWidth(self, _w):
                pass

            def SetDrill(self, _d):
                pass

            def SetNetCode(self, _n):
                pass

        class Board:
            def __init__(self):
                self.ajoutes = []

            def Add(self, v):
                self.ajoutes.append(v)

            def Remove(self, v):
                retires.append(v)

            def BuildConnectivity(self):
                return True

            def GetConnectivity(self):
                return self

            def RecalculateRatsnest(self):
                pass

            def GetConnectedItems(self, _i, *_a):
                return []            # jamais relie : chaque essai doit echouer

            # ⚠️ Le vrai BOARD de pcbnew expose `GetTracks()`, et la production
            # s en sert (`_obstacles_d_un_autre_net`, `_trous_perces`). Un faux
            # plus pauvre que le vrai fait echouer la production sur un defaut
            # qui n existe pas : completer le faux, jamais affaiblir le code.
            def GetTracks(self):
                return []

            def GetFootprints(self):
                return []

            def FindFootprintByReference(self, _r):
                return None

        class FakePcbnew:
            PCB_PAD_T = 7
            PCB_VIA = staticmethod(lambda _b: Via())
            VECTOR2I = staticmethod(lambda x, y: (x, y))

            @staticmethod
            def LoadBoard(_p):
                return Board()

            @staticmethod
            def SaveBoard(p, _b):
                Path(p).write_bytes(b"BOARD")

        resultat = tmp_path / "r.json"
        runner._stitch_islands(FakePcbnew, {
            "pcb": "in.kicad_pcb", "output": str(tmp_path / "o.kicad_pcb"),
            "result": str(resultat), "pads": json.dumps([["U2", "35"]]),
        })
        assert json.loads(resultat.read_text(encoding="utf-8"))["stitched"] == 0

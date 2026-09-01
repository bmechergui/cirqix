"""Un via ne se perce JAMAIS dans un trou deja perce — meme sur son propre net.

⚠️ Mesure du 2026-09-01, board `99_final` de `nucleo-f401`, livre a 1 connexion
manquante et ZERO erreur DRC — mais 187 avertissements, dont 116 que le board
place ne portait pas :

    silk_over_copper     44   deja dans le temoin place    +0   cosmetique
    silk_overlap         27   deja dans le temoin place    +0   cosmetique
    holes_co_located    116   absent du temoin           +116   DE NOTRE FAIT

Comptage des vias de ce meme board :

    131 vias poses  ·  94 positions distinctes  ·  37 vias EN TROP
    7 positions portent exactement x5 vias      <- les 5 passes de couture
    1 position en porte x10                     <- liaison GND + couture
    tous sur GND

CAUSE. `_stitch_zones` demande ses obstacles a `_obstacles_d_un_autre_net`, qui
ecarte VOLONTAIREMENT tout objet du net courant. C est juste pour du CUIVRE —
deux pistes GND peuvent se toucher sans court-circuit. C est faux pour un
PERCAGE : deux trous au meme point sont physiquement impossibles, quel que soit
le net. Le via pose a la passe 1 n etait donc pas un obstacle a la passe 2, qui
retrouvait le meme ilot, le meme meilleur point, et repercait au meme endroit.

Cinq passes, cinq vias empiles dans le meme trou. Pour un fabricant ce n est pas
une coquetterie : c est un percage impossible.

⚠️ La regle est GEOMETRIQUE, pas comptable : on ne compte pas les passes, on
refuse un point trop pres d un trou existant. Elle vaut donc aussi pour deux
vias d une meme passe, et pour un via pose pres d une pastille traversante.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as RUN  # noqa: E402

MM = 1_000_000


class TestRegleGeometrique:
    def test_un_point_libre_est_accepte(self):
        trous = [(0.0, 0.0, 0.15 * MM)]
        assert RUN._trou_libre(10 * MM, 10 * MM, 0.15 * MM, trous, 0.5 * MM)

    def test_le_MEME_point_est_refuse(self):
        # Le cas mesure : x5 et x10 vias a la position identique.
        trous = [(5.0 * MM, 5.0 * MM, 0.15 * MM)]
        assert not RUN._trou_libre(5 * MM, 5 * MM, 0.15 * MM, trous, 0.5 * MM)

    def test_un_point_trop_proche_est_refuse(self):
        # Rayons 0,15 + 0,15 = 0,30 ; il faut 0,5 d ecart bord a bord, donc
        # tout centre a moins de 0,80 mm est refuse.
        trous = [(0.0, 0.0, 0.15 * MM)]
        assert not RUN._trou_libre(0.7 * MM, 0.0, 0.15 * MM, trous, 0.5 * MM)

    def test_juste_au_dela_de_l_ecart_c_est_bon(self):
        trous = [(0.0, 0.0, 0.15 * MM)]
        assert RUN._trou_libre(0.9 * MM, 0.0, 0.15 * MM, trous, 0.5 * MM)

    def test_sans_aucun_trou_tout_est_libre(self):
        assert RUN._trou_libre(0.0, 0.0, 0.15 * MM, [], 0.5 * MM)


class _FauxPoly:
    def __init__(self, n):
        self._n = n

    def OutlineCount(self):
        return self._n

    def Outline(self, i):
        class _O:
            def BBox(self_):
                class _B:
                    GetLeft = staticmethod(lambda: 0)
                    GetTop = staticmethod(lambda: 0)
                    GetRight = staticmethod(lambda: 20 * MM)
                    GetBottom = staticmethod(lambda: 20 * MM)
                return _B()
        return _O()

    def Contains(self, pt, i):
        return True


class _FausseZone:
    def __init__(self, couche, ilots, net=1, nom="GND"):
        self._c, self._ilots, self._net, self._nom = couche, ilots, net, nom

    def GetNetname(self):
        return self._nom

    def GetNetCode(self):
        return self._net

    def GetLayerSet(self):
        class _S:
            def __init__(self, c):
                self._c = c

            def Seq(self):
                return [self._c]
        return _S(self._c)

    def GetFilledPolysList(self, c):
        return _FauxPoly(self._ilots if c == self._c else 0)


class _Point:
    def __init__(self, x, y):
        self.x, self.y = x, y


class _ViaExistant:
    """Un via DEJA sur le board, sur le MEME net que le plan qu on recoud."""

    def __init__(self, x, y, net=1, perc=0.3 * MM):
        self._x, self._y, self._net, self._p = x, y, net, perc

    def GetNetCode(self):
        return self._net

    def GetPosition(self):
        return _Point(self._x, self._y)

    def GetDrillValue(self):
        return self._p

    def GetBoundingBox(self):
        moi = self

        class _B:
            GetLeft = staticmethod(lambda: moi._x - moi._p)
            GetTop = staticmethod(lambda: moi._y - moi._p)
            GetRight = staticmethod(lambda: moi._x + moi._p)
            GetBottom = staticmethod(lambda: moi._y + moi._p)
        return _B()


class _FauxBoard:
    def __init__(self, zones, tracks=()):
        self._z, self._t, self.ajoutes = zones, list(tracks), []

    def Zones(self):
        return self._z

    def GetTracks(self):
        return list(self._t)

    def GetFootprints(self):
        return []

    def Footprints(self):
        return []

    def Add(self, item):
        self.ajoutes.append(item)
        self._t.append(item)


def _faux_pcbnew(board):
    class _FauxVia:
        def __init__(self, b):
            self.xy = None
            self.net = None
            self.perc = 0.3 * MM

        def SetPosition(self, p):
            self.xy = p

        def SetWidth(self, w):
            pass

        def SetDrill(self, d):
            self.perc = d

        def SetNetCode(self, n):
            self.net = n

        # ⚠️ Le via qu on vient de poser doit se comporter comme un via DEJA
        # pose : sinon la passe suivante ne peut pas le voir.
        def GetNetCode(self):
            return self.net if self.net is not None else 1

        def GetPosition(self):
            return _Point(*(self.xy or (0, 0)))

        def GetDrillValue(self):
            return self.perc

        def GetBoundingBox(self):
            class _B:
                GetLeft = staticmethod(lambda: 0)
                GetTop = staticmethod(lambda: 0)
                GetRight = staticmethod(lambda: 0)
                GetBottom = staticmethod(lambda: 0)
            return _B()

    class _FauxPcbnew:
        PCB_VIA = _FauxVia
        VECTOR2I = staticmethod(lambda x, y: (x, y))
        SaveBoard = staticmethod(
            lambda c, b: Path(c).write_text("(kicad_pcb)", encoding="utf-8"))

    return _FauxPcbnew


class TestExecutionReelle:
    """EXERCER la couture, pas seulement lire son source."""

    def _coudre(self, board, tmp_path, monkeypatch):
        faux = _faux_pcbnew(board)
        monkeypatch.setattr(RUN, "_charger_board", lambda p, c: board)
        monkeypatch.setattr(RUN, "_obstacles_d_un_autre_net", lambda b, n: [])
        res = tmp_path / "r.json"
        RUN._stitch_zones(faux, {
            "pcb": str(tmp_path / "in.kicad_pcb"),
            "output": str(tmp_path / "out.kicad_pcb"),
            "result": str(res),
            "nets": json.dumps(["GND"]),
        })
        return json.loads(res.read_text(encoding="utf-8"))

    def test_elle_coud_encore_quand_la_place_est_libre(self, tmp_path, monkeypatch):
        # Garde anti-regression : la correction ne doit pas eteindre la couture.
        board = _FauxBoard([_FausseZone(0, 3), _FausseZone(31, 1)])
        r = self._coudre(board, tmp_path, monkeypatch)
        assert r["stitched"] >= 3
        assert len(board.ajoutes) >= 3

    def test_elle_ne_reperce_PAS_dans_un_trou_existant(self, tmp_path, monkeypatch):
        # LE CAS MESURE. Le premier point que la couture essaie est le CENTRE
        # de la boite, (10, 10). On y met deja un via, sur le MEME net.
        deja = _ViaExistant(10 * MM, 10 * MM, net=1)
        board = _FauxBoard([_FausseZone(0, 1), _FausseZone(31, 1)], tracks=[deja])
        self._coudre(board, tmp_path, monkeypatch)
        for v in board.ajoutes:
            assert v.xy != (10 * MM, 10 * MM), (
                "un via a ete perce dans un trou deja perce")

    def test_deux_passes_ne_donnent_pas_deux_trous_au_meme_point(
            self, tmp_path, monkeypatch):
        # ⚠️ La reproduction exacte des x5 : on coud DEUX fois le meme board,
        # la seconde passe voyant les vias de la premiere.
        board = _FauxBoard([_FausseZone(0, 1), _FausseZone(31, 1)])
        self._coudre(board, tmp_path, monkeypatch)
        self._coudre(board, tmp_path, monkeypatch)
        pts = [v.xy for v in board.ajoutes if v.xy]
        assert len(pts) == len(set(pts)), (
            "deux passes ont perce au meme endroit : %s" % (pts,))

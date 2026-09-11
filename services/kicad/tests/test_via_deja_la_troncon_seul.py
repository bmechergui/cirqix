"""Un via du MEME net deja au point de chute n est pas un obstacle : on ne
repose que le troncon.

Mesure du 2026-09-11 (carte-08, board trace `/tmp/traces-routage`) : autour
de CHAQUE broche GND du LQFP (U1.8, .23, .35, .47), le via reserve etait la,
a 1,20 mm — le routeur l avait conserve — et aucune piste ne le reliait a la
pastille. A la repose, `_trou_libre` voyait ce via comme un trou occupe et
renoncait : « fanout: 0 sortie(s), 0 position(s) rejouee(s), 8 RENONCEE(S) ».
La pastille restait orpheline A CAUSE du via qui devait la relier.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import routing_pcbnew_runner as RUN  # noqa: E402
from routers import routing as R  # noqa: E402


class TestViaExistant:
    VIAS = [(1_000_000.0, 2_000_000.0, 1), (5_000_000.0, 5_000_000.0, 3)]

    def test_meme_net_meme_position(self):
        assert RUN._via_existant_a(self.VIAS, 1_000_000, 2_000_000, 1)

    def test_a_50_um_pres(self):
        assert RUN._via_existant_a(self.VIAS, 1_040_000, 2_000_000, 1)
        assert not RUN._via_existant_a(self.VIAS, 1_060_000, 2_000_000, 1)

    def test_un_autre_net_ne_compte_pas(self):
        assert not RUN._via_existant_a(self.VIAS, 1_000_000, 2_000_000, 2)

    def test_sans_via_rien(self):
        assert not RUN._via_existant_a([], 1_000_000, 2_000_000, 1)


class TestCablage:
    SRC = (_SERVICE / "tools" / "routing_pcbnew_runner.py").read_text(encoding="utf-8")

    def _corps(self):
        i = self.SRC.index("def _escape_pads(")
        return self.SRC[i:self.SRC.index(chr(10) + "def ", i + 1)]

    def test_le_via_existant_dispense_du_trou_libre(self):
        corps = self._corps()
        assert "existant = _via_existant_a(vias_existants, vx, vy, pad.GetNetCode())" in corps
        assert "if not existant and not _trou_libre(" in corps

    def test_le_troncon_est_pose_meme_quand_le_via_existe(self):
        corps = self._corps()
        i_e = corps.index("if not existant and not _trou_libre(")
        i_p = corps.index("piste = pcbnew.PCB_TRACK(board)", i_e)
        i_v = corps.index("if existant:", i_p)
        assert i_e < i_p < i_v

    def test_les_troncons_seuls_sont_comptes_et_journalises(self):
        assert '"troncons_seuls"' in self._corps()
        import inspect
        assert "troncons_seuls" in inspect.getsource(R._reposer_vias_reserves)

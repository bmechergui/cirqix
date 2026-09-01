"""L etape ③ ne doit jamais rendre un board APPAUVRI en nets.

⚠️ Regression du 2026-09-01, `esp32-baseline`, deux symptomes NOUVEAUX apparus
ensemble sur la carte ou l etape ③ s executait pour la premiere fois — zero
occurrence de l un comme de l autre dans le temoin :

    Freerouting échoué (pcbnew child exit -11 : PROPERTY_ENUM()
                        No enum choices defined)          <- import Specctra
    ValueError: Net 'GND' not found in PCB                <- repli kicad-tools

Le second est le plus parlant : le board remis a kicad-tools ne declare plus
`GND`. Or `_confier_au_plan` retire GND du DSN, jamais du BOARD. La seule
etape qui fasse REECRIRE le fichier par pcbnew avant le routage est
`_relier_gnd_avant_routage`, via `escape_pads` et son `SaveBoard`.

⚠️ Ce test ne prouve PAS que la reecriture est la cause — la mesure qui
trancherait exige le conteneur. Il pose la garde qui manquait : l etape ③ ne
peut plus, quoi qu il arrive, remettre a la suite de la chaine un board qui
declare moins de nets que celui qu elle a recu. C est la doctrine deja
appliquee partout ailleurs — « ne peut qu ameliorer » — etendue de la qualite
du routage a l INTEGRITE du fichier.

Un board ampute de ses nets ne provoque pas un echec franc : il provoque un
plantage lointain et un message qui accuse une autre etape. C est exactement ce
qui vient de se passer.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


def _board(nets: tuple) -> bytes:
    lignes = ["(kicad_pcb"]
    lignes += ['  (net %d "%s")' % (i, n) for i, n in enumerate(nets)]
    lignes.append(")")
    return ("\n".join(lignes)).encode("utf-8")


class TestLectureDesNets:
    def test_les_nets_du_board_sont_lus(self):
        assert R._nets_du_board(_board(("", "GND", "VCC"))) == {"", "GND", "VCC"}

    def test_un_board_vide_ne_declare_rien(self):
        assert R._nets_du_board(b"") == set()


class TestLesDeuxFormesDeKiCad:
    """⚠️ La garde ne doit pas devenir un no-op sur un board de KiCad 10.

    Deux ecritures coexistent pour la meme information :

        (net 3 "GND")   kicad-tools, et KiCad <= 9
        (net "GND")     pcbnew de KiCad 10 — donc tout board sorti du
                        round-trip Specctra

    Mesure du 2026-09-01 sur un board REEL du depot
    (`examples/stm32-validation/output/freerouting/…`, sorti de Freerouting) :
    la lecture numerotee seule y compte **ZERO net**. La garde
    « le board ne doit pas perdre de net » y comparait donc l ensemble vide a
    l ensemble vide et ne gardait plus rien — silencieusement.

    C est le meme piege que celui documente dans CLAUDE.md pour
    `_NET_DECL_RE` le 2026-08-20, reproduit a l identique. On accepte les deux
    formes.
    """

    def test_la_forme_numerotee_est_lue(self):
        assert R._nets_du_board(b'(net 3 "GND")') == {"GND"}

    def test_la_forme_NOMMEE_de_kicad_10_est_lue(self):
        assert R._nets_du_board(b'(net "GND")') == {"GND"}

    def test_les_deux_formes_se_melangent_sans_doublon(self):
        board = b'(kicad_pcb (net 3 "GND") (pad (net "GND")) (net "VCC"))'
        assert R._nets_du_board(board) == {"GND", "VCC"}

    def test_un_board_REEL_de_kicad_10_declare_bien_ses_nets(self):
        chemin = (_SERVICE_ROOT / "examples" / "stm32-validation" / "output"
                  / "freerouting" / "stm32_routage_2026-08-26.kicad_pcb")
        if not chemin.is_file():
            import pytest
            pytest.skip("board d inspection absent (output/ est gitignore)")
        nets = R._nets_du_board(chemin.read_bytes())
        assert "GND" in nets
        assert len(nets) > 5, "la garde retomberait a un ensemble quasi vide"


class TestGarde:
    def _cibler(self, monkeypatch, sortie_pcbnew: bytes):
        monkeypatch.setattr(R, "_pads_gnd_fine_pitch",
                            lambda pcb, nets: [("U1", "8")])
        monkeypatch.setattr(R, "_rapport_drc", lambda pcb: {})
        monkeypatch.setattr(R, "_compte_erreurs", lambda rapport: 0)
        monkeypatch.setattr(R, "_fill_zones", lambda board: board)

        def faux_pcbnew(args):
            Path(args["output"]).write_bytes(sortie_pcbnew)
            Path(args["result"]).write_text('{"escaped": 1, "renonces": 0}')

        monkeypatch.setattr(R, "_run_pcbnew_operation", faux_pcbnew)

    def test_un_board_ampute_de_ses_nets_est_REFUSE(self, monkeypatch):
        recu = _board(("", "GND", "VCC", "SDA"))
        self._cibler(monkeypatch, _board(("", "VCC")))  # GND et SDA perdus
        assert R._relier_gnd_avant_routage(recu, {"GND"}) is recu

    def test_un_board_intact_est_ACCEPTE(self, monkeypatch):
        recu = _board(("", "GND", "VCC"))
        pose = _board(("", "GND", "VCC")) + b"\n; piste posee"
        self._cibler(monkeypatch, pose)
        assert R._relier_gnd_avant_routage(recu, {"GND"}) == pose

    def test_un_board_ENRICHI_est_accepte(self, monkeypatch):
        # Poser du cuivre peut faire apparaitre un net ; seule la PERTE compte.
        recu = _board(("", "GND"))
        pose = _board(("", "GND", "Net-(U1-8)"))
        self._cibler(monkeypatch, pose)
        assert R._relier_gnd_avant_routage(recu, {"GND"}) == pose

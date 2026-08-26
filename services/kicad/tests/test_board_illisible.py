"""Un board que pcbnew ne sait pas lire doit le DIRE, et se laisser examiner.

Mesure du 2026-08-26, banc des cinq cartes. L ESP32 rendait 19 connexions
manquantes et 5 erreurs la ou les quatre autres etaient propres. Le journal
donnait ceci :

    AttributeError: 'NoneType' object has no attribute 'GetTracks'
      routing_pcbnew_runner.py:19, dans _export_specctra
    -> Freerouting echoue — repli kicad-tools

`pcbnew.LoadBoard()` rend `None` — pas une exception, `None` — et la ligne
suivante l utilise. L erreur remonte donc sous forme d `AttributeError` opaque,
a trois niveaux du vrai probleme : le board n a pas pu etre charge.

⚠️ Le cout n est pas cosmetique. Freerouting n est jamais appele, la cascade
retombe sur kicad-tools — dont le banc du 2026-08-21 a mesure 7 connexions
manquantes et 58 erreurs de fabricabilite la ou Freerouting en produit zero.
C est de la que viennent les 19 manquantes de l ESP32.

Et le board fautif etait perdu : impossible de savoir lequel, ni pourquoi. On le
conserve desormais, comme le fait deja `POST /erc` pour les schemas illisibles.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as runner  # noqa: E402


class _PcbnewMuet:
    """`LoadBoard` qui rend None — le comportement reel observe."""

    @staticmethod
    def LoadBoard(_p):
        return None


class TestChargement:
    def test_un_board_illisible_leve_un_message_EXPLICITE(self, tmp_path):
        f = tmp_path / "b.kicad_pcb"
        f.write_bytes(b"(kicad_pcb)")
        with pytest.raises(RuntimeError) as e:
            runner._charger_board(_PcbnewMuet, str(f))
        message = str(e.value)
        assert "pcbnew" in message.lower()
        assert str(f) in message, "le message doit nommer le fichier fautif"

    def test_le_board_fautif_est_CONSERVE(self, tmp_path, monkeypatch):
        garde = tmp_path / "garde"
        monkeypatch.setattr(runner, "_DOSSIER_ILLISIBLES", garde)
        f = tmp_path / "b.kicad_pcb"
        f.write_bytes(b"(kicad_pcb illisible)")
        with pytest.raises(RuntimeError):
            runner._charger_board(_PcbnewMuet, str(f))
        copies = list(garde.glob("*.kicad_pcb")) if garde.is_dir() else []
        assert copies, "aucune copie conservee — le board fautif est perdu"
        assert copies[0].read_bytes() == b"(kicad_pcb illisible)"

    def test_un_board_lisible_passe_sans_copie(self, tmp_path, monkeypatch):
        garde = tmp_path / "garde"
        monkeypatch.setattr(runner, "_DOSSIER_ILLISIBLES", garde)

        class Ok:
            @staticmethod
            def LoadBoard(_p):
                return "BOARD"

        f = tmp_path / "b.kicad_pcb"
        f.write_bytes(b"(kicad_pcb)")
        assert runner._charger_board(Ok, str(f)) == "BOARD"
        assert not garde.exists(), "on ne conserve que les ECHECS"


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8"
    )

    def test_aucun_LoadBoard_direct_ne_subsiste_HORS_du_chargeur(self):
        # Chaque appel direct est un endroit ou `None` repartira en silence.
        # Celui de `_charger_board` est le seul legitime : c est lui qui verifie.
        avant = self.SOURCE[: self.SOURCE.index("def _charger_board(")]
        apres = self.SOURCE[self.SOURCE.index("def _charger_board(") :]
        corps = apres[: apres.index(chr(10) + "def ")]
        reste = apres[apres.index(chr(10) + "def ") :]
        assert corps.count("pcbnew.LoadBoard(") == 1, "le chargeur doit appeler LoadBoard une fois"
        directs = avant.count("pcbnew.LoadBoard(") + reste.count("pcbnew.LoadBoard(")
        assert directs == 0, f"{directs} appel(s) direct(s) hors du chargeur"

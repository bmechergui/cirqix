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
        # Deux appels : l essai, puis la relance apres reparation du keepout.
        # Plus de deux signalerait une boucle de reessai non bornee.
        assert corps.count("pcbnew.LoadBoard(") == 2, (
            "le chargeur essaie une fois, repare, et reessaie une fois")
        directs = avant.count("pcbnew.LoadBoard(") + reste.count("pcbnew.LoadBoard(")
        assert directs == 0, f"{directs} appel(s) direct(s) hors du chargeur"


class TestReparationAuChargement:
    """Le chargeur REPARE avant de renoncer.

    Mesure du 2026-08-26 : corriger le seul `_export_specctra` laissait encore
    TROIS boards illisibles par tirage — `_fill_zones`, l API Freerouting et son
    repli chargent chacun leur board. SIX operations passent par `LoadBoard`.

    La reparation vit donc dans le chargeur, seul point de passage commun.
    """

    def test_un_keepout_guillemete_est_repare_et_charge(self, tmp_path):
        appels = {"n": 0}

        class Pcbnew:
            @staticmethod
            def LoadBoard(chemin):
                appels["n"] += 1
                texte = Path(chemin).read_text(encoding="utf-8")
                # Le vrai pcbnew refuse les valeurs entre guillemets.
                return None if '"not_allowed"' in texte else "BOARD"

        f = tmp_path / "b.kicad_pcb"
        f.write_text('(kicad_pcb (zone (keepout (tracks "not_allowed"))))', encoding="utf-8")
        assert runner._charger_board(Pcbnew, str(f)) == "BOARD"
        assert appels["n"] == 2, "le chargeur doit reessayer APRES reparation"
        assert '"not_allowed"' not in f.read_text(encoding="utf-8")

    def test_un_board_irreparable_leve_toujours(self, tmp_path, monkeypatch):
        # La reparation est une chance de plus, pas une excuse pour se taire.
        monkeypatch.setattr(runner, "_DOSSIER_ILLISIBLES", tmp_path / "garde")

        class Muet:
            @staticmethod
            def LoadBoard(_p):
                return None

        f = tmp_path / "b.kicad_pcb"
        f.write_text("(kicad_pcb vraiment casse)", encoding="utf-8")
        with pytest.raises(RuntimeError):
            runner._charger_board(Muet, str(f))

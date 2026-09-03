"""Un DRC qui n a pas eu lieu ne rend pas un verdict favorable.

⚠️ Mesure du 2026-08-27, ESP32 du banc. `_rapport_drc_placement` rendait un
dict VIDE des que `kicad-cli` echouait — ici parce que le board place portait
un keepout entre guillemets et se faisait refuser (« Failed to load board »).
`_compter_conflits_erreur` lisait ce vide et annoncait ZERO conflit.

Consequence : la boucle de re-tirage s arretait au premier tirage, satisfaite ;
le board partait au routage ; vingt-cinq minutes plus tard le DRC final
comptait vingt erreurs — celles-la meme qui etaient dans le board place depuis
le debut.

C est la meme famille que `ERC_CLEAN` sans ERC et `DRC_CLEAN` sans DRC, deja
corrigee ailleurs dans ce projet : l absence de controle se lisait comme un
controle reussi. La regle vaut ici aussi.

⚠️ Une seule absence reste toleree : `kicad-cli` introuvable. L appelant ne
peut pas la confondre avec un board refuse, et le service traite deja ce cas en
amont (`skipped`).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import placement as P  # noqa: E402


class _Run:
    """Un `kicad-cli` qui rend la main sans ecrire de rapport."""

    def __init__(self, stdout="Failed to load board", stderr=""):
        self.stdout, self.stderr = stdout, stderr


class TestRapport:
    def test_un_rapport_absent_leve_au_lieu_de_rendre_le_vide(self, monkeypatch, tmp_path):
        monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/kicad-cli")
        monkeypatch.setattr(P.subprocess, "run", lambda *a, **k: _Run())
        board = tmp_path / "b.kicad_pcb"
        board.write_text("(kicad_pcb)", encoding="utf-8")
        with pytest.raises(P.DrcInexecutable):
            P._rapport_drc_placement(board)

    def test_le_message_du_cli_est_conserve(self, monkeypatch, tmp_path):
        monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/kicad-cli")
        monkeypatch.setattr(P.subprocess, "run", lambda *a, **k: _Run())
        board = tmp_path / "b.kicad_pcb"
        board.write_text("(kicad_pcb)", encoding="utf-8")
        with pytest.raises(P.DrcInexecutable, match="Failed to load board"):
            P._rapport_drc_placement(board)

    def test_kicad_cli_absent_reste_tolere(self, monkeypatch, tmp_path):
        monkeypatch.setattr(shutil, "which", lambda _n: None)
        board = tmp_path / "b.kicad_pcb"
        board.write_text("(kicad_pcb)", encoding="utf-8")
        assert P._rapport_drc_placement(board) == {}


class TestCompteur:
    def test_un_tirage_non_mesurable_n_est_jamais_propre(self, monkeypatch, tmp_path):
        def refuse(_p):
            raise P.DrcInexecutable("Failed to load board")

        monkeypatch.setattr(P, "_rapport_drc_placement", refuse)
        n = P._compter_conflits_erreur(tmp_path / "b.kicad_pcb")
        assert n == P._CONFLITS_INDETERMINES
        assert n > 0, "un tirage non mesurable doit faire RE-TIRER"

    def test_la_sentinelle_ne_peut_pas_etre_retenue_comme_meilleure(self):
        # `auto_place` garde le plus petit compte ; la sentinelle doit perdre
        # contre n importe quel tirage reellement mesure, meme mauvais.
        assert P._CONFLITS_INDETERMINES > 10_000


class TestReparationAvantMesure:
    """La reparation doit preceder la mesure, sinon elle ne sert a rien."""

    SOURCE = (_SERVICE_ROOT / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_le_board_est_rendu_lisible_avant_d_etre_juge(self):
        for bloc in ("_compter_conflits_erreur(out)", "_compter_conflits_erreur(f)"):
            i = self.SOURCE.index(bloc)
            avant = self.SOURCE[max(0, i - 200):i]
            assert "_rendre_lisible(" in avant, (
                "mesurer un board illisible rend un rapport vide, lu « 0 erreur »")

    def test_rendre_lisible_deguillemete_vraiment(self, tmp_path):
        f = tmp_path / "b.kicad_pcb"
        f.write_text('(keepout (tracks "not_allowed"))', encoding="utf-8")
        P._rendre_lisible(f)
        assert f.read_text(encoding="utf-8") == "(keepout (tracks not_allowed))"

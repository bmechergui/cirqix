"""Carte de départ dimensionnée sur la surface des composants — réglage de banc.

⚠️ Relevé le 2026-09-19 : carte-09 porte 62 composants dont les courtyards
couvrent 5 % de ses 130 × 100 mm. Le placement étale tout sur la surface
reçue ; le resserrage final ne rattrape rien (127 × 97 hors connecteurs).
La règle est DÉSARMÉE par défaut : elle ne sert qu'à la mesure A/B.
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools import carte_compacte as CC  # noqa: E402


class TestTaille:
    def test_carte_09_ramenee_a_l_occupation_visee(self):
        l, h = CC.taille_compacte(662, 130, 100, 0.25)
        assert abs(l * h - 662 / 0.25) < 5
        assert abs(l / h - 1.3) < 0.01       # proportions gardees

    def test_on_ne_fait_que_reduire(self):
        assert CC.taille_compacte(662, 40, 30, 0.25) is None

    @pytest.mark.parametrize("args", [(0, 130, 100, 0.25), (662, 130, 100, 0),
                                      (662, 130, 100, 1.0), (662, 0, 100, 0.25)])
    def test_entrees_degenerees(self, args):
        assert CC.taille_compacte(*args) is None


class TestReglage:
    def test_vingt_cinq_pour_cent_par_defaut(self, monkeypatch, tmp_path):
        # D-2026-09-20-a, validee : la regle est ARMEE.
        import tools.reglages_banc as RB
        monkeypatch.setattr(RB, "_CHEMIN", tmp_path / "absent.json")
        monkeypatch.delenv("CIRQIX_OCCUPATION_CIBLE", raising=False)
        assert CC.occupation_cible() == 0.25

    def test_un_banc_peut_la_desarmer(self, monkeypatch, tmp_path):
        import tools.reglages_banc as RB
        f = tmp_path / "r.json"
        f.write_text('{"occupation_cible": 0}')
        monkeypatch.setattr(RB, "_CHEMIN", f)
        assert CC.occupation_cible() == 0.0


class TestCablage:
    SOURCE = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_appliquee_seulement_si_la_taille_n_est_pas_imposee(self):
        corps = self.SOURCE[self.SOURCE.index("def auto_place("):]
        corps = corps[: corps.index("\ndef ")]
        i = corps.index("compacter_la_carte_de_depart(")
        assert "if auto_size_board:" in corps[:i]
        assert "cible > 0" in corps[:i]
        # AVANT les tirages : sinon chaque tirage repartirait de la grande carte.
        assert i < corps.index("_auto_place_une_fois(")


pcbnew = pytest.importorskip("kicad_tools", reason="kicad_tools absent : se lance dans le conteneur")

BOARD = RACINE / "examples" / "carte-09-tres-dense" / "expected" / "placement.kicad_pcb"


class TestSurUnVraiBoard:
    def test_contour_reduit_et_mobiles_hors_carte(self):
        if not BOARD.is_file():
            pytest.skip("board du banc absent de l image")
        b64 = base64.b64encode(BOARD.read_bytes()).decode()
        sortie, l, h = CC.compacter_la_carte_de_depart(b64, 130, 100, 0.25)
        assert (l, h) != (130, 100) and l < 130 and h < 100
        texte = base64.b64decode(sortie).decode("utf-8")
        from kicad_tools.schema.pcb import PCB
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "b.kicad_pcb"
            f.write_text(texte, encoding="utf-8")
            pcb = PCB.load(str(f))
            hors = [fp.reference for fp in pcb.footprints if fp.position[0] < -100]
            conns = [fp.reference for fp in pcb.footprints if fp.reference[0] in "JP"]
        assert conns and not (set(conns) & set(hors))   # connecteurs gardes
        assert len(hors) == len(pcb.footprints) - len(conns)
        assert re.search(r'\(gr_rect', texte)

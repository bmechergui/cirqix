"""Un repli GND que le DRC n a pas pu juger ne remplace jamais le board.

⚠️ Releve le 2026-09-18. La comparaison des replis GND (cible et global)
lisait `(_compte_erreurs(r), len(r["unconnected_items"]))`. Quand kicad-cli
refuse de juger un board, `_rapport_drc` rend `_SANS_VERDICT` : ni erreur, ni
connexion manquante, donc `(0, 0)` — le meilleur score possible. Le secours
NON JUGE battait alors n importe quel board reellement mesure :

    avant = (0, 3)   # board route, 3 connexions manquantes, verdict reel
    apres = (0, 0)   # secours que kicad-cli n a pas su ouvrir
    _secours_est_meilleur(avant, apres) -> True   # remplace !

C est la faute que ce depot traque : un echec qui rend la meme valeur que son
cas normal. `_aggrave_le_board` la ferme depuis le 2026-09-07 (« je ne peux
pas juger » vaut « c est pire ») ; les replis GND, eux, comparaient encore des
couples bruts. `_reparer_reliefs_affames` testait deja `_sans_verdict` a la
main — la seule des trois.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402

_REEL = {"violations": [], "unconnected_items": [{}, {}, {}]}  # 0 erreur, 3 manquantes


class TestRegle:
    def test_sans_verdict_le_bilan_ne_vaut_PAS_zero(self, monkeypatch):
        monkeypatch.setattr(R, "_rapport_drc", lambda b: R._SANS_VERDICT.copy())
        assert R._bilan_drc(b"x") is None

    def test_avec_verdict_le_bilan_est_mesure(self, monkeypatch):
        monkeypatch.setattr(R, "_rapport_drc", lambda b: dict(_REEL))
        assert R._bilan_drc(b"x") == (0, 3)

    def test_un_secours_NON_JUGE_est_refuse(self):
        assert R._secours_est_meilleur(avant=(0, 3), apres=None) is False

    def test_un_board_de_reference_NON_JUGE_ne_se_remplace_pas_a_l_aveugle(self):
        assert R._secours_est_meilleur(avant=None, apres=(0, 0)) is False


class TestReplicible:
    def test_le_repli_CIBLE_garde_le_board_quand_le_secours_n_est_pas_juge(self, monkeypatch):
        final, cible = b"final-route", b"cible-illisible"
        monkeypatch.setattr(R, "_router_gnd_cible", lambda *a, **k: cible)
        monkeypatch.setattr(
            R, "_rapport_drc",
            lambda b: dict(_REEL) if b == final else R._SANS_VERDICT.copy())
        garde, orphelines = R._repli_gnd_cible_iteratif(
            b"etendu", None, 60.0, [("U1", "8")], final)
        assert garde == final
        assert orphelines == [("U1", "8")]


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_repli_GLOBAL_compare_par_le_bilan_qui_echoue_ferme(self):
        # Le bloc REEL, de l appel du repli jusqu a l etape suivante.
        i = self.SOURCE.index("secours = _router_en_incluant_gnd(")
        fin = self.SOURCE.index("_reparer_reliefs_affames", i)
        bloc = self.SOURCE[i:fin]
        assert "_bilan_drc(" in bloc, (
            "le repli global compare encore des couples bruts, que "
            "_SANS_VERDICT fait valoir (0, 0)")

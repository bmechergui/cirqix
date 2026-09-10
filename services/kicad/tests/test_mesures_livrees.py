"""Une carte livree par `livrer_campagne.py` emporte son `mesures.json`.

Mesure du 2026-09-10 : `carte-05` livree a 100 % / 59 violations gardait le
`mesures.json` de la livraison precedente (38 violations). Le script lit ce
fichier dans git pour juger la campagne SUIVANTE : une mesure qui ne decrit
pas le board livre fausse le prochain verdict.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE / "scripts"))

import livrer_campagne as L  # noqa: E402

_RESUME = ("SUMMARY routed=100 drc_violations=59 drc_clean=True files=20 "
           "types=silk_over_copper:40,silk_overlap:18,track_dangling:1")


def test_les_champs_mesures_sont_remplaces_et_le_reste_conserve():
    m = L.mesures_livrees({"largeur_mm": 70, "drc_violations": 38}, _RESUME, 0, "carte-05-t1")
    assert m["largeur_mm"] == 70
    assert m["routed_percent"] == 100 and m["drc_violations"] == 59 and m["drc_clean"] is True
    d = m["drc_du_board"]
    assert d["violations"] == 59 and d["nb_erreurs"] == 0 and d["fabricable"] is True
    assert d["types"].startswith("silk_over_copper:40")
    assert m["tirage"] == "carte-05-t1"


def test_des_erreurs_ou_des_non_connectes_rendent_non_fabricable():
    resume = "SUMMARY routed=92 drc_violations=48 drc_clean=False files=20 types=silk_overlap:14,unconnected_items:8"
    m = L.mesures_livrees({}, resume, 8, "t")
    assert m["drc_du_board"]["non_connectes"] == 8
    assert m["drc_du_board"]["fabricable"] is False
    assert L.mesures_livrees({}, "SUMMARY routed=100 drc_violations=3 drc_clean=True", 2, "t")["drc_du_board"]["fabricable"] is False


def test_sans_summary_rien_n_est_invente():
    assert L.mesures_livrees({"a": 1}, "AUCUN SUMMARY", 0, "t") == {"a": 1}


def test_la_livraison_ecrit_le_fichier():
    code = "\n".join(l.split("#")[0] for l in inspect.getsource(L.main).splitlines())
    assert "mesures_livrees(" in code and "mesures.json" in code


class TestLesCouchesComptent:
    """carte-11, 2026-09-10 : 100 %/0 err sur QUATRE couches livree par-dessus
    100 %/0 err sur DEUX. A egalite, moins de couches gagne."""

    def test_le_compte_des_couches_cuivre(self):
        deux = '(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (32 "B.Adhes" user))'
        quatre = '(layers (0 "F.Cu" signal) (1 "In1.Cu" signal) (2 "In2.Cu" signal) (31 "B.Cu" signal))'
        assert L.couches_du_texte(deux) == 2 and L.couches_du_texte(quatre) == 4

    def test_a_egalite_moins_de_couches_gagne(self):
        assert (0, 0, -100, 2) < (0, 0, -100, 4)
        assert (0, 0, -100, 4) < (0, 1, -100, 2), "une erreur DRC pese plus qu une couche"

    def test_les_deux_notes_portent_les_couches(self):
        for fn in (L._note_versionnee, L._note_du_tirage):
            code = "\n".join(l.split("#")[0] for l in inspect.getsource(fn).splitlines())
            assert "couches_du_texte(" in code, fn.__name__

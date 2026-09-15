"""Une broche nommee par son abreviation de datasheet trouve la BONNE broche — ou aucune.

Mesure du 2026-09-15, rejeu du projet « Thermometre I2C TMP102 (driver) » :
un NE555 dont le schema nomme ses broches comme sa datasheet — TR, Q, R, CV,
THR, DIS — alors que la bibliotheque KiCad les nomme TRIG, OUT, ~{RST}, CONT,
THRES, DISCH.

`_resolve_pin` se rabattait sur une recherche de SOUS-CHAINE. Resultat, par
kicad-cli sur le schema regenere :

    CV  -> aucune broche      U1.5 non connectee
    Q   -> aucune broche      U1.3 non connectee
    R   -> THRES (!)          VCC relie a la broche SEUIL, sans avertissement
                              U1.4 (RESET) non connectee

Le journal ne signalait que CV et Q. « R » etait contenu dans « THRES » :
l'alimentation etait branchee sur une broche de signal, en silence. Une
connexion FAUSSE est pire qu'une connexion absente — l'ERC voit la seconde,
pas toujours la premiere.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import schematic as S  # noqa: E402

NE555_KICAD = ["CONT", "DISCH", "GND", "OUT", "THRES", "TRIG", "VCC", "~{RST}"]


class _Broche:
    def __init__(self, composant: "_Composant", nom: str) -> None:
        self.composant, self.nom = composant, nom

    def __iadd__(self, net: object) -> "_Broche":
        self.composant.branchements.append((self.nom, net))
        return self


class _Composant:
    """Un faux composant circuit_synth : `comp[nom] += net`, et la meme erreur que la vraie."""

    def __init__(self, broches: list[str]) -> None:
        self.broches = broches
        self.branchements: list[tuple[str, object]] = []

    def __getitem__(self, cle: object) -> _Broche:
        if isinstance(cle, int) and 1 <= cle <= len(self.broches):
            return _Broche(self, f"#{cle}")
        if cle in self.broches:
            return _Broche(self, str(cle))
        disponibles = ", ".join(f"'{b}'" for b in sorted(self.broches))
        raise Exception(f"Pin '{cle}' not found in U1 (Timer:NE555P). Available: {disponibles}")

    def __setitem__(self, cle: object, valeur: object) -> None:
        pass


def _brancher(nom: object, broches: list[str] = NE555_KICAD) -> tuple[bool, list[str]]:
    comp = _Composant(broches)
    ok = S._resolve_pin(comp, nom, "U1", "NET")
    return ok, [b for b, _ in comp.branchements]


class TestAbreviationsDeDatasheet:
    @pytest.mark.parametrize("abreviation, broche_kicad", [
        ("TR", "TRIG"),
        ("THR", "THRES"),
        ("DIS", "DISCH"),
        ("Q", "OUT"),
        ("CV", "CONT"),
        ("R", "~{RST}"),
        ("RESET", "~{RST}"),
        ("TRIGGER", "TRIG"),
        ("THRESHOLD", "THRES"),
        ("DISCHARGE", "DISCH"),
        ("CTRL", "CONT"),
    ])
    def test_chaque_abreviation_trouve_sa_broche(self, abreviation, broche_kicad):
        assert _brancher(abreviation) == (True, [broche_kicad])

    def test_R_n_est_JAMAIS_branche_sur_THRES(self):
        # Le defaut mesure : « R » est contenu dans « THRES ».
        ok, branchements = _brancher("R")
        assert "THRES" not in branchements and "TRIG" not in branchements


class TestJamaisDeBranchementFaux:
    def test_un_nom_seulement_CONTENU_dans_un_autre_ne_branche_rien(self):
        # « ES » est dans « THRES » mais ne designe aucune broche.
        assert _brancher("ES") == (False, [])

    def test_un_prefixe_AMBIGU_ne_branche_rien(self):
        assert _brancher("IN", ["IN1", "IN2", "OUT"]) == (False, [])

    def test_un_nom_inconnu_ne_branche_rien(self):
        assert _brancher("ZZ") == (False, [])


class TestCeQuiMarchaitDeja:
    def test_le_nom_exact_KiCad(self):
        assert _brancher("THRES") == (True, ["THRES"])

    def test_le_numero_de_broche(self):
        assert _brancher(4) == (True, ["#4"])

    def test_le_nom_surligne_sans_ses_accolades(self):
        assert _brancher("RST") == (True, ["~{RST}"])

    def test_un_nom_a_segments(self):
        assert _brancher("PA5", ["PA4", "PA5/SCK", "PA6"]) == (True, ["PA5/SCK"])

"""Une absence de mesure ne peut JAMAIS valoir « fabricable ».

⚠️ Ce generateur a reellement rendu « fabricable oui » pour `carte-07` alors
que son pipeline avait ete tue au placement : `mesures.json` ne portait ni
`routed_percent` ni `drc_du_board`. L'ancien repli cherchait des types de
violations dans un champ VIDE, n'en trouvait aucun, et concluait au succes.

C'est le defaut le plus cher de ce depot, deja paye trois fois — rapport DRC
vide lu « 0 erreur », nets KiCad 10 comptes a zero, `via_count` jamais calcule
rendu a zero. On teste donc les DEUX faces : la mesure absente echoue, et la
mesure presente est bien lue.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from readme_banc_driver import _fabricable  # noqa: E402


def test_aucune_mesure_ne_vaut_pas_fabricable():
    fabricable, motif = _fabricable({})
    assert fabricable is False
    assert "non mesure" in motif


def test_mesures_vides_ne_valent_pas_fabricable():
    """La forme EXACTE qui a produit le faux verdict."""
    fabricable, _ = _fabricable({"composants": 48, "types_violations": ""})
    assert fabricable is False


def test_drc_du_board_vide_ne_vaut_pas_fabricable():
    """Un `drc_du_board` present mais SANS verdict ne tranche rien."""
    fabricable, _ = _fabricable({"drc_du_board": {}})
    assert fabricable is False


def test_le_verdict_du_board_fait_foi():
    ok, _ = _fabricable({"drc_du_board": {"fabricable": True, "nb_erreurs": 0}})
    assert ok is True

    ko, motif = _fabricable({"drc_du_board": {
        "fabricable": False, "nb_erreurs": 3, "erreurs": ["unconnected_items"]}})
    assert ko is False
    assert "3 erreur" in motif and "unconnected_items" in motif


@pytest.mark.parametrize("avertissement", [
    "via_dangling", "track_dangling", "silk_overlap", "silk_over_copper"])
def test_les_avertissements_kicad_ne_bloquent_pas(avertissement):
    """KiCad les classe `warning` : la carte se fabrique.

    Je les classais bloquants sur ma propre liste — plus severe que KiCad
    lui-meme, ce qui declarait non fabricables des cartes qui le sont.
    """
    ok, _ = _fabricable({"drc_du_board": {
        "fabricable": True, "nb_erreurs": 0, "types": "%s:12" % avertissement}})
    assert ok is True

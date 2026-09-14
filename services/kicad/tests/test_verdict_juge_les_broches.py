"""D-2026-09-14-a — le verdict « pro » du banc juge les broches, pas la moyenne des capas.

carte-10 : 22 capas de découplage sur les quatre broches VDD d'un LQFP. Chaque
broche servie à 2,1 mm ; moyenne de TOUTES les capas ≥ 5,4 mm à cinq campagnes
— refusée à chaque fois, quel que soit le moteur. Ce que ces tests
discriminent : la population jugée (la capa la plus proche de chaque broche),
les surnuméraires comptées mais pas jugées, une broche nue toujours refusée,
et les seuils inchangés.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import valider_placements as vp  # noqa: E402


def test_les_surnumeraires_ne_font_pas_refuser_une_carte_dont_chaque_broche_est_servie():
    # Le cas carte-10 en miniature : 2 broches, 6 capas ; l ancienne moyenne (5,4) refusait.
    par_broche = {("U1", 0.0, 0.0): [2.1, 6.0, 7.5, 8.0], ("U1", 7.0, 0.0): [1.9, 7.0]}
    v = vp.verdict_decouplage(par_broche)
    assert v["pro"] is True
    assert v["couverture"] == pytest.approx(2.1)
    assert v["moy_servantes"] == pytest.approx(2.0)
    assert v["n_servantes"] == 2 and v["n_surnumeraires"] == 4
    assert v["moy_surnumeraires"] == pytest.approx((6.0 + 7.5 + 8.0 + 7.0) / 4)
    assert sum(sum(x) for x in par_broche.values()) / 6 > vp._DECOUPLAGE_MOY_MM, "l ancien critere refusait"


def test_une_broche_nue_est_toujours_refusee():
    v = vp.verdict_decouplage({("U1", 0.0, 0.0): [2.0], ("U1", 7.0, 0.0): [4.0, 4.5]})
    assert v["pro"] is False and v["couverture"] == pytest.approx(4.0)


def test_les_seuils_sont_inchanges_et_la_moyenne_des_servantes_compte():
    assert vp._COUVERTURE_MM == 3.5 and vp._DECOUPLAGE_MOY_MM == 5.0
    # Trois broches servies a 3,4 mm chacune : couverture ok, moyenne 3,4 ok.
    assert vp.verdict_decouplage({(f"U1", i, 0.0): [3.4] for i in range(3)})["pro"] is True


def test_sans_broche_d_alimentation_rien_a_juger():
    v = vp.verdict_decouplage({})
    assert v["pro"] is True and v["couverture"] == 0.0 and v["n_servantes"] == 0


def test_la_couverture_est_bien_celle_du_verdict():
    """`_couverture` doit rendre la meme valeur que le verdict — une mesure, un endroit."""
    assert vp.verdict_decouplage({("U1", 0.0, 0.0): [3.0, 9.0]})["couverture"] == 3.0

"""Phase B de D-2026-09-26-a : un repère tourné dans l axe de son boîtier,
posé contre son corps.

Campagne du 2026-09-26, carte-07 : 9 repères en conflit, et
`degager_references` (texte à plat, 4 mm autour de l origine) n en plaçait
AUCUN. Mesuré sur quatre boards routés de la campagne, DRC kicad-cli :
70 avertissements de sérigraphie -> 16 ; carte-05 et carte-06 à zéro.

Gardes sur un VRAI board du banc, pas seulement sur une fixture.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

from kicad_tools.schema.pcb import PCB  # noqa: E402

from tools import serigraphie as S  # noqa: E402

CARTE_07 = _SERVICE / "examples" / "carte-07-multi-io" / "expected" / "placement.kicad_pcb"


def _charger(tmp_path):
    copie = tmp_path / "b.kicad_pcb"
    copie.write_bytes(CARTE_07.read_bytes())
    return copie, PCB.load(str(copie))


def _etat_des_references(pcb):
    return {fp.reference: (S._reference_visible(fp).position, S._angle_reference(pcb, fp.reference))
            for fp in pcb.footprints if fp.reference and S._reference_visible(fp) is not None}


@pytest.mark.parametrize("rot", [0.0, 90.0, 180.0, 270.0, 33.0])
def test_vers_local_est_l_inverse_de_tourne(rot):
    fp = SimpleNamespace(position=(12.0, -4.0), rotation=rot)
    x, y = S._tourne(fp, 1.3, -0.7)
    assert S._vers_local(fp, x, y) == pytest.approx((1.3, -0.7))


def test_moins_de_chevauchements_et_aucune_reduction(tmp_path):
    _, pcb = _charger(tmp_path)
    S.degager_references(pcb)
    avant = sum(S.compter_chevauchements(pcb))
    polices = {fp.reference: S._hauteur(S._reference_visible(fp))
               for fp in pcb.footprints if S._reference_visible(fp) is not None}
    assert S.reorienter_et_degager(pcb) >= 1
    assert sum(S.compter_chevauchements(pcb)) < avant
    assert polices == {fp.reference: S._hauteur(S._reference_visible(fp))
                       for fp in pcb.footprints if S._reference_visible(fp) is not None}


def test_ne_touche_que_ce_qui_chevauche(tmp_path):
    _, pcb = _charger(tmp_path)
    S.degager_references(pcb)
    boites = S.boites_des_references(pcb)
    genes = S._obstacles_cuivre(pcb) + S._obstacles_serigraphie(pcb)
    en_conflit = {r for r, b in boites.items()
                  if any(S._chevauche(b, o) for o in genes)
                  or any(S._chevauche(b, o) for q, o in boites.items() if q != r)
                  or S._deborde(b, S._contour(pcb))}
    avant = _etat_des_references(pcb)
    S.reorienter_et_degager(pcb)
    apres = _etat_des_references(pcb)
    touches = {r for r in avant if avant[r] != apres[r]}
    assert touches and touches <= en_conflit


def test_l_angle_ecrit_survit_a_la_sauvegarde(tmp_path):
    chemin, pcb = _charger(tmp_path)
    S.degager_references(pcb)
    S.reorienter_et_degager(pcb)
    angles = {fp.reference: S._angle_reference(pcb, fp.reference) for fp in pcb.footprints}
    assert any(a % 180 == 90 for a in angles.values())
    pcb.save(str(chemin))
    relu = PCB.load(str(chemin))
    assert angles == {fp.reference: S._angle_reference(relu, fp.reference) for fp in relu.footprints}


def test_le_placement_appelle_la_seconde_passe():
    src = (_SERVICE / "tools" / "placement.py").read_text(encoding="utf-8")
    assert "n = degager_references(pcb) + reorienter_et_degager(pcb)" in src


def test_la_serigraphie_se_rejoue_apres_le_resserrage_du_contour():
    src = (_SERVICE / "tools" / "placement.py").read_text(encoding="utf-8")
    corps = src[src.index("def _resserrer_le_contour"):src.index("def _couronne_de_secours")]
    assert corps.index("ajuster_contour_au_placement(f)") < corps.index("_degager_la_serigraphie(f)")


def test_un_second_passage_lit_les_angles_ecrits(tmp_path):
    """Revue du 2026-09-26 : `_resserrer_le_contour` rejoue les deux passes sur
    un board déjà tourné ; la passe à plat doit voir les textes verticaux."""
    _, pcb = _charger(tmp_path)
    S.degager_references(pcb)
    S.reorienter_et_degager(pcb)
    tournes = [fp for fp in pcb.footprints if S._angle_reference(pcb, fp.reference) % 180 == 90]
    assert tournes
    boites = S.boites_des_references(pcb)
    for fp in tournes:
        b = boites[fp.reference]
        assert (b[3] - b[1]) > (b[2] - b[0])      # boîte verticale, comme le texte
    avant = sum(S.compter_chevauchements(pcb))
    S.degager_references(pcb)
    S.reorienter_et_degager(pcb)
    assert sum(S.compter_chevauchements(pcb)) <= avant

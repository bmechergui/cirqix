"""Le routeur et le juge DRC doivent appliquer le MÊME règlement fabricant.

Contexte du chantier (2026-07-30). ``_CLEARANCE_MM = "0.2"`` a été calibré le
2026-07-06, à une époque où ``kicad-cli pcb drc`` jugeait avec les DÉFAUTS
KiCad (clearance 0,2 mm) faute de sidecar projet. Le chantier DRC-clean du
2026-07-19 a ensuite aligné le juge sur le profil fabricant via
``drc.write_mfr_project_sidecar`` (jlcpcb : 0,127 mm à 2 couches, 0,1016 mm à
4) — mais la constante du routeur n'a pas suivi.

Conséquence mesurée : le routeur s'interdisait ~2× ce que le fabricant autorise
ET ce que le juge accepte, sans gain de fabricabilité (un court-circuit est un
CONTACT cuivre, insensible à la clearance). Sur un LQFP-48 (pas 0,5 mm, pads
0,3 mm → gap inter-pads 0,2 mm), à 0,2 mm de clearance la piste maximale
entre deux pads vaut 0,1 mm, sous le minimum fabricant : aucun échappement de
surface n'est géométriquement possible.

Ces tests verrouillent la dérivation depuis le profil, pas la valeur en dur.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kicad-tools" / "src"))

from tools import kct_route  # noqa: E402

pytest.importorskip("kicad_tools.manufacturers")

_TWO_LAYER_BOARD = '(kicad_pcb (layers (0 "F.Cu" signal) (31 "B.Cu" signal)))'


def _profile_clearance(tier: str, layers: int) -> float:
    from kicad_tools.manufacturers import get_profile

    return get_profile(tier).get_design_rules(layers, 1.0).min_clearance_mm


_MARGE = kct_route._CLEARANCE_SAFETY_MARGIN_MM


def test_clearance_derivee_du_profil_fabricant_et_non_codee_en_dur():
    """La clearance passée au routeur vient du profil, au nombre de couches réel."""
    tier = kct_route._MFR_TIER_LADDER.split(",")[0].strip()

    obtenu = kct_route._profile_clearance_mm(fine_pitch=False,
                                             pcb_text=_TWO_LAYER_BOARD)

    assert float(obtenu) == pytest.approx(_profile_clearance(tier, 2) + _MARGE)


def test_fine_pitch_juge_a_quatre_couches_comme_starting_layers():
    """``--starting-layers 4`` impose de raisonner à 4 couches, pas à 2."""
    tier = kct_route._MFR_TIER_LADDER.split(",")[0].strip()

    obtenu = kct_route._profile_clearance_mm(fine_pitch=True,
                                             pcb_text=_TWO_LAYER_BOARD)

    assert float(obtenu) == pytest.approx(_profile_clearance(tier, 4) + _MARGE)
    assert float(obtenu) < float(kct_route._CLEARANCE_FALLBACK_MM)


def test_routeur_et_juge_partagent_le_meme_reglement():
    """Anti-régression du défaut d'origine : plus jamais deux règlements.

    Le juge lit ``get_profile(tier).get_design_rules(layers, 1.0)`` dans
    ``drc.write_mfr_project_sidecar`` ; le routeur doit lire exactement la même
    source, sinon on recrée le motif « 100 % routé, jamais fabricable ». Il vise
    volontairement un cran au-dessus du plancher (cf. la marge de sécurité), ce
    qui reste conforme : un plancher est un minimum, pas une cible.
    """
    tier = kct_route._MFR_TIER_LADDER.split(",")[0].strip()
    plancher_du_juge = _profile_clearance(tier, 4)

    clearance_routeur = float(kct_route._profile_clearance_mm(
        fine_pitch=True, pcb_text=_TWO_LAYER_BOARD))

    assert clearance_routeur >= plancher_du_juge
    assert clearance_routeur == pytest.approx(plancher_du_juge + _MARGE)


def test_clearance_transmise_strictement_au_dessus_du_plancher_du_juge():
    """Le routeur doit viser AU-DESSUS du plancher, jamais dessus.

    Défaut mesuré le 2026-07-30 sur le board STM32 rerouté : en transmettant le
    plancher exact du profil (0,1016 mm = 4 mil), le routeur a produit une piste
    à 0,1000 mm — il arrondit à sa grille interne — et le juge a levé
    ``clearance (requise 0.1016 mm; réelle 0.1000 mm)``. **1,6 µm d'écart** pour
    une erreur DRC. Une marge de sécurité absorbe la troncature.
    """
    tier = kct_route._MFR_TIER_LADDER.split(",")[0].strip()
    plancher = _profile_clearance(tier, 4)

    transmise = float(kct_route._profile_clearance_mm(fine_pitch=True,
                                                     pcb_text=_TWO_LAYER_BOARD))

    assert transmise > plancher, "une troncature ferait repasser sous le plancher"
    # La marge reste petite : elle ne doit pas coûter de complétion.
    assert transmise - plancher <= 0.02


def test_stitch_power_planes_active_quand_la_revision_le_supporte(monkeypatch):
    """Sans couture, le plan de masse n'est relié à aucun pad.

    Mesuré le 2026-07-30 : sur le board rerouté à 100 %, les 17 connexions
    manquantes restantes étaient **toutes** sur GND — zone de masse présente,
    mais zéro via la reliant aux pads. ``--stitch-power-planes`` pose ces vias.
    """
    monkeypatch.setattr(kct_route, "_route_supports", lambda flag: True)

    cmd = kct_route._build_route_cmd(Path("in.kicad_pcb"), Path("out.kicad_pcb"),
                                     300, fine_pitch=True)

    assert "--stitch-power-planes" in cmd


def test_flag_omis_si_la_revision_installee_ne_le_connait_pas(monkeypatch):
    """Un flag inconnu fait échouer TOUT le routage (rc=2, usage error).

    Mesuré le 2026-07-30 : l'image ``cirqix-kicad:latest`` installe kicad-tools
    depuis ``/opt``, antérieur au gitlink du dépôt, et rejetait
    ``--stitch-power-planes``. Le routage doit dégrader, pas planter.
    """
    monkeypatch.setattr(kct_route, "_route_supports", lambda flag: False)

    cmd = kct_route._build_route_cmd(Path("in.kicad_pcb"), Path("out.kicad_pcb"),
                                     300, fine_pitch=True)

    assert "--stitch-power-planes" not in cmd
    assert "--auto-mfr-tier" in cmd  # le reste de la ligne est intact


def test_build_route_cmd_utilise_la_clearance_fournie():
    cmd = kct_route._build_route_cmd(Path("in.kicad_pcb"), Path("out.kicad_pcb"),
                                     300, fine_pitch=True, clearance_mm="0.1016")

    assert cmd[cmd.index("--clearance") + 1] == "0.1016"


def test_repli_sur_la_constante_si_le_profil_est_indisponible(monkeypatch):
    """Un profil manquant ne doit jamais faire échouer le routage."""
    def _boom(_tier):
        raise RuntimeError("profil indisponible")

    monkeypatch.setattr("kicad_tools.manufacturers.get_profile", _boom)

    obtenu = kct_route._profile_clearance_mm(fine_pitch=True,
                                             pcb_text=_TWO_LAYER_BOARD)

    assert obtenu == kct_route._CLEARANCE_FALLBACK_MM

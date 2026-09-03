"""Deux connecteurs ancres ne doivent JAMAIS finir au meme point.

Trouve le 2026-08-23 par le premier pipeline complet passe par la file. Le run
tournait en rond — PLACEMENT, DRC, PLACEMENT, DRC — trois minutes par tirage, et
l orchestrateur expliquait lui-meme pourquoi :

    « courtyards overlap + PTH inside courtyard -> J1 et J3 co-localises
      (meme position x=128.5, y=123). Le placement a echoue. »

⚠️ Le re-tirage ne peut PAS reparer ce defaut. Les connecteurs sont ANCRES
(`fixed_refs`) — a dessein : leur position est une contrainte mecanique. Re-tirer
redistribue les composants MOBILES et laisse les deux connecteurs exactement l un
sur l autre. La boucle de sauvetage est structurellement incapable de corriger ce
qu elle observe, et le run epuise ses iterations sans jamais atteindre DRC_CLEAN.

La cause est dans `_clamp_fixed_refs_to_outline` : il ramene chaque ancrage
hors-carte a l interieur du contour INDEPENDAMMENT des autres. Deux connecteurs
debordant du meme cote sont donc clampes au MEME coin.

Pourquoi ce n a jamais ete vu : toutes nos validations de placement partaient
d un board DEJA place (`examples/stm32-validation/output/2_placement.kicad_pcb`).
Le pipeline complet, lui, fabrique le board depuis une description via
`gen_pcb` — et c est cette entree-la qui pose des connecteurs hors-carte.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import placement as P  # noqa: E402


def _board(connecteurs: list[tuple[str, float, float]]) -> str:
    fps = []
    for ref, x, y in connecteurs:
        fps.append(
            f'\t(footprint "Connector:Conn_01x04"\n'
            f'\t\t(layer "F.Cu")\n'
            f"\t\t(at {x} {y})\n"
            f'\t\t(fp_text reference "{ref}" (at 0 0) (layer "F.SilkS"))\n'
            f'\t\t(pad "1" thru_hole circle (at 0 0) (size 1 1) (drill 0.6)\n'
            f'\t\t\t(layers "*.Cu") (net 1 "GND"))\n'
            f"\t)"
        )
    return (
        "(kicad_pcb\n\t(version 20240108)\n"
        '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)\n'
        '\t\t(44 "Edge.Cuts" user)\n\t)\n'
        '\t(net 0 "")\n\t(net 1 "GND")\n'
        '\t(gr_rect (start 100 100) (end 160 140) (layer "Edge.Cuts"))\n'
        + "\n".join(fps)
        + "\n)"
    )


def _charger(texte: str):
    from kicad_tools.schema.pcb import PCB

    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "b.kicad_pcb"
        f.write_text(texte, encoding="utf-8")
        return PCB.load(str(f))


class TestClampDesAncrages:
    def test_deux_connecteurs_hors_carte_ne_se_superposent_pas(self):
        # Le cas mesure : deux connecteurs poses loin, DU MEME COTE. Clampes
        # independamment, ils atterrissent au meme coin.
        pcb = _charger(_board([("J1", 400.0, 400.0), ("J3", 420.0, 430.0)]))
        refs = P._connector_refs(pcb)
        assert sorted(refs) == ["J1", "J3"]

        P._clamp_fixed_refs_to_outline(pcb, refs)
        positions = [fp.position for fp in pcb.footprints if fp.reference in refs]
        assert len(set(positions)) == len(positions), (
            f"connecteurs superposes apres clamp : {positions}"
        )

    def test_un_connecteur_deja_dans_la_carte_ne_bouge_pas(self):
        # Ne pas deplacer ce qui n a pas besoin de l etre : la position d un
        # connecteur est une contrainte mecanique, pas une suggestion.
        pcb = _charger(_board([("J1", 120.0, 120.0)]))
        avant = [fp.position for fp in pcb.footprints if fp.reference == "J1"][0]
        P._clamp_fixed_refs_to_outline(pcb, ["J1"])
        apres = [fp.position for fp in pcb.footprints if fp.reference == "J1"][0]
        assert apres == avant

    def test_trois_connecteurs_hors_carte_restent_distincts(self):
        pcb = _charger(_board([("J1", 400.0, 400.0), ("J2", 401.0, 400.0),
                               ("J3", 402.0, 401.0)]))
        refs = P._connector_refs(pcb)
        P._clamp_fixed_refs_to_outline(pcb, refs)
        positions = [fp.position for fp in pcb.footprints if fp.reference in refs]
        assert len(set(positions)) == 3, f"superposition : {positions}"


class TestAncragesDejaDansLaCarte:
    """Le defaut ne vient pas forcement du clamp.

    Deux connecteurs poses en collision A L INTERIEUR du contour ne sont pas
    clampes — donc ils echappaient au correctif, alors qu ils produisent
    exactement le meme blocage : courtyards qui se chevauchent, DRC en echec, et
    un re-tirage impuissant puisque les ancrages ne bougent pas.

    On ne deplace QUE ceux qui sont reellement en collision, jugee par
    `PCB.check_placement_collision` (courtyards reels). Un connecteur valide ne
    bouge jamais : sa position est une contrainte mecanique.
    """

    def test_deux_connecteurs_superposes_dans_la_carte_sont_separes(self):
        pcb = _charger(_board([("J1", 120.0, 120.0), ("J3", 120.0, 120.0)]))
        refs = P._connector_refs(pcb)
        P._clamp_fixed_refs_to_outline(pcb, refs)
        positions = [fp.position for fp in pcb.footprints if fp.reference in refs]
        assert len(set(positions)) == 2, f"toujours superposes : {positions}"

    def test_deux_connecteurs_bien_separes_ne_bougent_pas(self):
        # Le cas normal, de loin le plus frequent : on ne touche a rien.
        pcb = _charger(_board([("J1", 110.0, 110.0), ("J3", 150.0, 130.0)]))
        refs = P._connector_refs(pcb)
        avant = {fp.reference: fp.position for fp in pcb.footprints if fp.reference in refs}
        P._clamp_fixed_refs_to_outline(pcb, refs)
        apres = {fp.reference: fp.position for fp in pcb.footprints if fp.reference in refs}
        assert apres == avant

"""Une empreinte verrouillée (`(locked yes)`) ne bouge pas au placement.

D-2026-09-27-a : un module qu'on veut figer, ou une pièce posée par
l'utilisateur, garde sa position — jamais centrée comme boîtier dominant,
couchée ni collée au bord.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "kicad-tools" / "src"))

from kicad_tools.schema.pcb import PCB  # noqa: E402

from tools import placement as P  # noqa: E402

CARTE_07 = RACINE / "examples" / "carte-07-multi-io" / "expected" / "placement.kicad_pcb"


def test_les_references_verrouillees_survivent_a_la_sauvegarde(tmp_path):
    chemin = tmp_path / "b.kicad_pcb"
    chemin.write_bytes(CARTE_07.read_bytes())
    pcb = PCB.load(str(chemin))
    cible = pcb.footprints[0]
    cible.locked = True
    pcb.save(str(chemin))
    assert P._refs_verrouillees(PCB.load(str(chemin))) == [cible.reference]


def test_le_placement_les_fige_et_les_exempte():
    src = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")
    corps = src[src.index("def _auto_place_une_fois("):]
    assert "verrouilles = _refs_verrouillees(pcb)" in corps
    assert "conn = conn + [r for r in verrouilles if r not in conn]" in corps
    assert "dominants = [r for r in _boitiers_dominants(pcb) if r not in verrouilles]" in corps
    assert "exempts = dominants + verrouilles" in corps
    for appel in ("_clamp_fixed_refs_to_outline(pcb, conn, exempts=exempts)",
                  "coucher_les_connecteurs(pcb, conn, exempts=exempts)",
                  "_coller_les_ancrages_au_bord(pcb, conn, exempts=exempts"):
        assert appel in corps

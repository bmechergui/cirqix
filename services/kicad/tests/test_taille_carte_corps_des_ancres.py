"""D-2026-09-28-a : un composant ANCRÉ réserve son corps, pas deux fois sa portée.

Campagne du 2026-09-28 : les cartes à module sortaient à 81 x 90 mm (Arduino,
module de 69 x 53) et 134 x 144 mm (Nucleo) — `taille_carte` réservait
`2 × portée` depuis l'origine du module, posée sur un coin : 102 et 184 mm.
Les composants mobiles gardent la portée (la réparation hors carte les
déplace en rayon — cause de la règle d'origine, carte-11).
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "kicad-tools" / "src"))

from kicad_tools.schema.pcb import PCB  # noqa: E402

from tools import placement as P  # noqa: E402
from tools import taille_carte as T  # noqa: E402

CARTE_11 = RACINE / "examples" / "carte-11-croisements" / "expected" / "placement.kicad_pcb"


def test_un_ancre_reserve_son_corps_et_la_carte_le_contient_encore():
    pcb = PCB.load(str(CARTE_11))
    conn = P._connector_refs(pcb)
    assert conn
    j = next(f for f in pcb.footprints if f.reference in conn)
    b = P._boite_orientee_fp(j)
    long = max(b[2] - b[0], b[3] - b[1])
    assert T._exigence_demi(j, True) == long / 2
    assert T._exigence_demi(j, True) < T._exigence_demi(j, False)     # portée : plus
    l, h, _ = T.taille_minimale(pcb)
    assert min(l, h) >= long + 2 * T._MARGE_BORD_MM                   # le corps tient


def test_sans_ancre_la_regle_d_origine(monkeypatch):
    pcb = PCB.load(str(CARTE_11))
    monkeypatch.setattr(T, "_ancres", lambda pcb: set())
    avant = T.taille_minimale(pcb)[0]
    monkeypatch.undo()
    assert T.taille_minimale(pcb)[0] <= avant


def test_les_ancres_sont_connecteurs_dominants_et_verrouilles():
    pcb = PCB.load(str(CARTE_11))
    assert set(P._connector_refs(pcb)) <= T._ancres(pcb)

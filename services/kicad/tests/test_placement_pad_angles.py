"""Le writer ajoute aux pads un angle que la source ne déclare pas.

Mesuré le 2026-08-01, Docker, sur `examples/stm32-validation` :

- source ``gen0`` — ``(footprint ... (at x y))`` sans rotation, pads
  ``(at 4.1625 2.75)`` **sans angle**, conformes au footprint officiel KiCad
  ``Package_QFP:LQFP-48_7x7mm_P0.5mm`` ;
- après placement — footprint toujours **non pivoté**, mais chaque pad porte
  ``(at 4.1625 2.75 90)``.

Les pads 25-27 d'un LQFP-48 forment une colonne verticale au pas de 0,5 mm. Un
angle de 90° bascule leur grand axe (1,475 mm) le long de la colonne : les
voisins se recouvrent d'un millimètre. Les positions, elles, ne bougent pas —
c'est l'angle seul qui est corrompu.

Effet mesuré sur un board **sans une seule piste** :

=================================  ============
État                               erreurs DRC
=================================  ============
``gen0`` (avant placement)                    0
après placement                             204
après restauration des angles            **0**
=================================  ============

Le placement introduisait donc la totalité des erreurs — 107 `clearance`,
84 `solder_mask_bridge`, 13 `shorting_items` — et le routage en était innocent
de bout en bout.

**Restaurer plutôt qu'imposer.** Une première version donnait à chaque pad
l'angle de son footprint ; elle ne corrigeait rien ici (le footprint n'est pas
pivoté) et aurait détruit les pads dont la bibliothèque déclare légitimement une
rotation propre. On recopie donc l'angle de la source, apparié par référence de
boîtier et numéro de pad.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kicad-tools" / "src"))

from tools import placement  # noqa: E402

_SOURCE = """(kicad_pcb
  (footprint "Package_QFP:LQFP-48"
    (property "Reference" "U2")
    (at 128.0 108.8)
    (pad "25" smd roundrect (at 4.1625 2.75) (size 1.475 0.3))
    (pad "26" smd roundrect (at 4.1625 2.25) (size 1.475 0.3))
  )
)"""

_APRES_WRITER = """(kicad_pcb
  (footprint "Package_QFP:LQFP-48"
    (property "Reference" "U2")
    (at 115.1657 117.0828 0)
    (pad "25" smd roundrect (at 4.1625 2.75 90) (size 1.475 0.3))
    (pad "26" smd roundrect (at 4.1625 2.25 90) (size 1.475 0.3))
  )
)"""


def test_l_angle_ajoute_par_le_writer_est_retire():
    """Le cas mesuré : 90° collé à des pads que la source déclare sans angle."""
    obtenu, n = placement.restore_pad_angles(_SOURCE, _APRES_WRITER)

    assert n == 2
    assert "(at 4.1625 2.75)" in obtenu
    assert "(at 4.1625 2.25)" in obtenu
    assert "90)" not in obtenu.split("(pad")[1]


def test_un_angle_legitime_de_la_source_est_conserve():
    """Restaurer, pas imposer — une rotation propre de bibliothèque survit."""
    source = ('(kicad_pcb (footprint "X" (property "Reference" "J1") (at 0 0)\n'
              '  (pad "1" smd roundrect (at 1 2 45) (size 1 2))))')
    apres = ('(kicad_pcb (footprint "X" (property "Reference" "J1") (at 5 5 90)\n'
             '  (pad "1" smd roundrect (at 1 2 135) (size 1 2))))')

    obtenu, n = placement.restore_pad_angles(source, apres)

    assert n == 1
    assert "(at 1 2 45)" in obtenu


def test_no_op_quand_le_writer_n_a_rien_change():
    obtenu, n = placement.restore_pad_angles(_SOURCE, _SOURCE)

    assert n == 0
    assert obtenu == _SOURCE


def test_les_positions_et_tailles_ne_sont_jamais_modifiees():
    """On ne touche qu'au troisième terme du (at ...)."""
    obtenu, _ = placement.restore_pad_angles(_SOURCE, _APRES_WRITER)

    assert "(size 1.475 0.3)" in obtenu
    assert "4.1625 2.75" in obtenu and "4.1625 2.25" in obtenu
    # La position du boîtier, elle, reste celle du placement.
    assert "(at 115.1657 117.0828 0)" in obtenu


def test_pad_absent_de_la_source_est_laisse_tel_quel():
    """Un pad inconnu de la source n'est pas une raison pour inventer."""
    apres = ('(kicad_pcb (footprint "X" (property "Reference" "U2") (at 0 0)\n'
             '  (pad "99" smd roundrect (at 1 2 90) (size 1 2))))')

    obtenu, n = placement.restore_pad_angles(_SOURCE, apres)

    assert n == 0
    assert "(at 1 2 90)" in obtenu


def test_source_vide():
    obtenu, n = placement.restore_pad_angles("(kicad_pcb)", _APRES_WRITER)

    assert n == 0
    assert obtenu == _APRES_WRITER

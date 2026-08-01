"""L'angle absolu d'un pad doit valoir : rotation du boîtier + angle de la source.

Le writer du placement se trompe dans les DEUX sens, mesuré le 2026-08-01 en
Docker sur `examples/stm32-validation`, sur deux tirages du même board :

===========  ==================  ==================  =========
Tirage       rotation boîtier    angle des pads      verdict
===========  ==================  ==================  =========
1                           0°   90° (**en trop**)   204 err.
2                         270°   absent (**manque**) 204 err.
===========  ==================  ==================  =========

La source ``gen0`` déclare, elle, des pads **sans angle** sur un boîtier non
pivoté — conforme au footprint officiel KiCad ``LQFP-48_7x7mm_P0.5mm``.

Les pads 25-27 forment une colonne verticale au pas de 0,5 mm et mesurent
1,475 × 0,3 mm. Dès que leur orientation ne correspond pas à celle du boîtier,
leur grand axe bascule le long de la colonne et les voisins se recouvrent d'un
millimètre. Les positions, elles, sont toujours correctes : c'est l'angle seul
qui est corrompu.

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

**La règle unifie les deux cas** : ``absolu = rotation_boîtier + relatif_source``,
apparié par référence de boîtier et numéro de pad. Vérifiée à 204 → 0 sur chacun
des deux tirages.

Deux versions antérieures ont échoué, chacune sur un seul cas : « angle = rotation
du boîtier » ne corrigeait pas le tirage 1 (boîtier non pivoté), et « recopier
l'angle de la source » ne corrigeait pas le tirage 2 (boîtier pivoté). Il fallait
les deux termes.

Un pad dont la bibliothèque déclare une rotation propre la conserve — elle est
ajoutée à celle du boîtier, jamais écrasée.
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


def test_boitier_non_pivote_angle_en_trop_retire():
    """Cas 1 mesuré : footprint à 0°, writer colle 90° aux pads."""
    obtenu, n = placement.restore_pad_angles(_SOURCE, _APRES_WRITER)

    assert n == 2
    assert "(at 4.1625 2.75)" in obtenu
    assert "(at 4.1625 2.25)" in obtenu
    assert "90)" not in obtenu.split("(pad")[1]


def test_boitier_pivote_angle_manquant_ajoute():
    """Cas 2 mesuré : footprint à 270°, pads SANS angle → formes non tournées.

    Les deux corruptions sont symétriques et se corrigent par la même règle :
    angle absolu = rotation du boîtier + angle relatif de la source.
    """
    apres = """(kicad_pcb
  (footprint "Package_QFP:LQFP-48"
    (property "Reference" "U2")
    (at 117.68 111.55 270)
    (pad "25" smd roundrect (at 4.1625 2.75) (size 1.475 0.3))
    (pad "26" smd roundrect (at 4.1625 2.25) (size 1.475 0.3))
  )
)"""

    obtenu, n = placement.restore_pad_angles(_SOURCE, apres)

    assert n == 2
    assert "(at 4.1625 2.75 270)" in obtenu
    assert "(at 4.1625 2.25 270)" in obtenu


def test_un_angle_legitime_de_la_source_est_conserve():
    """Restaurer, pas imposer — une rotation propre de bibliothèque survit."""
    source = ('(kicad_pcb (footprint "X" (property "Reference" "J1") (at 0 0)\n'
              '  (pad "1" smd roundrect (at 1 2 45) (size 1 2))))')
    apres = ('(kicad_pcb (footprint "X" (property "Reference" "J1") (at 5 5 90)\n'
             '  (pad "1" smd roundrect (at 1 2 135) (size 1 2))))')

    obtenu, n = placement.restore_pad_angles(source, apres)

    # Le writer avait vu juste : 90 (boîtier) + 45 (source) = 135 absolu.
    # Rien à corriger — et surtout, la rotation propre du pad n'est pas écrasée.
    assert n == 0
    assert "(at 1 2 135)" in obtenu


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

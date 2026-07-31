"""L'angle d'un pad est ABSOLU en repère board : il doit suivre le boîtier.

Dans le format ``.kicad_pcb``, la troisième valeur du ``(at x y angle)`` d'un pad
est son orientation **en repère board** — elle inclut déjà celle du footprint.
Un pad sans token d'angle vaut donc 0°, même sur un boîtier pivoté.

Quand le placement pivote un composant, les POSITIONS des pads tournent, mais
leurs FORMES restent à 0°. Sur un LQFP-48 pivoté de −90°, une rangée de pads
longs de 1,475 mm se retrouve alignée selon son grand axe au pas de 0,5 mm : les
voisins se recouvrent d'un millimètre.

Preuve arithmétique relevée dans le rapport DRC officiel, entre deux pads
distants de 3 pas : ``actual 0.0250 mm``, soit exactement ``1,5 − 1,475``.
L'encombrement pris en compte est celui d'AVANT rotation.

Chaîne mesurée le 2026-08-01, Docker, board STM32 :

===============================  =======  ============
Board                            pistes   erreurs DRC
===============================  =======  ============
``gen0`` (avant placement)             0            0
``tirage1`` (après placement)          0          204
après ``normalize_pad_angles``         0        **0**
===============================  =======  ============

Le placement introduisait donc la TOTALITÉ des erreurs, sur un board sans une
seule piste — le routage en était innocent de bout en bout.

Le correctif ne touche ni le placement ni sa méthode : positions, rotations et
stratégie sont inchangées. C'est une réparation de sérialisation.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kicad-tools" / "src"))

from tools import placement  # noqa: E402

_PIVOTE = """(kicad_pcb
  (footprint "Package_QFP:LQFP-48"
    (at 128.0 108.8 -90)
    (pad "1" smd roundrect (at -4.1625 -2.75) (size 1.475 0.3))
    (pad "13" smd roundrect (at -2.75 4.1625) (size 0.3 1.475))
  )
)"""

_DROIT = """(kicad_pcb
  (footprint "Capacitor_SMD:C_0805"
    (at 120.0 110.0)
    (pad "1" smd roundrect (at -0.9 0) (size 1.0 1.45))
  )
)"""


def test_les_pads_d_un_boitier_pivote_recoivent_son_angle():
    obtenu, n = placement.normalize_pad_angles(_PIVOTE)

    assert n == 2
    assert "(at -4.1625 -2.75 -90)" in obtenu
    assert "(at -2.75 4.1625 -90)" in obtenu
    # La rotation du footprint elle-même n'est pas touchée.
    assert "(at 128.0 108.8 -90)" in obtenu


def test_un_boitier_non_pivote_n_est_pas_touche():
    """Le cas le plus fréquent doit rester un no-op strict."""
    obtenu, n = placement.normalize_pad_angles(_DROIT)

    assert n == 0
    assert obtenu == _DROIT


def test_un_pad_qui_porte_deja_un_angle_est_laisse_tel_quel():
    """On ne réécrit que ce qui manque — jamais une valeur existante."""
    texte = ('(kicad_pcb (footprint "X" (at 10 10 90)\n'
             '  (pad "1" smd roundrect (at 1 2 45) (size 1 2))))')

    obtenu, n = placement.normalize_pad_angles(texte)

    assert n == 0
    assert "(at 1 2 45)" in obtenu


def test_les_tailles_de_pad_ne_sont_jamais_modifiees():
    """On corrige l'orientation, jamais la géométrie déclarée."""
    obtenu, _ = placement.normalize_pad_angles(_PIVOTE)

    assert "(size 1.475 0.3)" in obtenu
    assert "(size 0.3 1.475)" in obtenu


def test_board_sans_footprint():
    texte = "(kicad_pcb (segment (start 0 0) (end 1 1)))"

    obtenu, n = placement.normalize_pad_angles(texte)

    assert n == 0
    assert obtenu == texte

"""Re-placer un board DEJA place ne doit pas corrompre les angles de pads.

⚠️ Trouve le 2026-09-20 en rejouant le banc depuis des placements versionnes.
Sur le board PLACE, sans une piste, kicad-cli comptait 205 erreurs — 84
`shorting_items`, 84 `solder_mask_bridge`, 36 `clearance` — dont 168 items sur
U1, le LQFP-48. La signature exacte du defaut « angles de pads » du 2026-08-01.

`restore_pad_angles` applique `angle = rotation du boitier + angle RELATIF de
la source`. Mais `_pad_angles` rendait l angle DECLARE par la source, qui est
ABSOLU dans un `.kicad_pcb`. Tant que la source sort de gen_pcb (boitier a 0°),
absolu = relatif et tout va bien. Des que la source est un board deja place,
boitier pivote, la rotation est comptee DEUX FOIS.

Le motif mesure le dit sans ambiguite :

    boitier source a 90° ou 270°  -> ECHEC   carte-05 (270), 07 (270), 09 (90), 10 (270)
    boitier source a 0° ou 180°   -> succes  carte-04 (180), 06 (0), 08 (180)

(180° compte deux fois laisse un pad rectangulaire identique ; 90° le couche
sur ses voisins au pas de 0,5 mm.)

Ce n est pas qu un artefact de banc : le RE-TIRAGE de l orchestrateur renvoie
au placement le board du cache, DEJA place. La boucle censee sauver une carte
l empoisonnait une fois sur deux.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools import placement as P  # noqa: E402


def _board(rot_fp, angle_pad):
    rot = f" {rot_fp}" if rot_fp else ""
    ang = f" {angle_pad}" if angle_pad is not None else ""
    return (
        '(kicad_pcb\n'
        f'\t(footprint "Package_QFP:LQFP-48"\n\t\t(at 100 100{rot})\n'
        '\t\t(property "Reference" "U1")\n'
        f'\t\t(pad "25" smd roundrect (at 4.1625 2.75{ang}) (size 1.475 0.3))\n'
        f'\t\t(pad "26" smd roundrect (at 4.1625 2.25{ang}) (size 1.475 0.3))\n'
        '\t)\n)\n')


def _angles(texte):
    return [m.group(1) for m in re.finditer(r'\(pad "[^"]+" smd roundrect \(at [-\d.]+ [-\d.]+ ?([-\d.]*)\)', texte)]


class TestAngleRelatifDeLaSource:
    def test_source_non_pivotee_inchangee(self):
        assert P._pad_angles(_board(0, None))[("U1", "25")] in (None, 0.0)

    def test_source_pivotee_270_pads_270_vaut_relatif_zero(self):
        assert (P._pad_angles(_board(270, 270))[("U1", "25")] or 0.0) == 0.0

    def test_un_angle_propre_au_pad_est_conserve(self):
        # Boitier a 90°, pad declare a 135° absolu -> 45° relatif.
        assert P._pad_angles(_board(90, 135))[("U1", "25")] == 45.0


class TestReplacementDUnBoardDejaPlace:
    def test_source_a_270_replacee_a_90(self):
        # Le writer a laisse n importe quoi (ici 0) : on attend 90 = 90 + 0.
        texte, n = P.restore_pad_angles(_board(270, 270), _board(90, None))
        assert _angles(texte) == ["90", "90"], texte
        assert n == 2

    def test_source_a_270_replacee_a_270_ne_double_pas(self):
        # Le defaut : 270 + 270 = 180 — pads couches sur leurs voisins.
        texte, _ = P.restore_pad_angles(_board(270, 270), _board(270, 0))
        assert _angles(texte) == ["270", "270"], texte

    def test_source_a_90_replacee_a_0(self):
        texte, _ = P.restore_pad_angles(_board(90, 90), _board(0, 90))
        assert _angles(texte) == ["", ""], texte

    def test_cas_historique_intact_source_gen_pcb(self):
        # 2026-08-01 : source a 0° sans angle, writer ajoute 90 a tort.
        texte, n = P.restore_pad_angles(_board(0, None), _board(0, 90))
        assert _angles(texte) == ["", ""] and n == 2

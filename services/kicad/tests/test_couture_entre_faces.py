"""Deux plans d un seul tenant, sur deux faces, doivent etre COUSUS ensemble.

⚠️ Mesure du 2026-09-01, board livre de `nucleo-f401` — 98 %, 0 erreur, et UNE
connexion manquante que le rapport `kicad-cli` nomme sans ambiguite :

    Zone [GND] on F.Cu, priority 0   <->   Zone [GND] on B.Cu, priority 0

Ce ne sont pas des broches : ce sont LES DEUX PLANS DE MASSE qui ne se touchent
nulle part. Meme signature sur `stm32-30` et `stm32-100`, entre deux ilots
d une meme face.

CAUSE. `_stitch_zones` (tools/routing_pcbnew_runner.py) ecarte toute face d un
seul tenant :

    if total < 2:
        continue   # plan d un seul tenant : rien a recoudre

Vrai pour une face prise seule — un ilot unique n a rien a recoudre EN LUI-MEME.
Faux des que le net vit sur PLUSIEURS couches : F.Cu et B.Cu ont chacun un ilot,
donc chacun est ecarte, donc aucun via ne les relie. La couture savait joindre
deux ilots d une meme face, jamais deux faces entre elles.

⚠️ Je decrivais cette carte comme « une broche GND piegee sous un boitier
fine-pitch ». C etait faux : je l avais deduit du message d une garde au lieu
de lire le rapport DRC. Sur les quatre cartes incompletes, UNE SEULE porte une
broche piegee (`stm32-60`, `Pad 8 [GND] of U1`) ; les trois autres sont des
plans non cousus.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as RUN  # noqa: E402


class TestDecisionDeCoudre:
    def test_deux_ilots_sur_une_face_se_cousent(self):
        assert RUN._faut_coudre(ilots_sur_la_couche=2, couches_du_net=1) is True

    def test_un_ilot_sur_une_face_UNIQUE_ne_se_coud_pas(self):
        # Rien a relier : un plan d un seul tenant sur une carte a une couche.
        assert RUN._faut_coudre(ilots_sur_la_couche=1, couches_du_net=1) is False

    def test_un_ilot_par_face_sur_DEUX_faces_SE_COUD(self):
        # ⚠️ LE CAS `nucleo-f401`. Chaque face est d un seul tenant, donc
        # chacune etait ecartee — et les deux plans restaient etrangers.
        assert RUN._faut_coudre(ilots_sur_la_couche=1, couches_du_net=2) is True

    def test_zero_ilot_ne_se_coud_jamais(self):
        assert RUN._faut_coudre(ilots_sur_la_couche=0, couches_du_net=2) is False


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8")

    def test_la_condition_aveugle_a_disparu(self):
        i = self.SOURCE.index("def _stitch_zones(")
        corps = self.SOURCE[i:i + 5000]
        assert "if total < 2:" not in corps, (
            "la couture ecarte encore les faces d un seul tenant")

    def test_la_decision_passe_par_la_fonction(self):
        i = self.SOURCE.index("def _stitch_zones(")
        corps = self.SOURCE[i:i + 5000]
        assert "_faut_coudre(" in corps

    def test_le_nombre_de_couches_du_net_est_calcule(self):
        i = self.SOURCE.index("def _stitch_zones(")
        corps = self.SOURCE[i:i + 5000]
        assert "couches_du_net" in corps

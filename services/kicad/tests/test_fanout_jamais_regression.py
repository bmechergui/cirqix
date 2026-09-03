"""Le fanout promet « reparation, jamais regression » — il doit le PROUVER.

Mesure du 2026-08-23, board STM32, meme chemin de bout en bout :

    sans fanout : 4 connexions manquantes | 27 violations, 0 erreur
    avec fanout : 1 connexion manquante   | 35 violations, 6 ERREURS

Les erreurs ajoutees comprennent DEUX `shorting_items` entre GND et +3.3V —
des courts-circuits reels — plus un `solder_mask_bridge` et une clearance
mesuree a 0,0181 mm pour 0,2 exige.

Le via d echappement est pose a l aveugle : la direction de sortie pointe a
l oppose du centre du boitier, sans verifier ce qui se trouve sur le trajet.
Sur une carte dense il traverse une piste d alimentation.

⚠️ Le fanout ne se declenche PAS dans l ordre de production actuel (aucune
broche orpheline), donc ce defaut n a jamais nui. Il est neanmoins arme : la
promesse de sa docstring n etait tenue que par chance.

La garde compare le board AVANT et APRES, et rend l original des que le compte
d ERREURS augmente. Echanger une connexion manquante contre un court-circuit
est un mauvais marche : le premier se voit au DRC et bloque la commande, le
second peut partir en fabrication.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _rapport(n_erreurs: int, n_manquantes: int = 1) -> dict:
    return {
        "violations": [{"severity": "error", "type": "shorting_items"}] * n_erreurs,
        "unconnected_items": [
            {
                "items": [
                    {"description": "Pad 8 [GND] of U2 on F.Cu"},
                    {"description": "Zone [GND] on F.Cu, priority 0"},
                ]
            }
        ]
        * n_manquantes,
    }


class TestComptageDesErreurs:
    def test_compte_les_erreurs_et_ignore_les_avertissements(self):
        rapport = {
            "violations": [
                {"severity": "error"},
                {"severity": "warning"},
                {"severity": "error"},
            ]
        }
        assert routing_router._compte_erreurs(rapport) == 2

    def test_un_rapport_vide_ne_compte_rien(self):
        assert routing_router._compte_erreurs({}) == 0


class TestGarde:
    def test_le_board_est_rendu_intact_si_les_erreurs_augmentent(self, monkeypatch):
        avant, apres = b"AVANT", b"APRES"
        rapports = iter([_rapport(0), _rapport(2)])
        monkeypatch.setattr(routing_router, "_rapport_drc", lambda _b: next(rapports))
        monkeypatch.setattr(routing_router, "_pose_les_vias_d_echappement",
                            lambda _b, _p: apres)
        assert routing_router._fanout_pads_isolees(avant) == avant

    def test_la_reparation_est_conservee_si_rien_n_empire(self, monkeypatch):
        avant, apres = b"AVANT", b"APRES"
        rapports = iter([_rapport(1), _rapport(1)])
        monkeypatch.setattr(routing_router, "_rapport_drc", lambda _b: next(rapports))
        monkeypatch.setattr(routing_router, "_pose_les_vias_d_echappement",
                            lambda _b, _p: apres)
        assert routing_router._fanout_pads_isolees(avant) == apres

    def test_rien_a_reparer_ne_declenche_aucun_travail(self, monkeypatch):
        monkeypatch.setattr(routing_router, "_rapport_drc", lambda _b: {})

        def jamais(_b, _p):
            raise AssertionError("le fanout ne doit pas s executer sans broche isolee")

        monkeypatch.setattr(routing_router, "_pose_les_vias_d_echappement", jamais)
        assert routing_router._fanout_pads_isolees(b"BOARD") == b"BOARD"

"""Poser du cuivre dans une zone remplie oblige a la recouler.

⚠️ `_relier_gnd_avant_routage` (etape ③) s execute APRES
`_fill_zones(_add_ground_planes(etendu))` : elle ajoute une piste et un via A
L INTERIEUR de zones deja remplies, puis rend le board tel quel. Les polygones
remplis decrivent donc un cuivre qui n existe plus tel qu il est ecrit.

C est le SEUL endroit de la chaine ou du cuivre est modifie sans remplissage
derriere. Le chemin post-routage, lui, recoule bien : `_reposer_vias_reserves`
est suivi de `_add_ground_planes` puis `_fill_zones`.

La regle est posee dans CLAUDE.md depuis le 2026-08-23 : « un plan non rempli
n est qu un contour, dont le routeur ne tient aucun compte » — et un plan
rempli PERIME est pire qu un contour, puisqu il affirme quelque chose de faux.

⚠️ CE QUE CE TEST NE PROUVE PAS. Une regression est apparue le 2026-09-01 sur
`esp32-baseline` — pcbnew rend `exit -11` a l import de session Specctra, deux
fois, la ou le temoin n avait jamais plante — et l etape ③ s y executait pour
la premiere fois. Ce remplissage manquant est un candidat serieux, PAS une
cause etablie : la mesure qui trancherait exige le conteneur, indisponible a
l ecriture de ce test. On corrige ici un defaut avere par la regle du projet ;
si la regression survit, la cause est ailleurs et il faudra le dire.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestRemplissage:
    def _cibler(self, monkeypatch, appels):
        monkeypatch.setattr(R, "_pads_gnd_fine_pitch",
                            lambda pcb, nets: [("U1", "8")])
        monkeypatch.setattr(R, "_rapport_drc", lambda pcb: {})
        monkeypatch.setattr(R, "_compte_erreurs", lambda rapport: 0)

        def faux_fill(board):
            appels.append(board)
            return board + b"[REMPLI]"

        monkeypatch.setattr(R, "_fill_zones", faux_fill)

        def faux_pcbnew(args):
            Path(args["output"]).write_bytes(b"(kicad_pcb RELIE)")
            Path(args["result"]).write_text('{"escaped": 1, "renonces": 0}')

        monkeypatch.setattr(R, "_run_pcbnew_operation", faux_pcbnew)

    def test_le_board_relie_est_RECOULE(self, monkeypatch):
        appels = []
        self._cibler(monkeypatch, appels)
        sortie = R._relier_gnd_avant_routage(b"(kicad_pcb)", {"GND"})
        assert appels, ("le cuivre est pose dans des zones remplies sans "
                        "qu elles soient recoulees")
        assert sortie.endswith(b"[REMPLI]")

    def test_rien_n_est_recoule_si_aucune_cible(self, monkeypatch):
        # Sans broche a relier, le board n est pas touche : le recouler serait
        # un travail inutile sur le chemin le plus frequent.
        appels = []
        self._cibler(monkeypatch, appels)
        monkeypatch.setattr(R, "_pads_gnd_fine_pitch", lambda pcb, nets: [])
        recu = b"(kicad_pcb)"
        assert R._relier_gnd_avant_routage(recu, {"GND"}) is recu
        assert not appels

    def test_le_verdict_DRC_porte_sur_le_board_RECOULE(self, monkeypatch):
        # Comparer les erreurs d un board aux zones perimees jugerait un board
        # que personne ne recevra.
        appels, vus = [], []
        self._cibler(monkeypatch, appels)
        monkeypatch.setattr(R, "_rapport_drc", lambda pcb: vus.append(pcb) or {})
        R._relier_gnd_avant_routage(b"(kicad_pcb)", {"GND"})
        assert any(v.endswith(b"[REMPLI]") for v in vus), (
            "le DRC juge un board dont les zones sont perimees")

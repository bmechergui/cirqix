"""Deposer le board a CHAQUE etape, pour inspection dans KiCad.

⚠️ Demande de l utilisateur le 2026-09-01 : « je veux les cartes ici, je veux
verifier avec toi — pour chaque carte, chaque etape : plan, colle, routage
GND, et apres chaque etape ».

Sept depots jalonnent la chaine, dans l ordre ou elle travaille :

    01 plan_coule       le plan de masse coule ET rempli
    02 gnd_lie          apres la liaison des broches GND (etape ③)
    03 route            ce que le routeur rend, avant tout post-traitement
    04 vias_reposes     apres la repose des vias reserves
    05 plans_recoules   apres re-coulee et remplissage
    06 cousu            apres fanout, couture des pastilles et des ilots
    (le final est deja ecrit par le banc)

⚠️ DESACTIVE PAR DEFAUT. `CIRQIX_DUMP_ETAPES` vide, la chaine de production
n ecrit pas un octet de plus. Un outil d inspection ne doit rien coûter a ce
qu il observe.

⚠️ IL NE LEVE JAMAIS. Un vidage qui casserait un routage de 40 minutes
coûterait infiniment plus qu il ne rapporte : toute erreur est journalisee en
debug et avalee.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestDesactiveParDefaut:
    def test_sans_variable_rien_n_est_ecrit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(R, "_DOSSIER_ETAPES", "")
        R._deposer_etape("plan_coule", b"(kicad_pcb)")
        assert list(tmp_path.iterdir()) == []

    def test_un_board_vide_n_ecrit_rien(self, tmp_path, monkeypatch):
        monkeypatch.setattr(R, "_DOSSIER_ETAPES", str(tmp_path))
        R._deposer_etape("plan_coule", b"")
        assert list(tmp_path.iterdir()) == []


class TestDepot:
    def test_le_board_est_ecrit_numerote(self, tmp_path, monkeypatch):
        monkeypatch.setattr(R, "_DOSSIER_ETAPES", str(tmp_path))
        monkeypatch.setattr(R, "_NUMERO_ETAPE", [0])
        R._deposer_etape("plan_coule", b"(kicad_pcb A)")
        R._deposer_etape("gnd_lie", b"(kicad_pcb B)")
        noms = sorted(f.name for f in tmp_path.iterdir())
        assert noms == ["01_plan_coule.kicad_pcb", "02_gnd_lie.kicad_pcb"]
        assert (tmp_path / noms[0]).read_bytes() == b"(kicad_pcb A)"

    def test_il_ne_leve_jamais(self, monkeypatch):
        # Un chemin impossible ne doit pas casser un routage de 40 minutes.
        monkeypatch.setattr(R, "_DOSSIER_ETAPES", "\x00chemin/impossible")
        R._deposer_etape("plan_coule", b"(kicad_pcb)")


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_les_six_etapes_sont_jalonnees(self):
        for nom in ("plan_coule", "gnd_lie", "route", "vias_reposes",
                    "plans_recoules", "cousu"):
            assert '_deposer_etape("%s"' % nom in self.SOURCE, nom

    def test_le_depot_suit_l_etape_qu_il_nomme(self):
        # ⚠️ Un depot pose au mauvais endroit montrerait un board qui n est pas
        # celui de l etape : pire qu aucun depot, car il tromperait la lecture.
        i = self.SOURCE.index('_deposer_etape("plan_coule"')
        assert "_fill_zones(_add_ground_planes(" in self.SOURCE[i - 200:i]
        j = self.SOURCE.index('_deposer_etape("gnd_lie"')
        assert "_relier_gnd_avant_routage(" in self.SOURCE[j - 200:j]

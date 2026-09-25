"""Le routage PRIORITAIRE est câblé dans `route_auto`, dans le bon ordre.

D-2026-09-25-a : avant Freerouting, les liaisons critiques (quartz, charges,
découplages) sont posées par des pistes courtes, puis PROTÉGÉES avec la liaison
GND. Désactivé par défaut (réglage `routage_prioritaire`) jusqu'à la mesure A/B,
et ALTERNÉ un tirage sur deux : une piste protégée mal posée reviendrait à
chaque tirage, sans qu'aucun ne puisse la rattraper (risque relevé par les deux
critiques du 2026-09-25).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402
from tools import routing_pcbnew_runner as RUN  # noqa: E402


def _code(fonction) -> str:
    return "\n".join(l.split("#")[0] for l in inspect.getsource(fonction).splitlines())


def _reglage(valeur):
    from tools import reglages_banc
    original = reglages_banc.reglage
    reglages_banc.reglage = lambda nom, defaut=None: valeur if nom == "routage_prioritaire" else defaut
    return original


class TestAlternance:
    def test_desactive_par_defaut(self):
        assert R._passe_prioritaire_au_tirage(1) is False

    def test_un_tirage_sur_deux_quand_active(self):
        from tools import reglages_banc
        original = _reglage(True)
        try:
            assert [R._passe_prioritaire_au_tirage(r) for r in (1, 2, 3, 4)] == [True, False, True, False]
        finally:
            reglages_banc.reglage = original


class TestCablage:
    def test_ordre_reservations_passe_liaison_gnd_protection(self):
        code = _code(R.route_auto)
        i_resa = code.index("_VIAS_RESERVES = _reservations_du_tirage(")
        i_avant = code.index("avant_liaison = etendu")
        i_passe = code.index("_relier_liaisons_critiques(")
        i_gnd = code.index("_relier_gnd_avant_routage(etendu")
        i_prot = code.index("_ajouter_aux_pistes_protegees(etendu)")
        assert i_resa < i_avant < i_passe < i_gnd < i_prot
        assert "_passe_prioritaire_au_tirage(rang_au_palier)" in code

    def test_une_pastille_reliee_perd_sa_reservation(self):
        """Une pastille, un propriétaire : une broche reliée en priorité ne garde
        pas son via d'échappement réservé."""
        vias = [{"ref": "U1", "pad": "1", "via_x": 1, "via_y": 2},
                {"ref": "U1", "pad": "9", "via_x": 3, "via_y": 4}]
        restants = R._sans_les_pastilles_reliees(vias, {("U1", "1"), ("C1", "1")})
        assert [(v["ref"], v["pad"]) for v in restants] == [("U1", "9")]

    def test_le_runner_expose_l_operation(self):
        assert "relier_liaisons" in inspect.getsource(RUN.main)

    def test_le_runner_ne_relie_jamais_deux_nets_differents(self):
        code = _code(RUN._relier_liaisons)
        assert "netcode != int(pb.GetNetCode())" in code
        assert "IsOnLayer" in code   # une seule face, jamais de via
        assert "PCB_VIA" not in code

    def test_la_passe_ne_peut_qu_ameliorer(self):
        """Nets perdus, ou board aggravé après recoulée : on garde le board reçu."""
        code = _code(R._relier_liaisons_critiques)
        assert "_nets_du_board(" in code and "_aggrave_le_board(" in code
        assert "_fill_zones(" in code
        assert code.index("_fill_zones(") < code.index("_aggrave_le_board(")

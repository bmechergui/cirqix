"""Repli GND CIBLE : seule la broche orpheline et ses voisines GND les plus
proches sont rendues au routeur — le plan garde tout le reste.

Mesure du 2026-09-11 sur carte-08 et carte-10 (60 tirages rates) : le net
incomplet est GND dans 100 % des cas, a cause d UNE broche orpheline du plan
(aucune sortie laterale, pastille trop etroite pour un via). Le repli global
re-route TOUT le GND en pistes sur deux couches et perd 16 liaisons :
« repli GND REFUSE : (0 erreur, 16 manquante) ne fait pas mieux que
(0 erreur, 2 manquante) ». Il n a jamais ete retenu (11 replis, 0 retenu le
2026-09-02). Le repli cible ne demande au routeur qu une piste courte.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402

_BOARD = b"""(kicad_pcb (version 20240108) (generator "pcbnew")
  (net 0 "")
  (net 1 "GND")
  (net 2 "SIG")
  (footprint "C_0402" (layer "F.Cu") (at 10 10 90)
    (property "Reference" "C1" (at 0 -1) (layer "F.SilkS"))
    (pad "1" smd roundrect (at -0.5 0) (size 0.6 0.5) (layers "F.Cu") (net 2 "SIG"))
    (pad "2" smd roundrect (at 0.5 0) (size 0.6 0.5) (layers "F.Cu") (net 1 "GND"))
  )
  (footprint "C_0402" (layer "F.Cu") (at 12 10)
    (property "Reference" "C2" (at 0 -1) (layer "F.SilkS"))
    (pad "1" smd roundrect (at -0.5 0) (size 0.6 0.5) (layers "F.Cu") (net 2 "SIG"))
    (pad "2" smd roundrect (at 0.5 0) (size 0.6 0.5) (layers "F.Cu") (net 1 "GND"))
  )
  (footprint "C_0402" (layer "F.Cu") (at 40 40)
    (property "Reference" "C3" (at 0 -1) (layer "F.SilkS"))
    (pad "2" smd roundrect (at 0.5 0) (size 0.6 0.5) (layers "F.Cu") (net "GND"))
  )
  (footprint "LQFP" (layer "F.Cu") (at 10.2 10.8)
    (property "Reference" "U1" (at 0 -1) (layer "F.SilkS"))
    (pad "1" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "2" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "3" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "4" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "5" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "6" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "7" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "8" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "9" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "10" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "11" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "12" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "13" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "14" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "15" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 2 "SIG"))
    (pad "16" smd rect (at 0 0) (size 0.3 1) (layers "F.Cu") (net 1 "GND"))
  )
  (footprint "J" (layer "F.Cu") (at 10.5 11)
    (property "Reference" "J1" (at 0 -1) (layer "F.SilkS"))
    (pad "1" thru_hole circle (at 0 0) (size 1.7 1.7) (drill 1) (layers "*.Cu") (net 1 "GND"))
  )
)"""

_DSN = """(network
    (net SIG
      (pins C1-1 C2-1)
    )
    (net GND
      (pins C1-2 C2-2 C3-2
        J1-1)
    )
  )"""


class TestPinsAGarder:
    def test_l_orpheline_et_sa_voisine_gnd_la_plus_proche(self):
        pins = R._pins_gnd_a_garder(_BOARD, [("C1", "2")], {"GND"}, voisines=1)
        assert pins == {"C1-2", "J1-1"}      # J1.1 (10.5,11) a 1,58 mm ; C2.2 (12.5,10) a 2,55 mm

    def test_deux_voisines(self):
        pins = R._pins_gnd_a_garder(_BOARD, [("C1", "2")], {"GND"}, voisines=2)
        assert pins == {"C1-2", "J1-1", "C2-2"}

    def test_la_rotation_du_boitier_est_appliquee(self):
        # C1 est tourne de 90 degres : sa broche 2 n est pas a (10.5, 10) mais sur l axe y.
        pos = R._positions_des_pastilles(_BOARD, {"GND"})
        x, y = pos[("C1", "2")]
        assert abs(x - 10) < 0.01 and abs(abs(y - 10) - 0.5) < 0.01

    def test_une_voisine_de_boitier_dense_passe_en_dernier(self):
        # U1.16 (LQFP, 16 pastilles) est la plus proche (0,85 mm) mais aussi dure d acces
        # que l orpheline : J1.1 puis C2.2 passent avant.
        pins = R._pins_gnd_a_garder(_BOARD, [("C1", "2")], {"GND"}, voisines=2)
        assert pins == {"C1-2", "J1-1", "C2-2"}
        pins = R._pins_gnd_a_garder(_BOARD, [("C1", "2")], {"GND"}, voisines=4)
        assert "U1-16" in pins

    def test_sans_orpheline_rien(self):
        assert R._pins_gnd_a_garder(_BOARD, [], {"GND"}) == set()

    def test_un_board_illisible_rend_vide(self):
        assert R._pins_gnd_a_garder(b"", [("C1", "2")], {"GND"}) == set()


class TestDsn:
    def test_seules_les_broches_gardees_restent_au_routeur(self):
        texte, n = R._strip_net_from_dsn(_DSN, "GND", garder_pins={"C1-2", "J1-1"})
        assert "(net GND (pins C1-2 J1-1))" in texte
        assert "C2-2" not in texte and "C3-2" not in texte
        assert n == 2                         # deux broches retirees, deux gardees
        assert "(pins C1-1 C2-1)" in texte    # SIG intact

    def test_sans_broche_gardee_le_comportement_historique_subsiste(self):
        texte, n = R._strip_net_from_dsn(_DSN, "GND")
        assert "(net GND" not in texte and n == 4


class TestCablage:
    def test_le_repli_cible_est_tente_avant_le_repli_global(self):
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(R.route_auto).splitlines())
        i_c = code.find("_repli_gnd_cible_iteratif(")
        i_g = code.find("_router_en_incluant_gnd(")
        assert i_c != -1 and i_g != -1 and i_c < i_g

    def test_le_repli_cible_n_est_pas_soumis_au_seuil_du_global(self):
        """Le seuil `_repli_gnd_vaut_le_coup` ne bride que le repli GLOBAL
        (10-17 min) : le cible (11 s) passe avant lui."""
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(R.route_auto).splitlines())
        i_c = code.find("_repli_gnd_cible_iteratif(")
        i_s = code.find("_repli_gnd_vaut_le_coup(")
        assert i_c != -1 and i_s != -1 and i_c < i_s

    def test_le_repli_cible_est_repete_tant_qu_il_referme(self, monkeypatch):
        appels = []
        boards = [b"b1", b"b2", b"b3"]
        bilans = {b"b0": (0, 6), b"b1": (0, 5), b"b2": (0, 4), b"b3": (0, 4)}
        orph = {b"b0": [("C1", "2"), ("C2", "2")], b"b1": [("C2", "2")], b"b2": [("C3", "2")], b"b3": [("C3", "2")]}
        monkeypatch.setattr(R, "_router_gnd_cible", lambda *a, **k: (appels.append(1), boards[len(appels) - 1])[1])
        monkeypatch.setattr(R, "_bilan_drc", lambda b: bilans[b])
        monkeypatch.setattr(R, "_rapport_drc", lambda b: b)
        monkeypatch.setattr(R, "_pads_isolees_du_plan", lambda rap: orph[rap])
        final, restantes = R._repli_gnd_cible_iteratif(b"e", None, 10.0, orph[b"b0"], b"b0")
        assert final == b"b2" and restantes == [("C3", "2")] and len(appels) == 3
        assert 2 <= R._REPLI_CIBLE_TOURS <= 6

    def test_l_empreinte_du_module_est_journalisee_au_chargement(self):
        src = Path(R.__file__).read_text(encoding="utf-8")
        assert "routing.py charge : empreinte" in src
        assert len(R._empreinte_du_module()) == 10

    def test_confier_au_plan_transmet_les_broches_gardees(self):
        code = inspect.getsource(R._confier_au_plan)
        assert "garder_pins=_PINS_GND_A_GARDER" in code

    def test_le_repli_cible_restaure_le_global(self):
        code = inspect.getsource(R._router_gnd_cible)
        assert "finally:" in code and "_PINS_GND_A_GARDER = " in code
        assert "_ZONES_LIBEREES = memoire_zones" in code

    def test_le_repli_cible_libere_autour_des_orphelines(self):
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(R._router_gnd_cible).splitlines())
        assert "_ZONES_LIBEREES = [positions[" in code


def test_les_objets_manquants_sont_nommes_sous_le_verdict_drc():
    """« GND incomplet » sans pastille orpheline peut etre deux ilots, un via
    borgne ou une piste : le journal doit nommer les objets, pas seulement le net."""
    src = Path(R.__file__).read_text(encoding="utf-8")
    i = src.index("pourcentage ramene a")
    assert '"  manquant : %s"' in src[i:i + 1200]

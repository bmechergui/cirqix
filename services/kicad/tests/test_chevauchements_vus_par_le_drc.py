"""Un chevauchement de courtyard que SEUL le DRC voit est repare avant de livrer.

⚠️ Rejeu du 2026-09-20 : carte-05 et carte-09 sortent a UNE erreur, la meme —
`courtyards_overlap` entre le regulateur U2 (SOT-223) et un passif voisin
(C12, R22). Le journal du placement : « 0 ERROR / 3 WARNING residuels » puis
« 1 conflit(s) apres 4 tirages — board livre en l etat ».

CAUSE, deja ecrite dans le code sans que rien n en decoule : `PlacementAnalyzer`
APPROXIME un courtyard par « pastilles + 0,5 mm », kicad-cli lit la vraie
geometrie `F.CrtYd`. Sur un SOT-223 le corps et sa languette debordent
largement des pastilles : l Inspecteur ne voit rien a reparer la ou le DRC
refuse la carte. Mesurer avec un instrument et juger avec un autre, c est se
rassurer sans rien garantir (lecon du 2026-08-27, non appliquee ici).

REGLE (generale, aucune carte nommee) : apres la DERNIERE etape qui deplace,
les paires `courtyards_overlap` du DRC sont reparees avec les VRAIES boites —
on deplace le composant non ancre au plus petit courtyard vers la case libre
la plus proche — et on ne garde le resultat que s il n aggrave rien.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools import placement as P  # noqa: E402


def _rapport(*violations):
    return {"violations": list(violations)}


def _v(type_, sev, a, b):
    return {"type": type_, "severity": sev,
            "items": [{"description": f"Footprint {a}"}, {"description": f"Footprint {b}"}]}


class TestPaires:
    def test_extrait_les_paires_de_courtyards_en_erreur(self):
        r = _rapport(_v("courtyards_overlap", "error", "C12", "U2"),
                     _v("silk_overlap", "warning", "R1", "R2"),
                     _v("courtyards_overlap", "warning", "R3", "R4"),
                     _v("clearance", "error", "C1", "C2"))
        assert P._paires_de_courtyards(r) == [("C12", "U2")]

    def test_rapport_vide_ou_illisible(self):
        assert P._paires_de_courtyards({}) == []
        assert P._paires_de_courtyards({"violations": [{"type": "courtyards_overlap",
                                                       "severity": "error", "items": []}]}) == []


class TestQuiBouge:
    AIRES = {"U2": 45.0, "C12": 2.4, "J1": 30.0}

    def test_le_plus_petit_non_ancre_bouge(self):
        assert P._choisir_le_mobile("C12", "U2", self.AIRES, ancres=set()) == "C12"
        assert P._choisir_le_mobile("U2", "C12", self.AIRES, ancres=set()) == "C12"

    def test_un_ancre_ne_bouge_jamais(self):
        assert P._choisir_le_mobile("C12", "U2", self.AIRES, ancres={"C12"}) == "U2"

    def test_deux_ancres_on_renonce(self):
        assert P._choisir_le_mobile("J1", "U2", self.AIRES, ancres={"J1", "U2"}) is None


class TestCablage:
    SOURCE = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_apres_la_derniere_etape_qui_deplace_avant_la_serigraphie(self):
        corps = self.SOURCE[self.SOURCE.index("def _auto_place_une_fois("):]
        dernier_filet = corps.rindex("_garder_dans_le_contour(out, conn, fixes_snap)")
        appel = corps.index("_reparer_chevauchements_du_drc(out,")
        serigraphie = corps.index("_degager_la_serigraphie(out)")
        assert dernier_filet < appel < serigraphie


BANC = RACINE / "examples" / "carte-05-capteur-i2c" / "expected" / "placement.kicad_pcb"


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli absent : se lance dans le conteneur")
class TestSurUnVraiBoard:
    def test_un_passif_pose_sur_le_regulateur_est_ecarte(self, tmp_path):
        pytest.importorskip("kicad_tools")
        if not BANC.is_file():
            pytest.skip("board du banc absent")
        from kicad_tools.schema.pcb import PCB
        f = tmp_path / "b.kicad_pcb"
        shutil.copy(BANC, f)
        pcb = PCB.load(str(f))
        par_ref = {fp.reference: fp for fp in pcb.footprints}
        u2_avant = tuple(par_ref["U2"].position)
        par_ref["C12"].position = u2_avant            # le defaut, reproduit
        pcb.save(str(f))
        assert P._compter_conflits_erreur(f) >= 1
        n = P._reparer_chevauchements_du_drc(f, ancres=[])
        assert n >= 1
        assert P._compter_conflits_erreur(f) == 0
        apres = {fp.reference: tuple(fp.position) for fp in PCB.load(str(f)).footprints}
        assert apres["U2"] == u2_avant, "le regulateur ne bouge pas : c est le passif qui s ecarte"

"""Le cluster POWER n existait pas — a cause d un POINT DECIMAL.

⚠️ Mesure du 2026-09-02, `nucleo-f401`. Les huit condensateurs de decouplage
sont a **24,5 · 43,8 · 51,5 · 58,3 · 58,7 · 62,5 · 62,8 · 68,7 mm** du MCU. Un
condensateur de decouplage doit etre a 2-3 mm de la broche qu il sert : au-dela,
l inductance de la piste annule son effet.

`detect_functional_clusters` ne rendait que 4 clusters — 3 INTERFACE et
1 DRIVER — et **aucun POWER**. Les capas n appartenant a rien,
`snap_cluster_members` n avait rien a rapprocher.

CAUSE. Le motif natif de `kicad-tools` est

    r"^(\\+|\\-)?\\d+V"          # +3V3, +5V, -12V

Il exige des chiffres IMMEDIATEMENT suivis d un `V`. Notre generateur ecrit
`+3.3V` : le point decimal fait echouer le motif. Mesure directe :

    +3.3V   reconnu_power = False      <- le rail principal de la carte
    GND     reconnu_ground = True
    VIN     reconnu_power = True

`+3V3` est pourtant LA convention KiCad, concue precisement pour eviter ce
point. Les capas, elles, etaient parfaitement identifiees — `is_bypass_cap`
rend `True` pour les huit. Ce n est donc ni la detection des composants ni le
snap qui echouait, mais le NOM DU NET.

Effet mesure de la normalisation, meme board :

    SANS : 4 clusters, aucun POWER
    AVEC : 5 clusters — POWER, ancre U1, plafond 3,0 mm, les 8 capas

⚠️ AUCUNE heuristique maison n est introduite : la detection reste
`detect_functional_clusters`, on lui donne seulement le nom que KiCad emploie.
Precedent exact dans le projet : `kct_route.py::_VCC_RENAME` renomme deja
`+3.3V` en `P3V3` pour contourner une classification de la meme lib.

⚠️ SUR UNE COPIE, IMPERATIVEMENT. Renommer les pins du modele charge
renommerait les nets du board ecrit derriere — un board dont les nets changent
de nom est un board casse. On ne normalise que pour la DETECTION.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import placement_bypass as PB  # noqa: E402


class TestNomDuRail:
    def test_le_cas_mesure(self):
        assert PB._nom_kicad_du_rail("+3.3V") == "+3V3"

    def test_un_rail_negatif(self):
        assert PB._nom_kicad_du_rail("-12.5V") == "-12V5"

    def test_sans_signe(self):
        assert PB._nom_kicad_du_rail("1.8V") == "1V8"

    def test_un_rail_DEJA_conforme_est_intact(self):
        # Idempotence : la normalisation ne doit pas se mordre la queue.
        assert PB._nom_kicad_du_rail("+3V3") == "+3V3"

    def test_un_rail_entier_est_intact(self):
        assert PB._nom_kicad_du_rail("+5V") == "+5V"

    def test_la_masse_est_intacte(self):
        assert PB._nom_kicad_du_rail("GND") == "GND"

    def test_un_net_de_signal_est_intact(self):
        assert PB._nom_kicad_du_rail("Net-(U1-Pad3)") == "Net-(U1-Pad3)"

    def test_un_nom_vide_ne_casse_rien(self):
        assert PB._nom_kicad_du_rail("") == ""

    def test_un_nom_qui_CONTIENT_un_rail_sans_l_etre_est_intact(self):
        # ⚠️ Le motif est ancre aux deux bouts : on ne bricole pas un nom
        # quelconque qui ressemblerait de loin a un rail.
        assert PB._nom_kicad_du_rail("VDD_3.3V_SENSE") == "VDD_3.3V_SENSE"


class _Pin:
    def __init__(self, net_name):
        self.net_name = net_name
        self.net = 1
        self.number = "1"


class _Comp:
    def __init__(self, ref, nets):
        self.reference = ref
        self.ref = ref
        self.pins = [_Pin(n) for n in nets]


class TestNonMutation:
    """⚠️ LA garde qui compte : le board ne doit JAMAIS etre renomme."""

    def test_les_composants_d_origine_gardent_leur_nom_de_net(self, monkeypatch):
        vus = {}

        def _faux_detect(composants):
            vus["noms"] = [p.net_name for c in composants for p in c.pins]
            return []

        monkeypatch.setattr(PB, "detect_functional_clusters", _faux_detect,
                            raising=False)
        origine = [_Comp("C1", ["+3.3V", "GND"])]
        PB._clusters_natifs(origine)

        # La detection a bien vu le nom NORMALISE...
        assert "+3V3" in vus["noms"]
        # ...et l original n a pas bouge.
        assert [p.net_name for p in origine[0].pins] == ["+3.3V", "GND"]

    def test_la_detection_recoit_bien_les_composants(self, monkeypatch):
        recus = {}
        monkeypatch.setattr(
            PB, "detect_functional_clusters",
            lambda c: recus.setdefault("n", len(list(c))) or [], raising=False)
        PB._clusters_natifs([_Comp("C1", ["+3.3V"]), _Comp("C2", ["+3.3V"])])
        assert recus["n"] == 2

    def test_un_composant_sans_pins_ne_casse_rien(self, monkeypatch):
        monkeypatch.setattr(PB, "detect_functional_clusters", lambda c: [],
                            raising=False)
        vide = _Comp("M1", [])
        assert PB._clusters_natifs([vide]) == []


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "placement_bypass.py").read_text(
        encoding="utf-8")

    def test_le_snap_passe_par_la_detection_normalisee(self):
        # ⚠️ Une regle correcte jamais appelee est indistinguable d une regle
        # absente. Le snap doit consommer `_clusters_natifs`, pas appeler
        # `detect_functional_clusters` directement.
        i = self.SOURCE.index("def snap_cluster_members(")
        corps = self.SOURCE[i:]
        assert "_clusters_natifs(" in corps

    def test_le_snap_n_appelle_plus_la_detection_BRUTE(self):
        i = self.SOURCE.index("def snap_cluster_members(")
        code = [l for l in self.SOURCE[i:].split(chr(10))
                if not l.strip().startswith("#")]
        appels = [l for l in code if "detect_functional_clusters(" in l]
        assert not appels, (
            "le snap contourne encore la normalisation : %s" % appels)

"""Un condensateur de découplage appartient au CI qu'il TOUCHE — et le snap
vise la BROCHE, pas le corps.

⚠️ MESURE DU 2026-09-10 sur `carte-05-capteur-i2c`, après que l'utilisateur a
regardé les vues et dit : « jusqu'à maintenant il n'y a ni placement ni routage
pro ici ». Il avait raison, et mes chiffres ne le voyaient pas.

DEUX DÉFAUTS EMPILÉS, dans le placement des découplages :

1. `detect_power_clusters` garde un `processed_caps` : le PREMIER CI parcouru
   rafle toutes les capas de son rail. `U2` (régulateur) passe avant `U1` (MCU)
   et prend les DIX capas de +3V3 — dont `C10`..`C15` qui découplent le MCU.
   Le snap héritait de cet appariement et COLLAIT LES DÉCOUPLAGES DU MCU SUR
   LE RÉGULATEUR. Sur la référence humaine, `C49` était ancrée à 48 mm de `U5`.

2. Le snap POWER visait le CENTRE DU CORPS de l'ancre. « À 3 mm du corps » d'un
   LQFP-48 de 7 mm laisse la capa n'importe où sur un périmètre de 40 mm.
   `anchor_pin` était annoncé « jamais lu » dans CLAUDE.md depuis le 2026-08-29.

MESURÉ, métrique corps→broche, contre le CI le plus proche :

    référence humaine   22 -> 4,8 mm  (3 capas sur 4 à exactement 2,0 mm)
    carte-05            17 -> 7,1 mm  sans que rien ait bougé : mauvais partenaire

⚠️ MA MÉTRIQUE A ÉTÉ FAUSSE TROIS FOIS avant d'être juste (43, 26, 22 mm pour
la référence). Chaque fois, l'invraisemblance du chiffre — une carte pro à
40 mm de découplage — aurait dû m'arrêter. Une mesure qui contredit l'évidence
est une mesure fausse, pas une découverte.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

from tools import placement_bypass as B  # noqa: E402


class _Pin:
    def __init__(self, number, net_name):
        self.number, self.net_name, self.net = number, net_name, net_name


class _Comp:
    def __init__(self, ref, x, y, pins):
        self.ref, self.x, self.y = ref, x, y
        self.pins = [_Pin(n, net) for n, net in pins]


class _Cluster:
    def __init__(self, anchor, members):
        self.cluster_type, self.anchor = "ClusterType.POWER", anchor
        self.members, self.max_distance_mm = list(members), 3.0


def _carte():
    """Un régulateur U2 à gauche, un MCU U1 à droite, six capas +3V3 près du MCU."""
    u2 = _Comp("U2", 0.0, 0.0, [(str(i), "+3V3" if i == 2 else ("GND" if i == 1 else "VIN")) for i in range(1, 9)])
    u1 = _Comp("U1", 40.0, 0.0, [(str(i), "+3V3" if i in (1, 24) else ("GND" if i in (8, 23) else "SIG%d" % i)) for i in range(1, 49)])
    caps = [_Comp("C%d" % i, 40.0 + dx, dy, [("1", "+3V3"), ("2", "GND")])
            for i, (dx, dy) in enumerate(((3, 0), (-3, 0), (0, 3), (0, -3), (4, 2), (-4, -2)), start=10)]
    c1 = _Comp("C1", 2.0, 0.0, [("1", "+3V3"), ("2", "GND")])  # celle-la decouple U2
    return [u2, u1, c1] + caps


class TestReattribution:
    def test_les_capas_du_MCU_vont_au_MCU_pas_au_regulateur(self):
        comps = _carte()
        # Ce que la detection native rend : U2 a tout rafle.
        natif = [_Cluster("U2", ["C1", "C10", "C11", "C12", "C13", "C14", "C15"])]
        res = B._reattribuer_les_decouplages(natif, comps)
        par_ancre = {c.anchor: sorted(c.members) for c in res
                     if str(c.cluster_type).upper().endswith("POWER")}
        assert par_ancre.get("U1") == ["C10", "C11", "C12", "C13", "C14", "C15"], par_ancre
        assert par_ancre.get("U2") == ["C1"], par_ancre

    def test_un_CI_sans_cluster_natif_en_recoit_un(self):
        """U1 n'avait AUCUN cluster — `processed_caps` avait tout donné à U2.
        Sans lui dans les ancres, aucune réattribution n'était possible."""
        comps = _carte()
        natif = [_Cluster("U2", ["C1", "C10", "C11"])]
        res = B._reattribuer_les_decouplages(natif, comps)
        assert any(c.anchor == "U1" for c in res), "U1 n a pas recu de cluster"

    def test_une_capa_sur_un_AUTRE_rail_n_est_pas_volee(self):
        """Une capa +5V ne peut pas découpler un CI qui n'a pas de broche +5V."""
        comps = _carte()
        comps.append(_Comp("C99", 41.0, 1.0, [("1", "+5V"), ("2", "GND")]))
        comps.append(_Comp("U3", 41.0, 5.0, [(str(i), "+5V" if i == 1 else "GND") for i in range(1, 9)]))
        natif = [_Cluster("U3", ["C99"])]
        res = B._reattribuer_les_decouplages(natif, comps)
        u1 = next((c for c in res if c.anchor == "U1"), None)
        assert u1 is None or "C99" not in u1.members

    def test_un_seul_cluster_a_un_membre_est_rendu_tel_quel(self):
        natif = [_Cluster("U2", ["C1"])]
        res = B._reattribuer_les_decouplages(natif, _carte())
        assert [c.anchor for c in res] == ["U2"] and res[0].members == ["C1"]


class TestCablage:
    def test_clusters_natifs_appelle_la_reattribution(self):
        import inspect
        code = "\n".join(l.split("#")[0]
                         for l in inspect.getsource(B._clusters_natifs).splitlines())
        assert "_reattribuer_les_decouplages" in code

    def test_le_snap_POWER_vise_la_broche(self):
        import inspect
        code = "\n".join(l.split("#")[0]
                         for l in inspect.getsource(B.snap_cluster_members).splitlines())
        assert "_pastille_partagee" in code, "le snap POWER vise encore le corps"


class TestUneCapaParBrocheVDD:
    """Regle de l industrie (Hartley, IPC, docs/methodologie-routage.md) :
    UNE 100 nF par broche d alimentation du CI, le bulk au regulateur.

    Mesure du 2026-09-10 sur carte-05 apres la reattribution « au CI le plus
    proche » : C10..C15 restaient groupees autour du regulateur U2, parce que
    le GA les y avait deja rassemblees (il heritait de `processed_caps`).
    Le plus proche lisait donc l erreur qu il devait corriger. Un CI RECLAME
    autant de capas qu il a de broches de rail, les plus proches d abord ;
    le reste va au CI le plus proche.
    """

    def _carte_capas_parquees(self):
        u2 = _Comp("U2", 0.0, 0.0, [(str(i), "+3V3" if i == 2 else ("GND" if i == 1 else "VIN")) for i in range(1, 9)])
        u1 = _Comp("U1", 40.0, 0.0, [(str(i), "+3V3" if i in (1, 12, 24, 36) else ("GND" if i in (8, 23) else "SIG%d" % i)) for i in range(1, 49)])
        caps = [_Comp("C%d" % i, 2.0 + 0.5 * i, 1.0, [("1", "+3V3"), ("2", "GND")]) for i in range(1, 7)]
        return [u2, u1] + caps

    def test_le_MCU_reclame_autant_de_capas_que_de_broches_VDD(self):
        comps = self._carte_capas_parquees()
        natif = [_Cluster("U2", ["C1", "C2", "C3", "C4", "C5", "C6"])]
        res = B._reattribuer_les_decouplages(natif, comps)
        par_ancre = {c.anchor: sorted(c.members) for c in res}
        assert len(par_ancre.get("U1", [])) == 4, par_ancre
        assert len(par_ancre.get("U2", [])) == 2, par_ancre

    def test_les_capas_restantes_vont_au_plus_proche(self):
        """Six capas pres du MCU, deux broches VDD : les quatre restantes ne
        partent pas a 40 mm chez le regulateur (cas du test historique)."""
        comps = _carte()
        natif = [_Cluster("U2", ["C1", "C10", "C11", "C12", "C13", "C14", "C15"])]
        res = B._reattribuer_les_decouplages(natif, comps)
        par_ancre = {c.anchor: sorted(c.members) for c in res}
        assert par_ancre.get("U1") == ["C10", "C11", "C12", "C13", "C14", "C15"], par_ancre


class _Pad:
    def __init__(self, number, net_name, x, y):
        self.number, self.net_name, self.position = number, net_name, (x, y)


class _Fp:
    def __init__(self, ref, x, y, pads, rotation=0.0):
        self.reference, self.position, self.pads, self.rotation = ref, (x, y), pads, rotation


class TestUnePastilleParCapa:
    def test_une_pastille_deja_prise_est_evitee(self):
        u1 = _Fp("U1", 40.0, 0.0, [_Pad("1", "+3V3", -3.5, -3.0), _Pad("24", "+3V3", 3.5, 3.0), _Pad("8", "GND", 0, 3.5)])
        c = _Fp("C10", 36.0, -3.0, [_Pad("1", "+3V3", -0.5, 0), _Pad("2", "GND", 0.5, 0)])
        premiere = B._pastille_partagee(u1, c)
        assert premiere == (36.5, -3.0)
        seconde = B._pastille_partagee(u1, c, exclure={premiere})
        assert seconde == (43.5, 3.0)

    def test_toutes_prises_rend_la_plus_proche(self):
        u1 = _Fp("U1", 40.0, 0.0, [_Pad("1", "+3V3", -3.5, -3.0)])
        c = _Fp("C10", 36.0, -3.0, [_Pad("1", "+3V3", -0.5, 0)])
        assert B._pastille_partagee(u1, c, exclure={(36.5, -3.0)}) == (36.5, -3.0)

    def test_le_snap_distribue_les_capas_sur_des_pastilles_distinctes(self):
        import inspect
        code = "\n".join(l.split("#")[0]
                         for l in inspect.getsource(B.snap_cluster_members).splitlines())
        assert "pads_prises" in code and "exclure=" in code, (
            "deux capas se collent a la meme broche VDD, les autres restent nues")

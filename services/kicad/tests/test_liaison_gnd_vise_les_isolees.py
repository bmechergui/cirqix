"""L etape ③ doit viser AUSSI les broches que le DRC dit isolees du plan.

⚠️ Mesure du 2026-09-01, `nucleo-f401`, board `18_cousu` — trois connexions
manquantes sur une carte a 98 % :

    PTH pad 1 [GND] of J10   <->   Pad 2 [GND] of D3
    Pad 2 [GND] of D3        <->   Zone [GND] on F.Cu
    Pad 37 [MORPHO_R_6] U1   <->   PTH pad 6 of J11      (un signal)

Les deux premieres sont de la masse. Or `D3` est une LED 0603 et `J10` un
connecteur traversant : NI L UN NI L AUTRE n est un boitier fine-pitch, donc
ni l un ni l autre n a jamais ete VISE par l etape ③, qui ne cible que
`_pads_gnd_fine_pitch`.

⚠️ Le plus frappant : la mesure qui les designe est calculee UNE LIGNE plus
haut dans la meme fonction —

    isolees_avant = _pads_isolees_du_plan(_rapport_drc(pcb_bytes))

— et ne sert qu a VERIFIER apres coup. Jamais a agir. Meme famille que
`FunctionalCluster.max_distance_mm`, calcule a chaque appel et lu par personne.

⚠️ POURQUOI CE N ETAIT PAS UNE ERREUR AU DEPART. La docstring de
`_pads_gnd_fine_pitch` porte la mesure d origine : « sur le board place avec
son plan coule, AUCUNE broche GND n est isolee ». C etait vrai ce jour-la, et
c est ce qui a fait choisir une cible PREVENTIVE (les boitiers denses) plutot
que MESUREE. Mais l ensemble mesure n est pas toujours vide : il vaut 1 sur
`nucleo-f401`.

L union est donc strictement additive — quand la mesure ne trouve rien, le
comportement est celui d avant, exactement. On ne remplace pas la cible
preventive : on lui ajoute la cible mesuree, ce que l utilisateur demandait au
pied de la lettre (« vérifier TOUS les GND collés, et si non collés, les lier »).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestUnionDesCibles:
    def test_les_isolees_mesurees_sont_AJOUTEES(self):
        cibles = R._cibles_de_liaison([("U1", "8")], [("D3", "2"), ("J10", "1")])
        assert ("D3", "2") in cibles and ("J10", "1") in cibles

    def test_la_cible_preventive_est_CONSERVEE(self):
        # ⚠️ On n echange pas une cible contre l autre : la preventive existe
        # parce que les broches deviennent orphelines PENDANT le routage.
        cibles = R._cibles_de_liaison([("U1", "8")], [("D3", "2")])
        assert ("U1", "8") in cibles

    def test_sans_isolee_mesuree_le_comportement_est_INCHANGE(self):
        # Le cas du 2026-08-31 : aucune broche isolee sur le board place.
        assert R._cibles_de_liaison([("U1", "8"), ("U1", "9")], []) == [
            ("U1", "8"), ("U1", "9")]

    def test_un_doublon_n_est_compte_qu_une_fois(self):
        # ⚠️ Deux cibles au meme endroit, c est le defaut deja paye le
        # 2026-08-31 : deux vias au meme point, donc `hole_to_hole`, donc le
        # rejet TOUT-OU-RIEN des vingt et un vias.
        cibles = R._cibles_de_liaison([("U1", "8")], [("U1", "8"), ("D3", "2")])
        assert cibles.count(("U1", "8")) == 1
        assert len(cibles) == 2

    def test_l_ordre_est_stable(self):
        # Une cible qui change d ordre d un appel a l autre rendrait les
        # mesures irreproductibles.
        a = R._cibles_de_liaison([("U1", "8")], [("D3", "2"), ("J10", "1")])
        b = R._cibles_de_liaison([("U1", "8")], [("D3", "2"), ("J10", "1")])
        assert a == b

    def test_deux_ensembles_vides_ne_donnent_rien(self):
        assert R._cibles_de_liaison([], []) == []


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def _corps_de_l_etape(self) -> str:
        i = self.SOURCE.index("def _relier_gnd_avant_routage(")
        return self.SOURCE[i:self.SOURCE.index(chr(10) + "def ", i + 1)]

    def test_l_etape_utilise_REELLEMENT_l_union(self):
        # ⚠️ Une regle correcte jamais appelee est indistinguable d une regle
        # absente. Ici le risque est precis : `isolees_avant` etait deja
        # calcule et deja inutilise.
        assert "_cibles_de_liaison(" in self._corps_de_l_etape()

    def test_les_isolees_mesurees_alimentent_l_union(self):
        corps = self._corps_de_l_etape()
        i = corps.index("_cibles_de_liaison(")
        assert "isolees_avant" in corps[i:i + 160], (
            "l union ne recoit pas la mesure qui designe les broches orphelines")

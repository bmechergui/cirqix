"""Toute pastille CMS d'un net de plan reçoit son dogbone AVANT le routage.

⚠️ Mesure du 2026-09-02, `stm32-100` livrée à 99 %. Trois pastilles GND
restent orphelines du plan, et l'analyse du board final est sans ambiguïté :

    U1.8    plan F.Cu a 7,21 mm   plan B.Cu  PILE DESSOUS
    C12.2   plan F.Cu a 1,03 mm   plan B.Cu  PILE DESSOUS
    C2.2    plan F.Cu a 6,10 mm   plan B.Cu  a 3,22 mm

Deux d'entre elles **surplombent directement le cuivre de masse de B.Cu** : un
via droit les relierait. Ce qui l'en empêche est une piste de signal passant à
**0,048 mm** — pour un dégagement exigé de 0,2 mm.

CAUSE. Ces pastilles étaient **collées au plan F.Cu avant le routage** ; le DRC
ne les voyait pas orphelines. Ce sont les pistes de signal qui ont découpé le
plan autour d'elles. C'est un EFFET du routage, pas un état initial — la
docstring de `_pads_gnd_fine_pitch` le dit déjà.

Mais la cible préventive ne vise que les boîtiers DENSES, sur cette prémisse :

    « Le plan atteint sans peine la masse d une resistance ; reserver pour
      elle gaspillerait des sites dont les boitiers denses ont besoin. »

**Ces trois pastilles mesurent cette prémisse fausse sur 2 couches.** `C2` et
`C12` sont des condensateurs, `U1.8` une broche de MCU : aucune n'appartient à
un boîtier assez dense pour être visée, et toutes trois finissent orphelines.

⚠️ UN DOGBONE, PAS UN VIA DANS LA PASTILLE. Avis de Grok du 2026-09-02, qui
tranche entre les deux :

    « Via-in-pad avant routage, sous chaque capa : occupe B.Cu pile sous le
      composant, le meilleur canal de signal sur 2 couches. »

La courte piste déporte le via de `_ESCAPE_TRACE_MM` et libère ce canal. Le
via est ensuite protégé dans le `(wiring)` du DSN : le routeur contourne un
obstacle de 0,6 mm, il ne recoud pas une pastille encerclée.

⚠️ LES PASTILLES TRAVERSANTES SONT EXCLUES. Leur perçage atteint déjà le plan
de la face opposée — leur poser un via serait un doublon, et ce dépôt a déjà
payé ce doublon d'un rejet TOUT-OU-RIEN de vingt et un vias.

⚠️ Cette règle est ADDITIVE : elle élargit la cible, elle n'en retire aucune.
Les boîtiers denses restent visés par `_pads_gnd_fine_pitch`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


def _board(pads: str) -> bytes:
    return ('(kicad_pcb (footprint "X" (property "Reference" "C12")'
            + pads + '))').encode("utf-8")


class TestQuellesPastilles:
    def test_une_pastille_CMS_sur_un_net_de_plan_est_visee(self):
        b = _board('(pad "2" smd roundrect (net 3 "GND"))')
        assert R._pads_plan_a_degager(b, {"GND"}) == [("C12", "2")]

    def test_une_pastille_TRAVERSANTE_est_exclue(self):
        # ⚠️ Son percage atteint deja le plan d en face : le via ferait doublon.
        b = _board('(pad "1" thru_hole circle (net 3 "GND"))')
        assert R._pads_plan_a_degager(b, {"GND"}) == []

    def test_une_pastille_d_un_AUTRE_net_est_ignoree(self):
        b = _board('(pad "1" smd rect (net 7 "GPIO46"))')
        assert R._pads_plan_a_degager(b, {"GND"}) == []

    def test_un_petit_boitier_est_vise_LUI_AUSSI(self):
        # ⚠️ Le coeur du correctif : la densite du boitier n entre plus en
        # ligne de compte. `C12` porte deux pastilles, loin du seuil dense.
        b = _board('(pad "1" smd rect (net 7 "VCC"))'
                   '(pad "2" smd rect (net 3 "GND"))')
        assert R._pads_plan_a_degager(b, {"GND"}) == [("C12", "2")]

    def test_la_forme_de_net_SANS_NUMERO_est_reconnue(self):
        # ⚠️ pcbnew de KiCad 10 ecrit `(net "GND")` — la forme qui avait rendu
        # le compteur de nets aveugle le 2026-08-20.
        b = _board('(pad "2" smd rect (net "GND"))')
        assert R._pads_plan_a_degager(b, {"GND"}) == [("C12", "2")]

    def test_sans_net_de_plan_on_ne_vise_RIEN(self):
        b = _board('(pad "2" smd rect (net 3 "GND"))')
        assert R._pads_plan_a_degager(b, set()) == []

    def test_un_board_illisible_rend_une_liste_VIDE(self):
        # La reservation est un BONUS, jamais un passage oblige.
        assert R._pads_plan_a_degager(b"", {"GND"}) == []


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_regle_est_APPELEE_avant_le_routage(self):
        # Une regle correcte jamais invoquee est indistinguable d une absente.
        i = self.SOURCE.index("def _relier_gnd_avant_routage(")
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        assert "_pads_plan_a_degager(" in self.SOURCE[i:j]

    def test_la_cible_DENSE_subsiste(self):
        # ⚠️ Strictement additif : on elargit, on ne remplace pas.
        i = self.SOURCE.index("def _relier_gnd_avant_routage(")
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        assert "_pads_gnd_fine_pitch(" in self.SOURCE[i:j]

    def test_l_union_passe_par_le_DEDOUBLONNEUR(self):
        # ⚠️ Deux listes qui se recouvrent poseraient deux vias au meme point,
        # donc une violation hole_to_hole, donc le rejet de TOUT le lot.
        i = self.SOURCE.index("def _relier_gnd_avant_routage(")
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        assert "_cibles_de_liaison(" in self.SOURCE[i:j]


class TestPasDeDoublon:
    def test_une_pastille_visee_DEUX_FOIS_n_apparait_qu_une(self):
        assert R._cibles_de_liaison([("C12", "2")], [("C12", "2")]) == [("C12", "2")]

    def test_l_union_reste_additive(self):
        assert R._cibles_de_liaison([("U1", "8")], [("C2", "2")]) == [
            ("U1", "8"), ("C2", "2")]

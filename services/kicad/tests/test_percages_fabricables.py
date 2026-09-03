"""Un percage sous le minimum du fabricant doit etre ELARGI, pas tolere.

⚠️ Mesure du 2026-08-27, ESP32 du banc. Une fois les chevauchements de
courtyard resolus, les DOUZE erreurs restantes du board place etaient :

    drill_out_of_range   PTH pad 39 [+3.3V] of U1     x12

Ce sont les vias thermiques du pave du module — `(drill 0.2)` pour une
pastille de 0,6 mm, tels que la bibliotheque KiCad les fournit. Le minimum par
defaut de KiCad est 0,30 mm, et c est aussi le minimum du procede STANDARD de
JLCPCB : ce n est donc pas un faux positif, la carte serait refusee.

⚠️ La tentation est d ouvrir les regles dans le `.kicad_pro`, comme on le fait
deja pour les boitiers fine-pitch. C est un MENSONGE ici : `_projet_kicad`
n ouvre les regles que parce qu on accepte alors l option payante de JLCPCB.
Elargir le percage ne coute rien et rend la carte fabricable au tarif
standard — c est ce qu un concepteur fait.

⚠️ L anneau doit suivre. Elargir le percage sans elargir la pastille
transformerait une erreur de percage en erreur d anneau.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import placement as P  # noqa: E402

NL = chr(10)

_VIA_THERMIQUE = NL.join([
    '\t\t(pad "39" thru_hole circle',
    "\t\t\t(at -2.205 -1.6725)",
    "\t\t\t(size 0.6 0.6)",
    "\t\t\t(drill 0.2)",
    '\t\t\t(layers "*.Cu" "F.Mask")',
    "\t\t)",
])


class TestRegle:
    def test_un_percage_trop_fin_est_elargi_au_minimum(self):
        sortie, n = P.elargir_percages_trop_fins(_VIA_THERMIQUE)
        assert n == 1
        assert "(drill %s)" % P._PERCAGE_MINIMUM_MM in sortie
        assert "(drill 0.2)" not in sortie

    def test_l_anneau_suit_le_percage(self):
        sortie, _ = P.elargir_percages_trop_fins(_VIA_THERMIQUE)
        # 0,6 mm de pastille pour 0,3 de percage laisse 0,15 d anneau : au
        # dessus du minimum de 0,10. La pastille n a donc pas a bouger.
        assert "(size 0.6 0.6)" in sortie

    def test_une_pastille_trop_petite_grandit_avec_son_percage(self):
        etroit = _VIA_THERMIQUE.replace("(size 0.6 0.6)", "(size 0.35 0.35)")
        sortie, _ = P.elargir_percages_trop_fins(etroit)
        assert "(size 0.35 0.35)" not in sortie, (
            "elargir le percage sans la pastille change l erreur de nom")

    def test_un_percage_conforme_est_laisse_tel_quel(self):
        bon = _VIA_THERMIQUE.replace("(drill 0.2)", "(drill 0.4)")
        sortie, n = P.elargir_percages_trop_fins(bon)
        assert (sortie, n) == (bon, 0)

    def test_une_pastille_smd_n_est_pas_touchee(self):
        # Pas de percage : rien a elargir, et toucher sa taille serait faux.
        smd = '\t\t(pad "39" smd rect (at 0 0) (size 0.6 0.6) (layers "F.Cu"))'
        sortie, n = P.elargir_percages_trop_fins(smd)
        assert (sortie, n) == (smd, 0)


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_la_reparation_precede_la_mesure(self):
        # Meme raison que pour le deguillemetage : reparer apres avoir mesure
        # ne corrige rien de ce que l appelant a deja lu.
        assert "elargir_percages_trop_fins" in self.SOURCE
        i = self.SOURCE.index("def _rendre_lisible")
        corps = self.SOURCE[i:i + 1400]
        assert "elargir_percages_trop_fins" in corps, (
            "la reparation doit vivre au meme endroit que le deguillemetage")

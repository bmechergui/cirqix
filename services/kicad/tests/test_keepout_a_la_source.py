"""Un board qui sort du service doit etre LISIBLE par tout lecteur de KiCad.

⚠️ Mesure du 2026-08-27, ESP32 du banc. `place_auto` rendait un board dont le
keepout portait des valeurs entre guillemets — l ecriture de `kicad_tools` :

    (keepout (tracks "not_allowed") (vias "not_allowed") ...)

KiCad refuse alors le fichier ENTIER. On avait deja repare ce defaut, mais
seulement dans le CHARGEUR pcbnew (`_charger_board`). Or `kicad-cli` est un
SECOND lecteur, et il n a pas ce filet : il repondait « Failed to load board ».

La consequence n etait pas une erreur visible, mais un MENSONGE. Chaine
mesuree sur le meme board :

    board PLACE                : rapport DRC VIDE  -> lu « 0 erreur »
    apres coulee + remplissage : 20 erreurs        -> dont 12 courtyards_overlap

Les vingt erreurs etaient dans le board place depuis le debut. Le passage par
pcbnew (qui, lui, repare) ne les CREAIT pas : il les REVELAIT, en reecrivant un
fichier lisible. Entre les deux, `_compter_conflits_erreur` lisait « 0 conflit »
et la boucle de re-tirage acceptait un board condamne — puis la chaine routait
vingt-cinq minutes dessus.

D ou la regle : on repare a la SOURCE, une seule fois, pas chez chaque lecteur.
Un lecteur qu on oublie suffit a rendre la reparation decorative.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools.sexp_quote import unquote_keepout_values  # noqa: E402

NL = chr(10)

_KEEPOUT_QUOTE = (
    '(keepout (tracks "not_allowed") (vias "not_allowed") (pads "not_allowed") '
    '(copperpour "not_allowed") (footprints "not_allowed"))'
)


class TestLaRegle:
    def test_les_valeurs_de_keepout_perdent_leurs_guillemets(self):
        sortie, n = unquote_keepout_values(_KEEPOUT_QUOTE)
        assert n == 5
        assert '"' not in sortie
        assert "(tracks not_allowed)" in sortie
        assert "(copperpour not_allowed)" in sortie

    def test_un_keepout_deja_nu_est_laisse_tel_quel(self):
        nu = "(keepout (tracks not_allowed) (vias allowed))"
        sortie, n = unquote_keepout_values(nu)
        assert (sortie, n) == (nu, 0)

    def test_les_autres_chaines_ne_sont_pas_touchees(self):
        # Une valeur quotee qui n est PAS un mot-cle de keepout doit survivre :
        # deguillemeter au hasard casserait le fichier aussi surement.
        texte = '(layer "F.Cu") (net 3 "GND") (property "Value" "330")'
        sortie, n = unquote_keepout_values(texte)
        assert (sortie, n) == (texte, 0)


class TestCablage:
    """La regle doit etre appliquee la ou le board SORT, pas seulement lue."""

    PLACEMENT = (_SERVICE_ROOT / "tools" / "placement.py").read_text(
        encoding="utf-8")
    ROUTING = (_SERVICE_ROOT / "routers" / "routing.py").read_text(
        encoding="utf-8")

    def test_le_placement_deguillemete_ce_qu_il_rend(self):
        assert "unquote_keepout_values" in self.PLACEMENT, (
            "le board rendu par auto_place doit etre lisible par kicad-cli")

    def test_le_routage_partage_la_meme_regle(self):
        # Deux copies d une meme regle finissent toujours par diverger.
        assert "unquote_keepout_values" in self.ROUTING

"""Une zone ne peut pas citer des couches que la carte ne declare pas.

Cause racine des 19 connexions manquantes de l ESP32 du banc, trouvee le
2026-08-26 en capturant le board que pcbnew refusait :

    couches cuivre declarees par la carte :  2   (F.Cu, B.Cu)
    couches citees par un keepout         : 32   (F.Cu, B.Cu, In1..In30)

pcbnew refuse alors le fichier ENTIER — `LoadBoard` rend `None`. L export
Specctra echoue, Freerouting n est jamais appele, et la cascade retombe sur
kicad-tools, dont le banc du 2026-08-21 a mesure 7 connexions manquantes et
58 erreurs de fabricabilite la ou Freerouting en produit zero.

⚠️ Le keepout fautif n est PAS le notre : le notre ecrit `(copperpour
not_allowed)` sans guillemets, celui-ci les met, et il vient d un board dont le
generateur est `kicad_tools`. Le defaut est en amont — on le repare a la
lecture, comme on requote deja les proprietes numeriques nues.

⚠️ On RETIRE les couches fantomes, jamais la zone : un keepout qui disparait
laisserait le plan couler sous un boitier fine-pitch, ce que la mesure du
2026-08-23 a montre nefaste.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _board(couches_zone: str) -> bytes:
    return (
        "(kicad_pcb\n\t(version 20240108)\n"
        '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)\n'
        '\t\t(44 "Edge.Cuts" user)\n\t)\n'
        '\t(net 3 "GND")\n'
        "\t(zone\n"
        f"\t\t(layers {couches_zone})\n"
        '\t\t(keepout (copperpour "not_allowed"))\n'
        "\t)\n)"
    ).encode("utf-8")


TROP = '"F.Cu" "B.Cu" "In1.Cu" "In2.Cu" "In30.Cu"'
JUSTE = '"F.Cu" "B.Cu"'


class TestNettoyage:
    def test_les_couches_absentes_sont_retirees(self):
        out = routing_router._retirer_couches_fantomes(_board(TROP)).decode("utf-8")
        assert "In1.Cu" not in out and "In30.Cu" not in out

    def test_les_couches_reelles_sont_gardees(self):
        out = routing_router._retirer_couches_fantomes(_board(TROP)).decode("utf-8")
        assert '"F.Cu"' in out and '"B.Cu"' in out

    def test_la_zone_n_est_JAMAIS_supprimee(self):
        # Un keepout qui disparait laisse le plan couler sous un boitier
        # fine-pitch — mesure du 2026-08-23, c est exactement ce qu on evite.
        out = routing_router._retirer_couches_fantomes(_board(TROP)).decode("utf-8")
        assert "(zone" in out and "keepout" in out

    def test_un_board_deja_propre_n_est_pas_touche(self):
        entree = _board(JUSTE)
        assert routing_router._retirer_couches_fantomes(entree) == entree

    def test_un_board_sans_zone_n_est_pas_touche(self):
        entree = b'(kicad_pcb\n\t(layers\n\t\t(0 "F.Cu" signal)\n\t)\n)'
        assert routing_router._retirer_couches_fantomes(entree) == entree


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_nettoyage_precede_l_export_specctra(self):
        # Nettoyer APRES ne servirait a rien : c est l export qui charge le
        # board et echoue.
        assert "_retirer_couches_fantomes(" in self.SOURCE


class TestGuillemetsDeKeepout:
    """KiCad refuse une valeur de keepout entre guillemets.

    C est la VRAIE cause du board illisible qui degradait l ESP32 — isolee le
    2026-08-26 apres avoir d abord accuse les couches fantomes du meme keepout :

        (keepout (tracks "not_allowed") ...)   -> LoadBoard rend None
        (keepout (tracks not_allowed) ...)     -> charge

    Verifie sur le board reel : `None` avant, 20 empreintes apres.

    ⚠️ Le keepout fautif n est pas le notre — le notre ecrit ses valeurs nues.
    Il vient d un board genere par kicad_tools.
    """

    def _avec(self, valeur: str) -> bytes:
        return (
            "(kicad_pcb\n"
            '\t(layers\n\t\t(0 "F.Cu" signal)\n\t)\n'
            "\t(zone\n"
            f"\t\t(keepout (tracks {valeur}) (vias {valeur}) (copperpour {valeur}))\n"
            "\t)\n)"
        ).encode("utf-8")

    def test_les_guillemets_sont_retires(self):
        out = routing_router._deguillemeter_keepout(self._avec('"not_allowed"')).decode()
        assert '"not_allowed"' not in out
        assert "(tracks not_allowed)" in out

    def test_toutes_les_cles_sont_traitees(self):
        out = routing_router._deguillemeter_keepout(self._avec('"allowed"')).decode()
        for cle in ("tracks", "vias", "copperpour"):
            assert f"({cle} allowed)" in out

    def test_un_keepout_deja_nu_n_est_pas_touche(self):
        entree = self._avec("not_allowed")
        assert routing_router._deguillemeter_keepout(entree) == entree

    def test_les_autres_chaines_ne_sont_pas_touchees(self):
        # On ne deguillemete QUE les cles de keepout : un `(layer "F.Cu")`
        # deguillemete casserait le fichier a son tour.
        entree = self._avec('"not_allowed"')
        out = routing_router._deguillemeter_keepout(entree).decode()
        assert '"F.Cu"' in out

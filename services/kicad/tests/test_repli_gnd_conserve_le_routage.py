"""Le repli GND repartait de ZERO. Il doit completer, pas recommencer.

⚠️ Constat du 2026-08-31, souleve par l utilisateur : « si le repli se
declenche, repart-il de zero ou garde-t-il les pistes deja routees ? »

Il repartait de zero. Le code le montre :

    etendu  = _fill_zones(_add_ground_planes(etendu))   # board PLACE, non route
    secours = _router_en_incluant_gnd(etendu, ...)      # on lui donne celui-la

Et la mesure le confirme, `stm32-60` : 440 segments en entree, 384 en sortie.
Ce n est pas le routage complete, c est un routage entierement neuf.

C est du gachis : on jette un routage correct a 98 % pour tout recommencer, a
cause d UNE SEULE broche GND que le plan n atteint pas.

⚠️ Le mecanisme pour faire autrement existe depuis ce matin — la protection des
pistes (`_PISTES_A_PROTEGER`), validee sur un vrai board : 426 fils proteges,
88 % -> 98 %, 426 -> 510 segments. Le routeur COMPLETE au lieu de refaire.

On l applique donc au repli : les pistes deja routees sont protegees, et le
routeur n a plus qu a tirer les liaisons GND manquantes.

⚠️ L etat de module est RESTAURE sans faute. `_PISTES_A_PROTEGER` sert aussi a
l escalade : le laisser pointer sur le board du repli ferait proteger, au
palier suivant, un routage qui n est pas celui qu on a garde.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestSignature:
    def test_le_repli_accepte_le_routage_acquis(self):
        import inspect
        params = inspect.signature(R._router_en_incluant_gnd).parameters
        assert "deja_route" in params, (
            "le repli ne peut pas recevoir le routage a conserver")

    def test_il_reste_appelable_sans(self):
        # Compatibilite : un appelant qui n a rien a conserver doit passer.
        import inspect
        assert (inspect.signature(R._router_en_incluant_gnd)
                .parameters["deja_route"].default is None)


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def _corps(self) -> str:
        i = self.SOURCE.index("def _router_en_incluant_gnd(")
        j = self.SOURCE.index(chr(10) + "def ", i + 5)
        return self.SOURCE[i:j]

    def test_le_routage_acquis_est_PROTEGE(self):
        assert "_PISTES_A_PROTEGER" in self._corps(), (
            "le repli reroute tout au lieu de completer l existant")

    def test_l_etat_de_module_est_RESTAURE(self):
        """⚠️ `_PISTES_A_PROTEGER` sert AUSSI a l escalade. Le laisser pointer
        sur le board du repli ferait proteger, au palier suivant, un routage
        qui n est pas celui qu on a garde."""
        corps = self._corps()
        assert "finally:" in corps
        i = corps.index("finally:")
        assert "_PISTES_A_PROTEGER" in corps[i:i + 400]

    def test_l_appelant_transmet_le_board_ROUTE(self):
        i = self.SOURCE.index("secours = _router_en_incluant_gnd(")
        assert "final" in self.SOURCE[i:i + 160], (
            "on passe le board place au lieu du board route : rien a conserver")

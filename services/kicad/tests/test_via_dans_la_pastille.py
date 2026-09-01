"""Dernier recours : poser le via DANS la pastille elle-meme.

Demande repetee de l utilisateur : le plan prend GND en charge, et les pattes
qu il n atteint pas recoivent un fine-pitch et un via. Sur le board STM32, deux
pattes du LQFP-48 resistaient a toute sortie LATERALE — mesure du 2026-08-23 :
0 chemin degage sur 567 candidats, le voisinage comptant 182 obstacles apres
routage des signaux.

J avais ecarte le via-in-pad en jugeant qu un via de 0,60 mm ne rentre pas dans
une pastille de 0,30. C etait vrai de ce via-la, pas de la technique. Mesure du
2026-08-26 :

    pad 0,30 x 1,48 mm | via 0,30 -> obstacle le plus proche 0,350 mm  TIENT
                       | via 0,25 -> TIENT
                       | via 0,20 -> TIENT

Un via qui n est PAS PLUS LARGE que la pastille herite de la clearance de la
pastille — celle que la carte accepte deja. C est le meme raisonnement que
l exemption accordee a la piste d echappement le long de son propre pad.

Et il n a besoin d AUCUNE piste : pose au centre du pad, il le traverse
directement vers le plan de l autre face. Le probleme du chemin lateral, qui
condamnait les 567 candidats, disparait.

⚠️ Cout de fabrication : un via debouchant dans une pastille doit etre bouche et
recouvert (via-in-pad), facture en supplement chez JLCPCB. C est un choix
PRODUIT, pas une astuce gratuite — d ou le dernier recours et non le defaut.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as runner  # noqa: E402

MM = 1_000_000


class TestDiametre:
    def test_le_via_ne_depasse_jamais_la_pastille(self):
        # Tout l argument tient la-dessus : plus large, il perd la clearance du
        # pad et redevient un obstacle pour les voisines.
        assert runner._diametre_via_in_pad(300_000, 600_000) <= 300_000

    def test_un_pad_large_garde_le_via_nominal(self):
        # Ne pas retrecir sans raison : un via plus fin perce plus petit et
        # coute plus cher a fabriquer.
        assert runner._diametre_via_in_pad(2 * MM, 600_000) == 600_000

    def test_un_pad_minuscule_ne_recoit_rien(self):
        # Sous le minimum fabricable, on renonce plutot que de dessiner un
        # percage que personne ne peut realiser.
        assert runner._diametre_via_in_pad(100_000, 600_000) == 0


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8"
    )

    def test_le_via_in_pad_est_un_DERNIER_recours(self):
        # Une sortie laterale reste preferable : elle ne coute pas de via bouche.
        corps = self.SOURCE[self.SOURCE.index("def _escape_pads(") :]
        corps = corps[: corps.index(chr(10) + "def ")]
        # ⚠️ `_via_in_pad_possible` ENVELOPPE `_diametre_via_in_pad` depuis le
        # 2026-09-01 : elle y ajoute le refus d une pastille deja percee (un
        # trou dans un trou). L intention de la garde — le via-in-pad vient
        # APRES la recherche laterale — est inchangee ; seul le nom appele l est.
        assert "_via_in_pad_possible(" in corps
        assert corps.index("_choisir_sortie(") < corps.index("_via_in_pad_possible(")

    def test_le_renoncement_reste_possible(self):
        # Si meme le via-in-pad ne tient pas, on ne pose RIEN : une broche
        # orpheline se voit au DRC, un court-circuit part en fabrication.
        corps = self.SOURCE[self.SOURCE.index("def _escape_pads(") :]
        corps = corps[: corps.index(chr(10) + "def ")]
        assert "renonces" in corps

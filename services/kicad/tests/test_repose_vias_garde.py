"""La repose des vias etait la SEULE etape a poser du cuivre sans garde.

⚠️ Mesure du 2026-08-31, `nucleo-f401` au banc final :

    nucleo-f401   2 couches   97 %   3 manquantes   3 ERREURS   3447 s

Trois `copper_edge_clearance` — du cuivre a moins de 0,5 mm du bord de carte.
Premiere fois que cette carte porte des erreurs : ses deux mesures precedentes
etaient a ZERO. Une carte avec des erreurs de fabricabilite ne part pas en
production.

Inventaire des etapes qui AJOUTENT du cuivre apres le routage :

    _recoudre_les_zones      garde « ne peut qu ameliorer » : OUI
    _recoudre_les_ilots                                       OUI
    _fanout_pads_isolees                                      OUI
    _reposer_vias_reserves                                    NON

`_reposer_vias_reserves` repose les vias d echappement que l aller-retour
Specctra efface. Leurs positions sont calculees AVANT le routage : rien ne
garantit qu elles restent valides sur le board final, et rien ne le verifiait.

⚠️ La garde ne PREND PAS DE DECISION sur la cause exacte des trois erreurs —
elle rend l etape incapable d en ajouter, comme ses trois voisines. C est la
regle du projet : une etape de reparation ne doit jamais degrader.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestInventaire:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def _corps(self, nom: str) -> str:
        i = self.SOURCE.index("def %s(" % nom)
        j = self.SOURCE.index(chr(10) + "def ", i + 5)
        return self.SOURCE[i:j]

    # ⚠️ L ANCRE A DU BOUGER LE 2026-09-07, et c est instructif. Ces gardes
    # cherchaient le texte `_compte_erreurs` DANS le corps de chaque fonction.
    # La comparaison etait alors ecrite cinq fois a l identique — et donc
    # fausse cinq fois : sans verdict DRC les deux cotes valaient zero et le
    # candidat passait sans jugement. Elle vit desormais dans UNE fonction,
    # `_aggrave_le_board`, qui echoue fermé.
    #
    # L intention de ces gardes est inchangee : une etape qui pose du cuivre
    # doit verifier qu elle n aggrave rien. On s ancre donc sur l INTENTION —
    # l une ou l autre forme — plutot que sur un nom qui peut encore bouger.
    _GARDES = ("_aggrave_le_board", "_compte_erreurs")

    def _a_la_garde(self, corps: str) -> bool:
        return any(g in corps for g in self._GARDES)

    def _index_garde(self, corps: str) -> int:
        for g in self._GARDES:
            if g in corps:
                return corps.index(g)
        raise AssertionError("aucune garde de non-degradation dans ce corps")

    def test_toutes_les_etapes_qui_posent_du_cuivre_ont_la_garde(self):
        """⚠️ Invariant de la chaine : une etape de reparation ne degrade
        JAMAIS. Trois l avaient, une ne l avait pas."""
        for nom in ("_recoudre_les_zones", "_recoudre_les_ilots",
                    "_fanout_pads_isolees", "_reposer_vias_reserves"):
            assert self._a_la_garde(self._corps(nom)), (
                "%s ajoute du cuivre sans verifier qu elle n aggrave rien" % nom)

    def test_la_repose_rend_le_board_RECU_si_elle_aggrave(self):
        corps = self._corps("_reposer_vias_reserves")
        i = self._index_garde(corps)
        assert "return pcb_bytes" in corps[i:i + 600], (
            "la garde compte les erreurs mais ne rend pas le board d origine")

    def test_le_refus_est_DIT(self):
        # Un refus silencieux ferait croire que la repose a eu lieu.
        corps = self._corps("_reposer_vias_reserves")
        i = self._index_garde(corps)
        assert "logger.warning" in corps[i:i + 600]

"""La qualite du placement etait CALCULEE mais jamais RENDUE.

⚠️ Constat du 2026-08-30. `_longueur_de_fil_mm` tourne a chaque tirage et sert
deja a departager deux placements (`_placement_meilleur`). Mais le champ
n existait pas sur `AutoPlacementResponse` : pydantic l ignorait en silence, et
aucun appelant ne pouvait savoir quel placement il venait de recevoir.

Cette absence rendait invisible l asymetrie du pipeline :

    routage    3 tirages, on garde le MEILLEUR des trois
    placement  on s arrete au PREMIER tirage sans conflit

Or « sans conflit » ne veut pas dire « routable » : les six executions de
`stm32-100` avaient TOUTES un placement propre, et ont route a 48, 70, 99 et
100 %. La dispersion du produit fini vient de la, et rien ne la filtrait.

⚠️ On EXPOSE avant de changer quoi que ce soit. Rien ne prouve encore qu un
second tirage de placement ameliore le ROUTAGE — la seule mesure existante
portait sur la longueur de fil a budget reduit. Ce champ rend la correlation
mesurable ; la decision viendra apres, avec des chiffres.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers.placement import AutoPlacementResponse  # noqa: E402


class TestChamp:
    def test_le_champ_existe(self):
        assert "fil_mm" in AutoPlacementResponse.model_fields

    def test_il_traverse_le_dictionnaire_de_resultat(self):
        # Le routeur construit `AutoPlacementResponse(**result)` : sans champ
        # declare, pydantic jetait la valeur SANS erreur — c est ce qui a rendu
        # l omission indetectable.
        r = AutoPlacementResponse(kicad_pcb_b64="", placed_count=0,
                                  positions=[], fil_mm=372.5)
        assert r.fil_mm == 372.5

    def test_non_mesure_n_est_pas_zero(self):
        """⚠️ Defaut None, jamais 0.0.

        Un zero est plausible et se lirait comme « placement parfait », alors
        qu il signifierait « je n ai pas su mesurer ». Meme faute que le
        rapport DRC vide lu « 0 erreur ».
        """
        r = AutoPlacementResponse(kicad_pcb_b64="", placed_count=0, positions=[])
        assert r.fil_mm is None

    def test_les_champs_existants_survivent(self):
        r = AutoPlacementResponse(kicad_pcb_b64="x", placed_count=3,
                                  positions=[{"ref": "U1"}], conflits_restants=2)
        assert (r.placed_count, r.conflits_restants) == (3, 2)


class TestSource:
    SOURCE = (_SERVICE_ROOT / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_la_longueur_est_bien_calculee_en_amont(self):
        # Si ce calcul disparaissait, le champ expose rendrait None pour
        # toujours — et personne ne le verrait.
        assert '"fil_mm": _longueur_de_fil_mm(' in self.SOURCE

    def test_elle_sert_deja_a_departager_deux_tirages(self):
        assert "def _placement_meilleur(" in self.SOURCE

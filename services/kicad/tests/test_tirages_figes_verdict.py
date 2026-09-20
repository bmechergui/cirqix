"""« Tous les tirages ont figé » est un VERDICT sur le placement, pas une panne.

⚠️ Rejeu du 2026-09-20 : carte-09 et carte-10 sortent `skipped=True,
routed_percent=0` — la meme reponse qu un service sans routeur. Le client
(`handlers/routing.ts`) lit `skipped` comme une panne d infrastructure et
rend `status: 'error'` sans pourcentage : la boucle de re-tirage du placement
(`shouldRetryPlacement`, qui lit `routed_percent`) ne se declenche jamais.
Or le routeur A tourne, et il a MESURE : ~0 % apres 30 passes sans progres.
C est un verdict sur ce placement, et le seul remede est d en tirer un autre.

Regle : quand au moins un tirage a fige et qu aucun n a abouti, la reponse
porte `verdict="tirages_figes"` et `routed_percent` = meilleur pourcentage
mesure sur les tirages figes (lu dans le journal du routeur, jamais fabrique).
`skipped` reste vrai et aucun board n est rendu — on n invente pas de cuivre.
Une vraie panne (aucun moteur) garde `verdict=None`.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402


class TestModele:
    def test_le_verdict_existe_et_vaut_none_par_defaut(self):
        r = R.RouteAutoResponse(layers=2)
        assert r.verdict is None

    def test_verdict_tirages_figes(self):
        r = R.RouteAutoResponse(layers=2, skipped=True, routed_percent=17, verdict="tirages_figes")
        assert r.kicad_pcb_b64 is None and r.skipped and r.routed_percent == 17


class TestCablage:
    SOURCE = (RACINE / "routers" / "routing.py").read_text(encoding="utf-8")

    def _fin(self):
        corps = self.SOURCE[self.SOURCE.index("def route_auto("):]
        corps = corps[: corps.index("\nclass RouteProgressResponse")]
        return corps[corps.rindex("if meilleur is None:"):]

    def test_l_echec_final_porte_le_verdict_quand_un_tirage_a_fige(self):
        fin = self._fin()
        i = fin.rindex("skipped=True")
        bloc = fin[max(0, i - 900): i + 400]
        assert 'verdict="tirages_figes" if meilleur_fige is not None else None' in bloc
        assert "routed_percent=fige_max" in bloc or "routed_percent=(fige_max" in bloc

    def test_aucun_board_n_est_fabrique(self):
        fin = self._fin()
        assert "base64.b64encode(pcb_bytes)" not in fin

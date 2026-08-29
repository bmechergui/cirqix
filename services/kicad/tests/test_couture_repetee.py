"""La couture des ilots se repete jusqu a ce qu il n y ait plus rien a coudre.

⚠️ Mesure du 2026-08-29, banc avec le plan coule avant le routage. Quatre
cartes sur sept sortent a 100 % route et 0 erreur. Les trois autres restent a
96-98 %, et TOUTES leurs connexions manquantes sont des GND :

    stm32-30   4 manquantes   toutes GND
    stm32-60   3 manquantes   toutes GND

Ventilation sur stm32-30 : UNE seule est une pastille (`Pad 8 [GND] of U1`).
Les trois autres sont des paires `Zone [GND] <-> Zone [GND]` — le plan lui-meme
coupe en ilots par les pistes de signal.

La couture s executait bien : le journal montre 1 a 4 vias poses a chaque
passage. Mais elle ne passait QU UNE FOIS. Or recoudre deux ilots peut en
reveler un troisieme : le cuivre nouvellement joint change la topologie, et la
mesure suivante voit des paires que la premiere ne pouvait pas voir.

⚠️ On borne les passages. Une boucle non bornee sur une carte pathologique
tournerait indefiniment, et chaque passage coute un DRC plus un processus
pcbnew.

⚠️ On s arrete des qu un passage ne pose plus AUCUN via : insister ne
changerait rien, et `_recoudre_les_zones` rend alors le board recu tel quel.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestBoucle:
    def test_la_couture_repete_tant_qu_elle_progresse(self, monkeypatch):
        etats = [b"a", b"b", b"c", b"c"]
        vus = []

        def faux(pcb):
            vus.append(pcb)
            return etats[len(vus)] if len(vus) < len(etats) else pcb

        monkeypatch.setattr(R, "_recoudre_les_zones", faux)
        sortie = R._coudre_jusqu_au_bout(b"a")
        assert sortie == b"c"
        assert len(vus) >= 3, "il faut repasser tant que le board change"

    def test_elle_s_arrete_quand_plus_rien_ne_bouge(self, monkeypatch):
        appels = []

        def inerte(pcb):
            appels.append(pcb)
            return pcb

        monkeypatch.setattr(R, "_recoudre_les_zones", inerte)
        assert R._coudre_jusqu_au_bout(b"x") == b"x"
        assert len(appels) == 1, "un passage sans effet ne se repete pas"

    def test_le_nombre_de_passages_est_borne(self, monkeypatch):
        compteur = {"n": 0}

        def toujours_different(pcb):
            compteur["n"] += 1
            return pcb + b"."

        monkeypatch.setattr(R, "_recoudre_les_zones", toujours_different)
        R._coudre_jusqu_au_bout(b"x")
        assert compteur["n"] <= R._PASSES_COUTURE, (
            "une carte pathologique ne doit pas faire tourner la boucle sans fin")

    def test_la_borne_laisse_de_la_marge(self):
        # Un seul passage supplementaire ne servirait a rien ; une borne trop
        # large couterait un DRC et un processus pcbnew par passage.
        assert 3 <= R._PASSES_COUTURE <= 8


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_boucle_est_utilisee_dans_le_routage(self):
        i = self.SOURCE.index("essais = _paliers_avec_tirages(")
        assert "_coudre_jusqu_au_bout(" in self.SOURCE[i:]

"""Le plafond d horloge suit la CADENCE du routeur, comme le fait deja le silence.

⚠️ Mesure du 2026-09-22, carte-10, MEME placement gele :

    machine LIBRE     4 tirages   4 x (0 erreur, 0 manquante)   139-392 s
    machine CHARGEE   3 tirages   3 ECHECS                      603-1838 s

La charge venait d une consultation d agent lancee pendant le banc. Processeur
dispute -> moins de passes par seconde -> `_PLAFOND_ATTENTE_S = 300` tire alors
que le routeur PROGRESSAIT encore -> tirage declare fige -> la chaine garde un
board moins bon.

⚠️ C EST UNE SŒUR OUBLIEE. `_faut_couper` a trois coupures :

    fenetre de passes   compte des passes         independante de la machine
    routeur MUET        `max(300 s, 3 x cadence)` SUIT deja la cadence
    temps sans progres  `> 300 s` en dur          NE LA SUIT PAS

Le meme fichier savait donc deja qu un plafond d horloge doit suivre la
cadence ; une seule des deux coupures l applique. « NEVER laisser un defaut
corrige dans une fonction sans chercher ses SŒURS. »

REGLE : l horloge ne doit JAMAIS couper avant que la fenetre de passes ne l ait
fait. Le plafond vaut donc au moins ce que cette fenetre coute au rythme
OBSERVE — deduit, jamais un second seuil calibre.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402


class TestLHorlogeNeCoupePasAvantLesPasses:
    def test_machine_normale_le_plafond_habituel_s_applique(self):
        # 150 passes a 1 s = 150 s : le plafond de 300 s reste le maitre.
        assert R._faut_couper(plat=10, fenetre=150, muet=False,
                              sans_progres_s=301.0, cadence_s=1.0) is True
        assert R._faut_couper(plat=10, fenetre=150, muet=False,
                              sans_progres_s=299.0, cadence_s=1.0) is False

    def test_machine_LENTE_le_plafond_suit_la_cadence(self):
        # 150 passes a 5 s = 750 s : couper a 300 s trancherait un tirage qui
        # progresse encore. C est le defaut mesure le 2026-09-22.
        assert R._faut_couper(plat=10, fenetre=150, muet=False,
                              sans_progres_s=400.0, cadence_s=5.0) is False
        assert R._faut_couper(plat=10, fenetre=150, muet=False,
                              sans_progres_s=800.0, cadence_s=5.0) is True

    def test_sans_cadence_mesuree_rien_ne_change(self):
        """Une cadence inconnue ne doit ni allonger ni raccourcir l attente."""
        assert R._faut_couper(plat=10, fenetre=150, muet=False,
                              sans_progres_s=301.0, cadence_s=0.0) is True

    def test_les_deux_autres_coupures_sont_intactes(self):
        assert R._faut_couper(plat=150, fenetre=150, muet=False,
                              sans_progres_s=0.0, cadence_s=5.0) is True
        assert R._faut_couper(plat=0, fenetre=150, muet=True,
                              sans_progres_s=0.0, cadence_s=5.0) is True

    def test_fenetre_nulle_ne_ressuscite_pas_la_coupure_par_les_passes(self):
        # `fenetre == 0` = « ne coupe pas sur les passes » (presque fini).
        assert R._faut_couper(plat=9999, fenetre=0, muet=False,
                              sans_progres_s=10.0, cadence_s=1.0) is False


class TestCablage:
    SOURCE = (RACINE / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_cadence_mesuree_est_bien_transmise(self):
        i = self.SOURCE.index("if _faut_couper(plat, fenetre, muet,")
        assert "cadence" in self.SOURCE[i:i + 300], \
            "la cadence est mesuree mais jamais passee a la coupure"

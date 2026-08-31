"""Le delai du processus pcbnew coupait un travail d UNE SECONDE.

⚠️ Mesure du 2026-08-31, A/B du plan de masse sur `stm32-100`. Le journal
porte TROIS fois :

    couture des ilots impossible (pcbnew child timed out after 60s)
    — board conserve

Consequence : le plan reste fragmente, des broches GND restent non reliees, et
rien ne le dit hormis un avertissement noye. La couture n a JAMAIS tourne sur
la plus grosse carte du banc.

⚠️ LE TRAVAIL N EST PAS LONG. Mesure directe sur les deux boards produits par
l A/B, machine au repos :

    ab_t1.kicad_pcb   stitch_zones   0,8 s
    ab_t1.kicad_pcb   fill_zones     1,4 s
    ab_t0.kicad_pcb   stitch_zones   0,7 s
    ab_t0.kicad_pcb   fill_zones     1,3 s

Moins d une seconde, coupee a soixante. Le delai n a donc pas ete atteint par
la DUREE du travail mais par la FAMINE DE CPU : un tirage de routage abandonne
continue de tourner dans la JVM — `PUT /jobs/{id}/cancel` repond 501, on ne
peut pas le tuer — a 400-500 % de CPU, pendant que le post-traitement s execute.

Nos propres tirages abandonnes sabotent les etapes qui les suivent. C est
structurel : la JVM execute deux jobs en parallele (verifie le 2026-08-29), et
le palier suivant demarre pendant que le precedent agonise.

⚠️ Un ralentissement mesure de plus de SOIXANTE-QUINZE fois. Le delai doit
donc absorber une contention de cet ordre, sans quoi il ne mesure pas la sante
de pcbnew mais la charge de la machine — et il echoue precisement quand la
carte est grosse, c est-a-dire quand la couture est le plus necessaire.

⚠️ On ne SUPPRIME pas le delai : un pcbnew reellement bloque tiendrait le
pipeline entier. On le rend proportionne au defaut qu il doit attraper.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestDelai:
    def test_il_absorbe_la_contention_mesuree(self):
        """0,8 s de travail, ralentissement mesure > 75x sous charge.

        Le delai doit couvrir tres largement ce facteur : sous les 300 s, on
        recree l echec silencieux de la couture sur les grosses cartes.
        """
        assert R._PCBNEW_RUNNER_TIMEOUT_S >= 300

    def test_il_reste_BORNE(self):
        # Sans borne, un pcbnew bloque tiendrait le pipeline entier.
        assert R._PCBNEW_RUNNER_TIMEOUT_S <= 900


class TestDiagnostic:
    def test_l_operation_est_NOMMEE_dans_l_erreur(self):
        """⚠️ « pcbnew child timed out after 60s » ne dit pas CE QUI a expire.

        Trois expirations dans un meme journal, trois operations differentes
        possibles (couture, remplissage, echappement) : sans le nom, on ne peut
        ni imputer ni corriger. C est ce qui a rendu ce defaut invisible.
        """
        src = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")
        # ⚠️ On verifie le HANDLER d expiration, pas le fichier entier — et
        # sans dependre du style de citation, l f-string imposant des simples
        # la ou j avais ecrit des doubles. Une garde qui teste la ponctuation
        # ne teste pas le comportement.
        i = src.index("except subprocess.TimeoutExpired")
        handler = src[i:i + 900]
        assert "payload.get(" in handler and "operation" in handler, (
            "l erreur d expiration ne nomme pas l operation qui a expire")


class TestCablage:
    def test_le_delai_est_bien_celui_du_sous_processus(self):
        src = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")
        i = src.index("def _run_pcbnew_operation(")
        corps = src[i:i + 1800]
        assert "timeout=_PCBNEW_RUNNER_TIMEOUT_S" in corps

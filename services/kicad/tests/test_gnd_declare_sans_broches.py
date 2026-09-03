"""Le net du plan reste DECLARE dans le DSN, mais sans broches a router.

⚠️ LE DERNIER VERROU de la sequence demandee par l utilisateur :

    ① plan de masse coule       ② coller les GND qui touchent le plan
    ③ LIER les GND qui ne touchent pas — piste ou via — AVANT les signaux
    ④ router les signaux        ⑤ escalader en gardant le cuivre …

`_confier_au_plan` RETIRAIT du DSN le bloc `(net GND (pins ...))` en entier.
Consequence mesuree le 2026-09-01 sur un DSN reel du pipeline :

    nets declares : 140        GND declare : NON

Donc chaque `(via ... (net GND) (type protect))` injecte referencait un net
absent du fichier, et la garde de resolubilite les ecartait tous — « 12 via(s)
ecartee(s) (GND x12) ». Le cuivre de masse pose a l etape ③ n etait donc JAMAIS
annonce au routeur : celui-ci pouvait le traverser sans le savoir, et les
broches que le plan n atteint pas restaient orphelines.

Retirer le net etait pourtant necessaire : sans cela le routeur ROUTE GND, et
le repli qui fait exactement cela a ete mesure DEGRADANT six fois sur six
(jusqu a 27 manquantes contre 4).

La sortie est de dissocier les deux : garder le net DECLARE — pour que le
routeur sache qu il existe et que la protection soit resoluble — mais lui
retirer ses BROCHES, pour qu il n ait rien a router dessus.

    avant :  (net GND (pins U1-1 U2-3 ...))   -> supprime entierement
    apres :  (net GND)                        -> declare, sans broche

⚠️ La grammaire Specctra rend `(pins ...)` optionnel dans une entree de
`network`. Que Freerouting l accepte reste a MESURER : c est pourquoi le
comportement est porte par une constante, et non code en dur.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402

LF = chr(10)


def _dsn(*nets: str) -> str:
    corps = "".join(
        "    (net %s%s      (pins U1-%d U2-%d)%s    )%s" % (n, LF, i, i, LF, LF)
        for i, n in enumerate(nets, start=1))
    return ("(pcb board" + LF + "  (network" + LF + corps + "  )" + LF
            + "  (wiring" + LF + "  )" + LF + ")")


class TestSectionNetwork:
    def test_seule_la_section_network_est_lue(self):
        """⚠️ Les nets du bloc `(wiring)` ne sont pas des DECLARATIONS.

        Les y compter rendrait la garde circulaire : elle validerait sa propre
        injection et n ecarterait plus jamais rien.
        """
        dsn = _dsn("SDA").replace("  (wiring" + LF,
                                  "  (wiring" + LF
                                  + '    (via "V" 1.0 2.0 (net INVENTE))' + LF)
        assert R._nets_declares_dsn(dsn) == {"SDA"}


class TestDeclarationSansBroches:
    def test_le_net_du_plan_reste_declare(self):
        texte, n = R._strip_net_from_dsn(_dsn("GND", "SDA"), "GND",
                                         garder_declaration=True)
        assert n == 2, "les broches doivent etre comptees comme confiees au plan"
        assert "(net GND)" in texte
        assert "U1-1" not in texte, "les broches de GND doivent disparaitre"
        assert "U1-2" in texte, "les autres nets ne sont pas touches"

    def test_le_net_declare_sans_broches_est_RESOLUBLE(self):
        # Le point entier de la manoeuvre : la protection du cuivre de masse
        # doit cesser d etre ecartee.
        texte, _ = R._strip_net_from_dsn(_dsn("GND", "SDA"), "GND",
                                         garder_declaration=True)
        assert "GND" in R._nets_declares_dsn(texte)

    def test_le_retrait_COMPLET_reste_possible(self):
        texte, n = R._strip_net_from_dsn(_dsn("GND", "SDA"), "GND",
                                         garder_declaration=False)
        assert n == 2
        assert "(net GND" not in texte
        assert "GND" not in R._nets_declares_dsn(texte)

    def test_un_net_absent_ne_change_rien(self):
        avant = _dsn("SDA")
        texte, n = R._strip_net_from_dsn(avant, "GND", garder_declaration=True)
        assert (texte, n) == (avant, 0)


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_confier_au_plan_porte_le_choix(self):
        i = self.SOURCE.index("def _confier_au_plan(")
        corps = self.SOURCE[i:i + 1200]
        assert "garder_declaration=" in corps, (
            "le choix n est pas transmis : la declaration ne peut pas survivre")

    def test_le_comportement_est_porte_par_une_CONSTANTE(self):
        # ⚠️ Non mesure a l ecriture : Freerouting peut refuser un net sans
        # broches. Le comportement doit pouvoir etre remis en cause sans
        # toucher au chemin critique.
        assert isinstance(R._GARDER_LE_NET_DU_PLAN_DECLARE, bool)

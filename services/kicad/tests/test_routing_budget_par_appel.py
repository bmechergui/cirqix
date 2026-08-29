"""Le budget de routage doit valoir pour l'APPEL, pas pour chaque niveau.

`route_auto` enchaîne jusqu'à quatre routeurs. Chacun recevait `req.timeout_s`
EN ENTIER : un appel pouvait donc valoir plusieurs fois le budget demandé.

Mesuré le 2026-08-20 sur le board STM32, `timeout_s: 1800` : **2547 s** au
total — Niveau 1, puis Freerouting, puis le Niveau 4 qui relance `kct route`
avec les mêmes 1800 s. Le client, lui, calcule son échéance à partir d'UN budget
(`routingAbortMs = budget + marge`) : il raccroche donc pendant que le service
travaille encore, et le travail déjà fait part à la poubelle.

Un budget qui ne borne rien n'est pas un budget. On calcule une échéance UNIQUE
à l'entrée, et chaque niveau reçoit le temps RESTANT.

⚠️ Un niveau ne doit pas être lancé avec des miettes : sous
`_MIN_LEVEL_BUDGET_S`, on passe au suivant plutôt que de démarrer un travail
condamné — un routeur tué en cours ne rend rien, alors qu'un niveau plus rapide
pourrait encore aboutir.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


class TestBudgetRestant:
    def test_le_restant_decroit_avec_le_temps(self):
        assert routing_router._remaining_budget_s(1000.0, now=100.0) == 900
        assert routing_router._remaining_budget_s(1000.0, now=900.0) == 100

    def test_le_restant_ne_devient_jamais_negatif(self):
        # Un budget négatif passé à un sous-processus serait interprété comme
        # « pas de limite » par certains outils : plancher à zéro.
        assert routing_router._remaining_budget_s(1000.0, now=1500.0) == 0

    def test_un_budget_epuise_n_autorise_plus_de_niveau(self):
        assert not routing_router._budget_suffisant(0)
        assert not routing_router._budget_suffisant(5)
        assert routing_router._budget_suffisant(routing_router._MIN_LEVEL_BUDGET_S)


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_aucun_niveau_ne_recoit_le_budget_brut_de_la_requete(self):
        # `req.timeout_s` sert à CALCULER l'échéance, une seule fois. Le passer
        # tel quel à un niveau réintroduit la multiplication du budget.
        code = "\n".join(
            ligne for ligne in self.SOURCE.splitlines()
            if not ligne.lstrip().startswith("#")
        )
        appels_bruts = [
            ligne for ligne in code.splitlines()
            if "req.timeout_s" in ligne and "deadline" not in ligne
        ]
        assert appels_bruts == [], f"budget brut encore passé : {appels_bruts}"

    def test_l_echeance_est_calculee_a_deux_niveaux_seulement(self):
        """Deux echeances imbriquees, pas une par palier ni une par niveau.

        Depuis l'escalade de couches (2026-08-21), le budget se lit a deux
        etages : `route_auto` borne l'APPEL ENTIER, escalade comprise, et
        passe le RESTANT a chaque palier ; `_route_auto_once` borne ce palier
        et sert le restant a chacun de ses quatre niveaux.

        Sans le premier etage, l'escalade multiplierait le budget par le nombre
        de paliers -- exactement le defaut corrige au niveau de la cascade.
        """
        assert self.SOURCE.count("deadline = _now() + req.timeout_s") == 2
        # Et le restant doit bien etre passe au palier, sinon chaque palier
        # repartirait du budget entier.
        #
        # ⚠️ Partager ce restant entre les essais a ete essaye le 2026-08-29
        # et s est revele DESASTREUX : 1800 s / 12 essais = 150 s chacun, trop
        # court pour router une carte de 100 composants — tous les paliers ont
        # rendu 0 %, contre 96 % avec le budget entier. Donner tout le restant
        # s adapte de soi-meme, une carte rapide laissant de quoi re-tirer.
        assert "timeout_s=max(restant, _MIN_LEVEL_BUDGET_S)" in self.SOURCE


class TestAucunNiveauNeDemarreSansBudget:
    """Un niveau lance avec zero seconde echoue instantanement -- pour rien.

    Mesure du 2026-08-21 : le Niveau 1 (kicad-tools) a consomme les 600 s du
    budget au premier palier d escalade. Freerouting a ensuite recu ZERO :

        Freerouting echoue (... timed out after 0 seconds) -- repli kicad-tools

    `subprocess.run(timeout=0)` leve immediatement. Le niveau n a pas ete
    « trop lent » : il n a jamais tourne. Pire, son echec a ete compte comme un
    echec de Freerouting, ce qui envoie chercher au mauvais endroit.

    Le garde existait sur le Niveau 1 seulement. Il doit couvrir CHAQUE niveau :
    mieux vaut passer au suivant -- ou rendre ce qu on a -- que consommer un
    tour de cascade pour un echec certain.
    """

    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_chaque_niveau_verifie_le_budget_avant_de_partir(self):
        """Un comptage de ratio serait un mauvais proxy : on verifie les ENTREES.

        Chaque niveau qui consomme du temps doit tester le budget sur la ligne
        meme qui decide de le lancer.
        """
        entrees = [
            "if is_simple and _budget_suffisant(",
            "if api_url is not None and _budget_suffisant(",
            "if paths is not None and _budget_suffisant(",
            "elif _budget_suffisant(",
        ]
        manquants = [e for e in entrees if e not in self.SOURCE]
        assert manquants == [], f"niveaux sans garde de budget : {manquants}"

    def test_la_boucle_d_escalade_verifie_aussi(self):
        assert "if meilleur is not None and not _budget_suffisant(restant)" in self.SOURCE

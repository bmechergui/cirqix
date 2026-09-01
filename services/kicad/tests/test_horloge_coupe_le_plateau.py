"""Quand la fenetre de passes dit « ne coupe pas », l HORLOGE doit trancher.

⚠️ Mesure du 2026-09-01, banc a placement fige, `stm32-100` : UN SEUL tirage a
tourne **plus de 62 minutes** sans jamais etre coupe, sur ces lignes repetees
a l infini dans le journal Freerouting :

    InsertFoundConnectionAlgo: via mask not found for net #18
    InsertFoundConnectionAlgo: insert via failed for net #18
    Autorouter Failed to route connection between ...

    2 unrouted   ·   2 unrouted   ·   2 unrouted   ·   ...

Deux connexions restantes, aucune ne progresse, et le routeur n abandonne pas.

POURQUOI RIEN NE COUPAIT — deux verrous qui se completent :

1. `_fenetre_stagnation(2)` rend **0** (`unrouted <= _PRESQUE_FINI`), et
   `fenetre == 0` veut dire « ne coupe pas sur les passes ». C est voulu : a
   deux connexions pres, un rattrapage tardif reste possible.

2. Le plafond d horloge `_PLAFOND_ATTENTE_S` n etait consulte QUE par
   `_routeur_muet`, donc uniquement pour un routeur SILENCIEUX. Celui-ci
   parlait — 3,4 millions de lignes — donc jamais muet, donc jamais coupe.

Le commentaire de la boucle decrivait pourtant exactement la regle attendue :

    « Le critere des PASSES ne coupe donc plus quand il ne reste presque
      rien ; seul l HORLOGE tranche alors, et elle tranche toujours. Sans
      elle, "ne jamais couper" recreerait les 40 minutes sur une carte a
      2,5 s la passe. »
    « ⚠️ Le plafond compte le temps SANS PROGRES, pas le temps total. »

C etait donc une garde DOCUMENTEE MAIS NON CABLEE — la faute que ce projet
traque partout. `_faut_couper` ne recevait aucun temps.

⚠️ Le plafond compte le temps SANS PROGRES, jamais le temps total : compte
depuis le debut, il a deja coupe un tirage legitime de la Nucleo apres UNE
passe, sur un board ou une passe dure plusieurs minutes.

⚠️ Couper est sans danger DEPUIS ce matin seulement : le board partiel est
desormais conserve (`746875c`, une panne ne prend plus la place du meilleur)
et le job abandonne reste recuperable dans la JVM (`29c9dfe`).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestPlateauSansFin:
    def test_la_fenetre_nulle_ne_protege_plus_indefiniment(self):
        # Le cas `stm32-100` : 2 non routes, fenetre 0, routeur bavard.
        assert R._faut_couper(plat=400, fenetre=0, muet=False,
                              sans_progres_s=R._PLAFOND_ATTENTE_S + 1) is True

    def test_sous_le_plafond_on_attend_encore(self):
        assert R._faut_couper(plat=400, fenetre=0, muet=False,
                              sans_progres_s=R._PLAFOND_ATTENTE_S - 1) is False

    def test_un_routage_qui_PROGRESSE_n_est_jamais_coupe(self):
        # `sans_progres_s` est remis a zero a chaque progres : un tirage long
        # mais qui avance ne doit jamais tomber sous cette regle.
        assert R._faut_couper(plat=0, fenetre=0, muet=False,
                              sans_progres_s=0.0) is False
        assert R._faut_couper(plat=0, fenetre=150, muet=False,
                              sans_progres_s=5.0) is False


class TestCriteresExistants:
    def test_la_fenetre_de_passes_coupe_toujours(self):
        assert R._faut_couper(plat=150, fenetre=150, muet=False,
                              sans_progres_s=0.0) is True

    def test_le_silence_coupe_toujours(self):
        assert R._faut_couper(plat=0, fenetre=0, muet=True,
                              sans_progres_s=0.0) is True

    def test_l_appel_sans_temps_reste_accepte(self):
        # Compatibilite : le parametre est optionnel, une valeur absente ne
        # coupe pas — sans mesure on attend, on n abandonne pas a l aveugle.
        assert R._faut_couper(plat=400, fenetre=0, muet=False) is False


class TestSansMesure:
    """⚠️ « Mesure a zero » n est pas « jamais mesure » — ma propre faute.

    `_passes_sans_progres` documente que `0` signifie SOIT un progres reel,
    SOIT un journal illisible : « sans mesure on ATTEND, on n abandonne pas a
    l aveugle ». Ma premiere version remettait l horloge a zero sur `plat == 0`
    — donc AUSSI quand rien n avait ete mesure. Resultat : l horloge repartait
    a chaque tour de boucle et ne coupait JAMAIS.

    Mesure du 2026-09-01 : `nucleo-f401` a passe 18 minutes dans son repli GND,
    bloquee a 6 non routes, sans que la garde livree une heure plus tot ne
    bronche. J ai commis la faute exacte contre laquelle ce projet met en garde
    partout, quelques heures apres l avoir ecrite.

    Le temps ne repart donc plus que sur une AVANCEE MESUREE — un changement du
    nombre de non routes — et il ne coupe pas tant qu aucune mesure n existe.
    """

    def test_sans_aucune_mesure_on_ne_coupe_pas(self):
        # Avant la premiere passe, `unrouted` est inconnu. Couper la reviendrait
        # a abandonner un board lent des la premiere seconde — ce qui est
        # arrive a la Nucleo avec la version « temps TOTAL ».
        assert R._temps_sans_progres(mesure_faite=False, depuis_s=9999.0) == 0.0

    def test_avec_une_mesure_le_temps_compte(self):
        assert R._temps_sans_progres(mesure_faite=True, depuis_s=42.0) == 42.0


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_boucle_transmet_le_temps_sans_progres(self):
        # ⚠️ Une regle correcte que personne n alimente est indistinguable
        # d une regle absente : c est precisement ce qui vient de couter
        # 62 minutes.
        i = self.SOURCE.index("if _faut_couper(")
        assert "sans_progres_s=" in self.SOURCE[i:i + 200]

    def test_le_temps_est_remis_a_zero_au_progres(self):
        assert "_dernier_progres_a = time.time()" in self.SOURCE

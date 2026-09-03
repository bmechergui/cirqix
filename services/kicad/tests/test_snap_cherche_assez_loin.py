"""Le snap cherchait une place dans un anneau de 4,5 mm, et renonçait.

⚠️ Mesure du 2026-09-02, `nucleo-f401`. Le cluster POWER existe enfin (ancre
`U1`, plafond 3 mm, les 8 condensateurs de découplage), et pourtant AUCUN
n'est déplacé. Le journal le dit pour les huit :

    snap C16 -> U1 : aucune place libre, non deplace
    snap C29 -> U1 : aucune place libre, non deplace
    … les huit

CAUSE — et ce n'est PAS celle que j'avais écrite. J'avais conclu à une
contradiction arithmétique entre le plafond POWER (3 mm) et la marge du halo
d'escape (5 mm) : « le snap cherche un point à la fois à moins de 3 et à plus
de 5 mm, impossible par construction ». **C'était faux.** Le plafond ne décide
que s'il faut ESSAYER ; le déplacement, lui, est accepté dès qu'il AMÉLIORE
l'écart libre. Un point à 5 mm aurait donc parfaitement remplacé un point à
58 mm.

La vraie cause est la PORTÉE de la recherche :

    _ESSAIS_RADIAUX = 4  ·  _PAS_RADIAL_MM = 1,5   ->  4,5 mm au-delà de la marge

Sur une ancre dense (marge 5 mm), `_cible_libre` n'explore donc que l'anneau
d'écart libre **5,0 à 9,5 mm**. Or les résistances de `nucleo-f401` occupent
précisément cet anneau — 13,7 mm d'entraxe, soit ~6,2 mm d'écart libre au corps
du LQFP-64. L'anneau est plein, la recherche rend `None`, et le snap renonce.

REMÈDE, sans nombre magique. On cherche jusqu'à l'écart libre où le membre se
trouve DÉJÀ : au-delà, la garde « ne peut qu'améliorer » refuserait le point de
toute façon. La borne est donc DÉDUITE de la situation, pas choisie. Un plafond
absolu la borne pour protéger le temps de calcul.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import placement_bypass as PB  # noqa: E402


class TestPorteeDeRecherche:
    def test_sans_ecart_connu_on_garde_la_portee_d_origine(self):
        # Compatibilite : un appelant qui ne sait pas d ou vient le membre
        # obtient le comportement anterieur.
        assert PB._essais_radiaux(None, marge=5.0) == PB._ESSAIS_RADIAUX

    def test_le_cas_mesure_cherche_BEAUCOUP_plus_loin(self):
        # C16 est a 62,5 mm du MCU, marge 5 mm : il faut pouvoir explorer
        # jusque-la, sinon on ne trouve jamais de place.
        n = PB._essais_radiaux(62.5, marge=5.0)
        assert n * PB._PAS_RADIAL_MM + 5.0 >= 62.5, (
            "la recherche s arrete avant l endroit ou le membre se trouve deja")

    def test_un_membre_deja_proche_ne_declenche_pas_une_grande_recherche(self):
        # Ecart 6 mm, marge 5 mm : un seul pas suffit a couvrir le reste.
        assert PB._essais_radiaux(6.0, marge=5.0) <= 2

    def test_on_cherche_au_moins_un_pas(self):
        # Meme si l ecart est SOUS la marge, la recherche doit avoir lieu :
        # rendre 0 essai equivaudrait a supprimer le snap.
        assert PB._essais_radiaux(1.0, marge=5.0) >= 1

    def test_la_recherche_est_BORNEE(self):
        # Un ecart absurde ne doit pas faire exploser le temps de calcul.
        assert PB._essais_radiaux(100000.0, marge=5.0) <= PB._ESSAIS_RADIAUX_MAX

    def test_le_plafond_laisse_de_la_place_aux_vrais_cas(self):
        # 68,7 mm est le pire ecart mesure sur nucleo-f401 : il doit tenir
        # SOUS le plafond, sinon le plafond redevient le vrai blocage.
        assert PB._essais_radiaux(68.7, marge=5.0) < PB._ESSAIS_RADIAUX_MAX


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "placement_bypass.py").read_text(
        encoding="utf-8")

    def _corps(self, nom: str) -> str:
        # ⚠️ La DERNIERE fonction du fichier n a pas de `def` suivant : sans
        # ce repli, la garde levait ValueError au lieu de mesurer.
        i = self.SOURCE.index("def %s(" % nom)
        j = self.SOURCE.find(chr(10) + "def ", i + 1)
        return self.SOURCE[i:j if j != -1 else len(self.SOURCE)]

    def test_la_recherche_utilise_REELLEMENT_la_portee_deduite(self):
        # ⚠️ Une regle correcte jamais appelee est indistinguable d une regle
        # absente. `_cible_libre` doit consommer `_essais_radiaux`, pas la
        # constante brute.
        corps = self._corps("_cible_libre")
        assert "_essais_radiaux(" in corps

    def test_le_snap_TRANSMET_l_ecart_actuel(self):
        # Sans lui, `_cible_libre` retombe sur la portee d origine et le
        # correctif serait inerte — exactement le defaut qu on repare.
        corps = self._corps("snap_cluster_members")
        i = corps.index("_cible_libre(")
        assert "ecart" in corps[i:i + 260], (
            "l ecart actuel n est pas transmis a la recherche")

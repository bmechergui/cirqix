"""Un repli GND qui a déjà échoué sur les mêmes broches ne se retente pas.

⚠️ Mesure du 2026-09-02, banc des quatre cartes, placements validés :

    carte           replis tentés   RETENUS   refusés
    nucleo-f401           2            0          0
    stm32-30              3            0          3
    stm32-60              3            0          2
    stm32-100             3            0          0

**Onze replis tentés. ZÉRO retenu.** Pas un seul n'a produit un meilleur board.

Le coût, lui, est énorme : le repli retire GND du plan, ce qui oblige
Freerouting à router **58 broches de masse en pistes**. Il explique l'essentiel
des 2795 s de `stm32-60` (trois replis) et des 3907 s de `stm32-100`. Sur cette
dernière, un seul repli a duré plus de vingt minutes — pour rattraper UNE
pastille.

⚠️ On ne SUPPRIME pas le repli. `CLAUDE.md` documente un cas réel où il a
fonctionné (`stm32-60` passée de 98 % à 100 % le 2026-08-31), et la garde qui
le compare ne peut de toute façon rien retenir de mauvais. Le supprimer
échangerait un gain rare contre une certitude de perte.

Ce qu'on retire, c'est la RÉPÉTITION. Les tirages successifs d'une même carte
produisent des états très proches : un repli refusé sur un jeu de broches
orphelines le sera sur le même jeu. On mémorise donc ce qui a déjà été tenté,
et on ne le refait pas.

⚠️ Aucun seuil, aucune valeur choisie. La règle est « on n'essaie pas deux fois
la même chose », pas « on n'essaie que N fois ».
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


class TestSignature:
    """La signature identifie CE QU'ON A ESSAYÉ DE RÉPARER, pas le board."""

    def test_les_memes_broches_donnent_la_meme_signature(self):
        a = R._signature_orphelines([("D3", "2"), ("J10", "1")])
        b = R._signature_orphelines([("D3", "2"), ("J10", "1")])
        assert a == b

    def test_l_ORDRE_ne_change_rien(self):
        # Le rapport DRC ne garantit pas l ordre : deux listes des memes
        # broches decrivent le meme probleme.
        a = R._signature_orphelines([("D3", "2"), ("J10", "1")])
        b = R._signature_orphelines([("J10", "1"), ("D3", "2")])
        assert a == b

    def test_des_broches_DIFFERENTES_donnent_une_signature_differente(self):
        # ⚠️ Sinon on refuserait un repli sur un probleme jamais tente.
        a = R._signature_orphelines([("D3", "2")])
        b = R._signature_orphelines([("D4", "2")])
        assert a != b

    def test_aucune_broche_donne_une_signature_stable(self):
        assert R._signature_orphelines([]) == R._signature_orphelines([])


class TestMemoire:
    def setup_method(self):
        R._replis_gnd_echoues.clear()

    def test_un_premier_essai_est_AUTORISE(self):
        assert R._repli_deja_tente([("D3", "2")]) is False

    def test_le_MEME_essai_est_refuse_ensuite(self):
        R._noter_repli_echoue([("D3", "2")])
        assert R._repli_deja_tente([("D3", "2")]) is True

    def test_un_essai_DIFFERENT_reste_autorise(self):
        # ⚠️ Le point qui compte : on ne bloque pas un probleme nouveau.
        R._noter_repli_echoue([("D3", "2")])
        assert R._repli_deja_tente([("J10", "1")]) is False

    def test_l_ordre_n_empeche_pas_la_reconnaissance(self):
        R._noter_repli_echoue([("D3", "2"), ("J10", "1")])
        assert R._repli_deja_tente([("J10", "1"), ("D3", "2")]) is True

    def test_la_memoire_se_vide(self):
        # Entre deux cartes, rien ne doit subsister — sinon la carte suivante
        # heriterait des echecs de la precedente.
        R._noter_repli_echoue([("D3", "2")])
        R._replis_gnd_echoues.clear()
        assert R._repli_deja_tente([("D3", "2")]) is False


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_site_d_appel_CONSULTE_la_memoire(self):
        # ⚠️ Une regle correcte jamais appelee est indistinguable d une regle
        # absente.
        i = self.SOURCE.rindex("repli sur un routage incluant GND")
        fenetre = self.SOURCE[max(0, i - 1200):i + 1200]
        assert "_repli_deja_tente(" in fenetre

    def test_un_echec_est_NOTE(self):
        # Sans cela la memoire reste vide et le correctif est inerte.
        assert "_noter_repli_echoue(" in self.SOURCE

    def test_la_memoire_est_VIDEE_a_chaque_appel(self):
        # Le repli est mémorisé PAR APPEL de route_auto : deux cartes
        # differentes ne doivent pas se contaminer.
        i = self.SOURCE.index("def route_auto(")
        corps = self.SOURCE[i:i + 6000]
        assert "_replis_gnd_echoues.clear()" in corps

"""Ne pas re-tirer un palier hors d atteinte : monter d une couche.

Mesure du 2026-08-29, stm32-100 (100 composants, 208x156 mm) : trois tirages
a 2 couches ont consomme les 3600 s du budget — 60 %, 70 %, puis « budget
epuise avant le Niveau 4 ». La carte n a JAMAIS essaye 4 couches, alors que
c est le seul levier qui lui manquait.

L ecart entre deux tirages Freerouting sur le meme board est borne : 65, 77
et 91 % sur la Nucleo, soit 26 points au plus. Sous ~75 %, aucun re-tirage
ne rattrape 100 % ; le budget depense la est du budget vole au palier
suivant.
"""
from __future__ import annotations

from routers.routing import _tirages_epuises_au_palier, _SEUIL_REDRAW_PCT


def test_un_palier_loin_du_but_ne_merite_pas_de_re_tirage():
    assert _tirages_epuises_au_palier(60) is True
    assert _tirages_epuises_au_palier(70) is True


def test_un_palier_presque_bon_merite_ses_re_tirages():
    """91 % -> 100 % est un rattrapage MESURE : on ne coupe pas dessus."""
    assert _tirages_epuises_au_palier(91) is False
    assert _tirages_epuises_au_palier(_SEUIL_REDRAW_PCT) is False


def test_le_seuil_laisse_la_place_a_l_ecart_mesure():
    """26 points d ecart mesure : un seuil trop haut couperait un rattrapage."""
    assert 100 - _SEUIL_REDRAW_PCT <= 26, (
        "seuil trop bas : on re-tirerait des paliers hors d atteinte")
    assert _SEUIL_REDRAW_PCT >= 75, (
        "seuil trop haut : on couperait un palier qui pouvait encore aboutir")


def test_un_echec_de_moteur_ne_declenche_pas_l_escalade():
    """0 % « aucun moteur » n est pas un verdict de routage.

    Le troisieme tirage de stm32-100 a rendu 0 % parce qu aucun moteur n a
    tourne. Traiter ce zero comme une mesure ferait monter d une couche sur
    une panne — on re-tire au meme palier.
    """
    assert _tirages_epuises_au_palier(0) is False


# ---------------------------------------------------------------------------
# Cablage — la regle doit s appliquer DANS la boucle, pas seulement exister.
# ---------------------------------------------------------------------------

import inspect

from routers.routing import route_auto


def test_la_regle_est_appliquee_dans_la_boucle():
    src = inspect.getsource(route_auto)
    assert "_tirages_epuises_au_palier(" in src, (
        "regle jamais appliquee : les tirages perdus le restent")


def test_le_compteur_du_palier_est_remis_a_zero_en_montant():
    """Sans remise a zero, un palier bas condamnerait tous les suivants."""
    src = inspect.getsource(route_auto)
    i = src.index("_tirages_epuises_au_palier(")
    avant = src[:i]
    assert "palier != palier_courant" in avant, (
        "aucune detection de changement de palier")
    assert "meilleur_du_palier = 0" in avant


def test_le_meilleur_du_palier_est_alimente():
    src = inspect.getsource(route_auto)
    assert "meilleur_du_palier = max(" in src, (
        "compteur jamais mis a jour : la regle lirait toujours 0")

"""Freerouting tourne a vide : plafonner ses passes.

Mesure du 2026-08-29 sur 495 jobs du journal Freerouting :

    226 422 passes au total, dont 191 695 SANS le moindre progres — 84 %

Profil constant : le routeur travaille dans les premieres passes, puis repete
le meme score et le meme nombre de nets non routes jusqu a la 999e.

    pass    4  score 772.19  unrouted 46      <- tout le travail est ici
    pass  999  score 772.19  unrouted 46      <- 995 passes plus tard

⚠️ Un plafond BAS serait faux. 19 % des jobs progressent encore apres la
passe 30, certains jusqu a la 997e — et ce sont ceux qui finissent a 1 seul
net non route. Le plafond se choisit sur la distribution, pas sur le pire cas
observe :

    dernier progres <=  10 : 72 %
    dernier progres <=  30 : 81 %
    dernier progres <= 100 : 89 %
"""
from __future__ import annotations

import inspect

from routers.routing import _REGLAGES_FREEROUTING, _PLAFOND_PASSES, _route_with_freerouting_api


def test_le_plafond_est_envoye_au_routeur():
    assert _REGLAGES_FREEROUTING, (
        "aucun reglage envoye : Freerouting garde son defaut de 9999 passes")
    assert _REGLAGES_FREEROUTING.get("max_passes") == _PLAFOND_PASSES


def test_le_plafond_couvre_la_grande_majorite_des_jobs_mesures():
    """<= 100 couvre 89 % ; on garde une marge au-dessus."""
    assert _PLAFOND_PASSES >= 100, (
        "plafond trop bas : 19 % des jobs progressent encore apres la passe 30")
    assert _PLAFOND_PASSES <= 300, (
        "plafond trop haut : au-dela, on repaye les passes a vide qu on veut eviter")


def test_les_reglages_sont_transmis_a_l_enqueue():
    src = inspect.getsource(_route_with_freerouting_api)
    assert "router_settings" in src, "reglages jamais transmis au job"


def test_seul_le_plafond_est_impose():
    """Les autres defauts de Freerouting ont battu toutes nos variantes.

    Mesure du 2026-08-28 : fanout, couts de vias et passes d optimiseur —
    aucun reglage essaye n a fait mieux que le defaut. On ne change donc QUE
    ce qu une mesure condamne.
    """
    assert set(_REGLAGES_FREEROUTING) == {"max_passes"}, (
        "un reglage non mesure s est glisse dans la charge")

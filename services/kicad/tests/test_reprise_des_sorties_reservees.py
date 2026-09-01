"""La position reservee AVANT le routage doit etre REJOUEE, pas recalculee.

⚠️ Defaut trouve le 2026-08-31, et c est celui qui produit la broche GND
orpheline. La chaine calcule, AVANT le routage, une position de via valide pour
chaque broche fine-pitch — quand la place existe encore. Le journal le dit :
« 21 via(s) d echappement places avant routage, 0 renonce(s) ».

Puis `_reposer_vias_reserves` ne transmettait au runner que `ref` et `pad` :

    "pads": json.dumps([[v["ref"], v["pad"]] for v in vias])

Les `via_x` / `via_y` calcules etaient JETES. `_escape_pads` repartait donc de
zero, sur le board ROUTE, ou les pistes de signal occupent desormais les
couloirs — et renoncait. La reservation ne reservait rien : elle mesurait une
place qu on ne se donnait jamais la peine de reprendre.

⚠️ Rejouer n est pas forcer. Une position reservee peut etre devenue illegale :
on la VERIFIE avec les criteres exacts de `_choisir_sortie` (trajet degage a la
marge de la piste, point de chute degage a la marge du via) et on ne retombe
sur la recherche que si elle ne passe plus. Poser sans verifier ramenerait les
courts-circuits mesures le 2026-08-23.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as RUN  # noqa: E402

SOURCE_ROUTING = (_SERVICE_ROOT / "routers" / "routing.py").read_text(
    encoding="utf-8")


class TestValiditeDUneSortieReservee:
    def test_une_sortie_degagee_est_acceptee(self):
        # Aucun obstacle : la position reservee reste bonne.
        assert RUN._sortie_reservee_valide(
            0, 0, 1_200_000, 0, obstacles=[], marge=500_000,
            exempt=None, marge_piste=325_000) is True

    def test_un_obstacle_SUR_LE_TRAJET_la_refuse(self):
        # Une piste de signal posee pendant le routage, en travers.
        obstacle = (500_000, -100_000, 700_000, 100_000)
        assert RUN._sortie_reservee_valide(
            0, 0, 1_200_000, 0, obstacles=[obstacle], marge=500_000,
            exempt=None, marge_piste=325_000) is False

    def test_un_obstacle_AU_POINT_DE_CHUTE_la_refuse(self):
        # Le trajet est libre, mais le via ne tient plus a l arrivee.
        obstacle = (1_300_000, -100_000, 1_500_000, 100_000)
        assert RUN._sortie_reservee_valide(
            0, 0, 1_200_000, 0, obstacles=[obstacle], marge=500_000,
            exempt=None, marge_piste=100_000) is False

    def test_l_exemption_du_pad_est_TRANSMISE(self):
        # ⚠️ Mes deux premieres versions de ce test placaient la boite du pad
        # dans `obstacles` — ce qui n arrive jamais, `_obstacles_d_un_autre_net`
        # ne rendant que le cuivre d un AUTRE net — puis choisissaient une
        # geometrie ou l obstacle bloquait de toute facon APRES la sortie du
        # pad. Ce qui doit etre garde ici est plus simple et plus juste : que
        # `exempt` soit bien TRANSMIS a `_trajet_libre`. Trajet entierement
        # DANS la boite du pad, obstacle en travers :
        propre = (-150_000, -150_000, 150_000, 150_000)
        obstacle = (50_000, -10_000, 60_000, 10_000)
        assert RUN._sortie_reservee_valide(
            0, 0, 100_000, 0, obstacles=[obstacle], marge=10_000,
            exempt=propre, marge_piste=325_000) is True
        # Sans exemption, le meme trajet est refuse des le depart — c est la
        # mesure du 2026-08-23 : 0 broche fine-pitch ne pouvait sortir.
        assert RUN._sortie_reservee_valide(
            0, 0, 100_000, 0, obstacles=[obstacle], marge=10_000,
            exempt=None, marge_piste=325_000) is False


class TestCablage:
    def test_la_repose_transmet_les_COORDONNEES(self):
        # ⚠️ La garde porte sur ce qui est ENVOYE au runner. Un rejeu correct
        # que personne n alimente est indistinguable d un rejeu absent.
        i = SOURCE_ROUTING.index("def _reposer_vias_reserves(")
        corps = SOURCE_ROUTING[i:i + 2000]
        assert '[[v["ref"], v["pad"]] for v in vias]' not in corps, (
            "la repose jette encore les positions reservees")
        assert 'v["via_x"]' in corps and 'v["via_y"]' in corps

    def test_le_runner_accepte_les_deux_formes(self):
        # `[ref, pad]` (fanout post-routage, sans reservation) et
        # `[ref, pad, x, y]` (repose d une position reservee).
        source = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
            encoding="utf-8")
        i = source.index("def _escape_pads(")
        corps = source[i:i + 4000]
        assert "len(cible) >= 4" in corps
        assert "_sortie_reservee_valide(" in corps

    def test_le_rejeu_est_COMPTE_et_rendu(self):
        # Un rejeu qui ne se compte pas ne peut pas etre distingue d un rejeu
        # qui n a jamais lieu — le defaut meme qu on corrige ici.
        source = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
            encoding="utf-8")
        # ⚠️ Le CORPS de la fonction, pas une tranche de longueur fixe : les
        # 5000 caracteres d origine ont ete depasses le 2026-09-01 et la garde
        # a cesse de mesurer ce qu elle visait, sans que son intention change.
        i = source.index("def _escape_pads(")
        corps = source[i:source.index(chr(10) + "def ", i + 1)]
        assert '"reprises"' in corps

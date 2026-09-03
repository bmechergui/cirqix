"""Refaire le placement a chaque run rend toute comparaison ININTERPRETABLE.

⚠️ Constat de l utilisateur le 2026-08-31, et il a raison contre moi : le banc
regenere schema, PCB et PLACEMENT a chaque execution. Chaque comparaison
melange donc DEUX variables — ce que je reproche a tous les autres mecanismes
depuis deux jours, et que j avais laisse dans mon propre instrument.

La preuve tombe le jour meme, `nucleo-f401`, deux runs consecutifs du MEME
code :

    banc precedent   tirages a 97 %, 98 %, 98 %
    banc suivant     tirages a 67 %, 77 %, 43 %

Le routage n a pas change. Le PLACEMENT, si.

Le board place est desormais conserve (`output/2_placement.kicad_pcb`). Le
reutiliser rend la mesure CONTROLEE : une seule variable bouge, celle qu on
etudie. Et il economise le placement, qui coute 10 a 20 minutes par carte —
trois tirages sur `arduino-uno` ce jour-la.

⚠️ Ce n est PAS le mode par defaut. Un banc de reference doit exercer la chaine
ENTIERE, placement compris : c est lui qui mesure le produit. Le placement fige
sert a etudier une etape AVAL, et il faut le demander.

⚠️ Un placement fige ABSENT doit etre DIT, jamais contourne en silence : on
croirait mesurer a placement constant alors qu on en aurait regenere un.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT / "scripts"))

import banc_exemples as B  # noqa: E402


class TestOption:
    def test_le_drapeau_existe(self):
        import inspect
        src = inspect.getsource(B.main)
        assert "--placement-fige" in src, (
            "aucun moyen de demander un placement constant")

    def test_il_n_est_PAS_le_defaut(self):
        """⚠️ Un banc de reference doit exercer la chaine ENTIERE. Le placement
        fige sert a etudier une etape aval — il se demande."""
        import inspect
        assert B._PLACEMENT_FIGE is False, (
            "le banc mesurerait une chaine amputee sans qu on l ait demande")
        src = inspect.getsource(B.main)
        assert "_PLACEMENT_FIGE = True" in src


class TestReutilisation:
    def test_le_board_conserve_est_relu(self):
        import inspect
        src = inspect.getsource(B._un_tirage)
        assert "2_placement.kicad_pcb" in src
        # ⚠️ Fenetre des DEUX cotes : le chemin du board est defini juste
        # AVANT le test du drapeau. Une garde qui ne regarde que l aval mesure
        # l ordre des lignes, pas le cablage.
        i = src.index("_PLACEMENT_FIGE")
        autour = src[max(0, i - 400):i + 500]
        assert "2_placement.kicad_pcb" in autour, (
            "le drapeau ne mene pas a la relecture du board conserve")
        assert "read_bytes()" in autour

    def test_un_placement_absent_est_DIT(self):
        """⚠️ Contourner en silence ferait croire a une mesure a placement
        constant alors qu on en aurait regenere un."""
        import inspect
        src = inspect.getsource(B._un_tirage)
        i = src.index("_PLACEMENT_FIGE")
        bloc = src[i:i + 900]
        assert "logger" in bloc or "print" in bloc

    def test_le_placement_reste_CONSERVE_dans_les_deux_modes(self):
        # Sans conservation, la prochaine mesure figee n aurait rien a relire.
        import inspect
        src = inspect.getsource(B._un_tirage)
        assert src.count("2_placement.kicad_pcb") >= 2

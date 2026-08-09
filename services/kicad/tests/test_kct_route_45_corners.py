"""Angles de routage professionnels : des coins à 45°, jamais à 90°.

Un routage pro ne comporte pas de coin droit — les pistes tournent à 45°.
kicad-tools sait le faire (``convert_45_corners``), mais **Patch Cirqix #7**
avait dû neutraliser cette passe : en déplaçant la géométrie, elle taille des
diagonales dans le cuivre des pads voisins, et le collision checker par cellules
ne voit pas ces coupes continues (issue upstream #750). Mesuré alors :
27 ``shorting_items`` avec l'optimiseur actif contre 3 sans.

Deux constats du 2026-07-31 ont motivé ce chantier :

1. ``KCT_SAFE_OPTIMIZE`` n'était fixée **nulle part** dans le code Cirqix — le
   patch était documenté dans ``DEPENDENCIES.md`` et jamais appliqué. Les passes
   dangereuses tournaient donc à chaque routage : **204 erreurs DRC** sur un
   board mesuré (107 clearance, 84 solder_mask_bridge, 13 courts).
2. Le board de référence de juillet n'a que 62 % de ses segments sur
   0/45/90/135° — le reste part dans des angles arbitraires (52,5°, 130,1°…).

La réconciliation est native : le patch est enfin appliqué au sous-processus de
routage, et les 45° sont réintroduits **après**, avec
``OptimizationConfig(drc_aware=True)`` qui restaure les segments d'origine de
tout net dont l'optimisation augmente les violations — garde par catégorie
comprise (issue #3138), qui refuse aussi l'échange d'une violation contre une
autre à total constant.

Générale par construction : la décision est prise **par net**, à partir du DRC
réel du profil fabricant. Aucun réglage propre à une carte, et le placement
n'est jamais touché.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kicad-tools" / "src"))

from tools import kct_route  # noqa: E402

_BOARD = b"(kicad_pcb (segment (start 0 0) (end 5 0) (net 1)))"


def test_patch_7_applique_au_sous_processus_de_routage():
    """``KCT_SAFE_OPTIMIZE`` doit atteindre le sous-processus kct.

    Sans elle, les passes qui déplacent la géométrie tournent pendant le
    routage — 204 erreurs DRC mesurées le 2026-07-31.
    """
    env = kct_route._kct_env()

    assert env.get("KCT_SAFE_OPTIMIZE") == "1"


def test_notre_processus_garde_la_passe_45_disponible(monkeypatch):
    """La variable ne doit PAS fuiter dans le processus courant.

    ``OptimizationConfig.__post_init__`` désactive ``convert_45_corners`` quand
    elle est présente : la post-conversion deviendrait un no-op silencieux.
    """
    monkeypatch.delenv("KCT_SAFE_OPTIMIZE", raising=False)
    from kicad_tools.router import OptimizationConfig

    assert OptimizationConfig(convert_45_corners=True).convert_45_corners is True


def test_conversion_45_est_drc_aware(monkeypatch):
    """La conversion doit tourner en mode rollback, pas à l'aveugle."""
    vu: dict[str, object] = {}

    def faux_optimize_pcb(src, dst, fn, config, *a, **kw):
        vu["drc_aware"] = config.drc_aware
        vu["mfr"] = config.drc_manufacturer
        vu["layers"] = config.drc_layers
        vu["convert_45"] = config.convert_45_corners
        # Les passes que Patch #7 a mesurées dangereuses restent OFF.
        vu["compress"] = config.compress_staircase
        vu["pull_tight"] = config.pull_tight
        Path(dst).write_bytes(b"(kicad_pcb CONVERTI)")
        return type("S", (), {"corners_before": 8, "corners_after": 0,
                              "drc_errors_before": 3, "drc_errors_after": 3})()

    monkeypatch.setattr("kicad_tools.router.optimizer.pcb.optimize_pcb",
                        faux_optimize_pcb)

    obtenu = kct_route.convert_corners_45_drc_aware(_BOARD, "jlcpcb", 4)

    assert obtenu == b"(kicad_pcb CONVERTI)"
    assert vu["drc_aware"] is True
    assert vu["mfr"] == "jlcpcb"
    assert vu["layers"] == 4
    assert vu["convert_45"] is True
    assert vu["compress"] is False, "Patch #7 : passe mesurée dangereuse"
    assert vu["pull_tight"] is False, "Patch #7 : passe mesurée dangereuse"


def test_un_echec_de_conversion_ne_perd_jamais_le_routage(monkeypatch):
    """Une amélioration esthétique ne doit pas coûter un routage."""
    def boum(src, dst, fn, config, *a, **kw):
        raise RuntimeError("optimiseur cassé")

    monkeypatch.setattr("kicad_tools.router.optimizer.pcb.optimize_pcb", boum)

    assert kct_route.convert_corners_45_drc_aware(_BOARD, "jlcpcb", 4) == _BOARD


def test_no_op_si_la_variable_fuit_dans_le_processus(monkeypatch):
    """Garde explicite : mieux vaut ne rien faire que croire avoir converti."""
    monkeypatch.setenv("KCT_SAFE_OPTIMIZE", "1")

    assert kct_route.convert_corners_45_drc_aware(_BOARD, "jlcpcb", 4) == _BOARD

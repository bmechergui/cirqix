"""D-2026-09-29-a : le banc s'arrête de re-placer à partir de 95 % sans erreur,
comme l'orchestrateur (`SEUIL_SANS_REPLACEMENT_PCT`). Un banc qui re-place là
où la production ne le fait plus mesurerait un temps qu'aucun client ne paie.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
PIPELINE = RACINE / "examples" / "led-blinker-full-pipeline" / "run_pipeline.py"
# `.parent.parent` : dans l image Docker le service est `/app` (un seul parent).
ORCH = RACINE.parent.parent / "packages" / "agents" / "src" / "orchestrator.ts"


def test_meme_seuil_que_l_orchestrateur():
    if not ORCH.is_file():
        pytest.skip("orchestrateur TS absent : image Docker du service seul")
    banc = re.search(r"^SEUIL_SANS_REPLACEMENT_PCT = (\d+)", PIPELINE.read_text(encoding="utf-8"), re.M)
    prod = re.search(r"SEUIL_SANS_REPLACEMENT_PCT = (\d+)", ORCH.read_text(encoding="utf-8"))
    assert banc and prod and banc.group(1) == prod.group(1) == "95"


def test_la_boucle_s_arrete_au_seuil_sans_erreur():
    src = PIPELINE.read_text(encoding="utf-8")
    boucle = src[src.index("for essai in range("):]
    assert "if routed >= SEUIL_SANS_REPLACEMENT_PCT and erreurs == 0:" in boucle
    i = boucle.index("if routed >= SEUIL_SANS_REPLACEMENT_PCT and erreurs == 0:")
    assert "break" in boucle[i:i + 400]
    # avant l agrandissement de carte : on ne prepare pas un essai qui n aura pas lieu
    assert i < boucle.index("taille_suivante(")


def test_a_95_avec_erreurs_on_re_route_le_meme_placement():
    """Regle du 2026-10-01 : le placement est deja verifie au DRC ; une erreur
    DRC apres routage vient du routage. A >= 95 %, l essai suivant reprend le
    MEME placement (ni /place/auto, ni agrandissement), comme `placementAGarder`."""
    src = PIPELINE.read_text(encoding="utf-8")
    boucle = src[src.index("for essai in range("):]
    assert "if place_garde is not None:" in boucle
    assert boucle.index("if place_garde is not None:") < boucle.index('_post("/place/auto"')
    assert "place_garde = place" in boucle
    agrandir = boucle.index("taille_suivante(")
    assert "if place_garde is None:" in boucle[agrandir - 300:agrandir]


def test_le_reroutage_garde_reprend_au_palier_atteint():
    """2026-10-02 : carte-09, trois reroutages repartant de 2 couches (82 min)."""
    src = PIPELINE.read_text(encoding="utf-8")
    boucle = src[src.index("for essai in range("):]
    assert 'requete["palier_depart"] = palier_garde' in boucle
    assert boucle.index('requete["palier_depart"]') < boucle.index('_post("/route/auto", requete)')
    assert 'palier_garde = couches if' in boucle


def test_un_routage_sans_board_ne_compte_pas():
    """2026-10-01, carte-10 : « 98 % » rendu par des tirages figes, sans board
    (0 via, 280 erreurs au DRC du board place). Il ne doit ni gagner ni verrouiller."""
    src = PIPELINE.read_text(encoding="utf-8")
    assert 'if res_r.get("skipped") or not res_r.get("kicad_pcb_b64"):' in src

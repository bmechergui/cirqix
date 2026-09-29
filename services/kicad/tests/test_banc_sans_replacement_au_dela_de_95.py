"""D-2026-09-29-a : le banc s'arrête de re-placer à partir de 95 % sans erreur,
comme l'orchestrateur (`SEUIL_SANS_REPLACEMENT_PCT`). Un banc qui re-place là
où la production ne le fait plus mesurerait un temps qu'aucun client ne paie.
"""
from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
PIPELINE = RACINE / "examples" / "led-blinker-full-pipeline" / "run_pipeline.py"
ORCH = RACINE.parents[1] / "packages" / "agents" / "src" / "orchestrator.ts"


def test_meme_seuil_que_l_orchestrateur():
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

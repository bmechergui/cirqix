"""Aucun caractere de controle parasite dans le code du service.

⚠️ QUATRE FOIS le 2026-08-29/30, une edition programmatique a interprete un
echappement AVANT d ecrire le fichier, y laissant un caractere invisible :

  1. `\(zone\b`      -> `\(zone` + BACKSPACE : motif mort, la fonction rendait
                        `{}` sur une entree valide, sans exception ;
  2. `\n` dans le shell -> lettre `n` echappee, argument de plus passe a la
                        JVM, `bash -n` validait pourtant la ligne ;
  3. le test cense attraper le n°2, dont le motif avait lui aussi perdu un
     antislash ;
  4. `\(footprint\b`  -> BACKSPACE a nouveau : la selection des pastilles
                        signal ne retenait RIEN.

Chaque fois le fichier se LIT normalement — le caractere ne s affiche pas — et
les tests passent, parce qu ils exercent la fonction avec une fixture qui ne
contient pas le cas reel.

Un caractere de controle n a aucune raison d etre dans du code source. Cette
garde le dit une fois pour toutes, sur TOUS les fichiers du service.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[1]
_CONTROLE = {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
             0x0B, 0x0C, 0x0E, 0x0F, 0x1A, 0x1B}


def _fichiers():
    for dossier in ("routers", "tools", "scripts"):
        for f in sorted((_RACINE / dossier).rglob("*.py")):
            if "kicad-tools" in str(f) or "circuit_synth" in str(f):
                continue
            yield f
    yield _RACINE / "main.py"


@pytest.mark.parametrize("fichier", list(_fichiers()), ids=lambda f: f.name)
def test_aucun_caractere_de_controle(fichier):
    brut = fichier.read_bytes()
    for i, octet in enumerate(brut):
        if octet in _CONTROLE:
            contexte = brut[max(0, i - 45):i].decode("utf-8", "replace")
            pytest.fail(
                f"caractere de controle 0x{octet:02X} a l octet {i} de "
                f"{fichier.name} — un echappement a ete interprete trop tot. "
                f"Contexte : ...{contexte}")

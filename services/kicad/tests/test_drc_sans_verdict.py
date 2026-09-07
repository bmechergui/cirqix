"""Un DRC indisponible ne doit pas valoir « zéro erreur ».

⚠️ DÉFAUT CONNU, ASSUMÉ DANS LE CODE, ET JAMAIS CORRIGÉ. `_rapport_drc` rend un
dict vide quand `kicad-cli` manque ou que le board ne charge pas, et son propre
commentaire le dit :

    « ERROR, pas WARNING : les appelants lisent le dict vide comme "rien a
      signaler". TANT QU ILS LE FONT, ce journal est le seul endroit ou
      l absence de verdict est visible. »

Le journal n est pas un correctif. Les six gardes « une réparation ne peut
qu améliorer » s écrivent toutes :

    si erreurs(candidat) > erreurs(original) :  rejeter le candidat

Sans verdict, les DEUX côtés valent 0, `0 > 0` est faux, et le candidat est
ACCEPTÉ SANS JUGEMENT. Toute garde « ne peut qu améliorer » devient donc
« accepte tout » dès que le DRC est muet — exactement quand on en a le plus
besoin, puisqu un board illisible est aussi un board suspect.

C est la famille déjà corrigée trois fois ailleurs : un échec qui rend la même
valeur que son cas normal.
"""
import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing  # noqa: E402


_BOARD = b"(kicad_pcb (version 20240108))"
_AUTRE = b"(kicad_pcb (version 20240108) (segment))"


def test_un_rapport_sans_verdict_se_declare(monkeypatch):
    """L absence de verdict doit être LISIBLE dans le rapport, pas devinée."""
    monkeypatch.setattr(routing.shutil, "which", lambda _: None)
    rapport = routing._rapport_drc(_BOARD)
    assert routing._sans_verdict(rapport) is True


def test_un_vrai_rapport_porte_bien_un_verdict():
    assert routing._sans_verdict({"violations": []}) is False
    assert routing._sans_verdict({"violations": [{"severity": "error"}]}) is False


def test_la_garde_refuse_le_candidat_quand_le_DRC_est_muet(monkeypatch):
    """Sans verdict : on garde le board REÇU, jamais le candidat non jugé."""
    monkeypatch.setattr(routing, "_rapport_drc", lambda _: {"_sans_verdict": True})
    assert routing._aggrave_le_board(_BOARD, _AUTRE) is True


def test_la_garde_accepte_une_vraie_amelioration(monkeypatch):
    rapports = {
        _BOARD: {"violations": [{"severity": "error"}, {"severity": "error"}]},
        _AUTRE: {"violations": [{"severity": "error"}]},
    }
    monkeypatch.setattr(routing, "_rapport_drc", lambda b: rapports[b])
    assert routing._aggrave_le_board(_BOARD, _AUTRE) is False


def test_la_garde_refuse_une_vraie_degradation(monkeypatch):
    rapports = {
        _BOARD: {"violations": []},
        _AUTRE: {"violations": [{"severity": "error"}]},
    }
    monkeypatch.setattr(routing, "_rapport_drc", lambda b: rapports[b])
    assert routing._aggrave_le_board(_BOARD, _AUTRE) is True


def test_l_egalite_est_acceptee(monkeypatch):
    """Ne pas aggraver suffit : une réparation neutre reste légitime."""
    monkeypatch.setattr(routing, "_rapport_drc", lambda _: {"violations": []})
    assert routing._aggrave_le_board(_BOARD, _AUTRE) is False


def test_les_avertissements_ne_bloquent_rien(monkeypatch):
    rapports = {
        _BOARD: {"violations": []},
        _AUTRE: {"violations": [{"severity": "warning"}] * 40},
    }
    monkeypatch.setattr(routing, "_rapport_drc", lambda b: rapports[b])
    assert routing._aggrave_le_board(_BOARD, _AUTRE) is False


def test_aucune_garde_ne_compare_plus_a_la_main():
    """Une règle correcte appliquée à un seul site ne protège pas ses sœurs.

    On s ancre sur la FORME du défaut : plus aucune comparaison directe de deux
    `_compte_erreurs(_rapport_drc(...))`, qui redeviendrait aveugle au verdict
    manquant. C est ce qui a laissé six gardes identiques toutes fausses.
    """
    src = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")
    assert "_compte_erreurs(_rapport_drc" not in src

"""Le Géomètre doit dire qu'il a tourné — le silence n'est pas une preuve.

Dans `auto_place`, TOUTES les branches qui journalisent le CMA-ES sont des
échecs ou des réparations :

    - sous-processus en échec        → warning
    - exception                      → exception
    - conflits ERROR introduits      → warning + restauration
    - dérive de déplacement          → warning + restauration
    - réparation post-CMA-ES         → info (seulement si `n_err_before`)

Quand il réussit proprement, **rien n'est écrit**. Un succès silencieux est donc
indistinguable d'une étape jamais exécutée.

C'est précisément la condition qui a coûté des semaines à ce projet : le
Géomètre n'a JAMAIS tourné en production (`signal.signal` hors thread
principal), et personne ne pouvait le voir — ses tests passaient, la production
était muette. Le correctif d'alors fut le sous-processus ; celui-ci est
l'observabilité qui aurait permis de le détecter.

Constaté le 2026-08-21 : sur un run complet de 19 minutes dont ~15 de placement,
le journal ne porte AUCUNE trace CMA-ES. Impossible de dire si le Géomètre a
raffiné, a été sauté, ou a échoué en silence.

⚠️ Ce test verrouille l'OBSERVABILITÉ, pas le résultat. Un raffinement qui ne
s'annonce pas est un raffinement qu'on ne peut pas défendre.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

SOURCE = (_SERVICE_ROOT / "tools" / "placement.py").read_text(encoding="utf-8")


def _bloc_geometre() -> str:
    """Le corps de `auto_place` à partir de l'appel au Géomètre."""
    debut = SOURCE.index("refine = _refine_with_cmaes(")
    fin = SOURCE.index("_reserve_escape_halos(", debut)
    return SOURCE[debut:fin]


class TestObservabiliteDuGeometre:
    def test_le_succes_est_journalise(self):
        bloc = _bloc_geometre()
        assert "_LOG_GEOMETRE_OK" in bloc, (
            "le chemin de succès du Géomètre ne journalise rien : "
            "un succès silencieux ne se distingue pas d'une étape jamais exécutée"
        )

    def test_le_saut_est_journalise(self):
        # `refined: False` sans exception — CMA-ES indisponible ou sauté. Le
        # board reste valide, mais il faut le DIRE.
        bloc = _bloc_geometre()
        assert "_LOG_GEOMETRE_SAUTE" in bloc, (
            "un Géomètre sauté doit être annoncé, pas déduit d'une absence"
        )

    def test_le_journal_porte_une_mesure_et_pas_seulement_un_verdict(self):
        # « le Géomètre a tourné » sans chiffre ne permet pas de détecter une
        # dérive. Le déplacement max et la durée sont déjà calculés.
        # On regarde l'APPEL, dans le bloc du Géomètre — pas la définition de la
        # constante, dont le voisinage ne dit rien des arguments passés.
        bloc = _bloc_geometre()
        i = bloc.index("_LOG_GEOMETRE_OK")
        extrait = bloc[i: i + 300]
        assert "max_disp" in extrait, "le déplacement mesuré doit figurer au journal"
        assert re.search(r"elapsed_s|elapsed", extrait), "la durée doit figurer au journal"

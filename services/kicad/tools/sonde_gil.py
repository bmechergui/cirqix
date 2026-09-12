"""Sonde de famine du GIL — l instrument qui a trouve la vraie cause des
« Child process died » le 2026-09-10, installe A DEMEURE dans chaque worker.

Le superviseur d uvicorn 0.30 abat par SIGKILL un worker qui ne repond pas a
son ping en 5 s (`supervisors/multiprocess.py:170`). Un SIGKILL ne laisse
aucune trace : ni `faulthandler`, ni exception, ni journal. La seule facon de
savoir CE QUE FAISAIT le worker est de le lui demander AVANT la mort.

Principe : un thread Python re-arme chaque seconde
`faulthandler.dump_traceback_later(seuil)`. Ce minuteur vit dans un thread C
qui n a pas besoin du GIL. Tant que le thread Python tourne, il est re-arme et
ne tire jamais. S il est affame `seuil` secondes — c est-a-dire exactement la
condition dans laquelle le thread qui repond au ping l est aussi — le minuteur
tire et ecrit la pile de TOUS les threads sur stderr, donc dans `docker logs`,
juste avant que le superviseur ne frappe.

Le seuil est SOUS les 5 s du superviseur : on veut la pile, pas le cadavre.
Cout : un reveil par seconde, nul. Ne change rien au comportement du service.
"""
from __future__ import annotations

import faulthandler
import sys
import threading
import time

SEUIL_S = 4.5
_demarree = False


def _boucle(seuil_s: float) -> None:
    while True:
        faulthandler.dump_traceback_later(seuil_s, repeat=False, file=sys.stderr)
        time.sleep(1.0)


def armer_la_sonde_de_famine(seuil_s: float = SEUIL_S) -> bool:
    """Demarre la sonde une seule fois par processus. Rend True si demarree."""
    global _demarree
    if _demarree:
        return False
    t = threading.Thread(target=_boucle, args=(seuil_s,),
                         name="sonde-famine-gil", daemon=True)
    t.start()
    _demarree = True
    return True

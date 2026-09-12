"""Lance uvicorn avec un superviseur qui ne prend pas « occupe » pour « pendu ».

Mesure du 2026-09-10. Le superviseur d uvicorn 0.30 abat par SIGKILL tout
worker qui ne repond pas a son ping en 5 s (`supervisors/multiprocess.py:170`,
valeur codee en dur, pas d option). Deux causes reelles, prouvees par la sonde
de famine (`tools/sonde_gil.py`) :

  1. un appel C qui tient le GIL (le `read_text` de 564 Mo, corrige) ;
  2. la VM WSL qui PAGINE : 234 Mo en swap, 570 000 pages ecrites, et un
     compteur de pression memoire `full` a 5,8 heures cumulees. Le worker
     etait dans un parseur pur Python de 0,15 s quand il a ete tue — il ne
     tenait rien, il attendait ses pages.

Un worker qui met 30 s a repondre n est pas pendu : il route une carte. On
elargit la tolerance a `TOLERANCE_PING_S` par les valeurs par defaut des deux
methodes que le superviseur appelle sans argument. Rien d autre ne change ;
un worker reellement mort (`process.is_alive()` faux) est toujours relance.
"""
from __future__ import annotations

import sys

TOLERANCE_PING_S: float = 30.0


def elargir_la_tolerance(secondes: float = TOLERANCE_PING_S) -> float:
    """Pose la tolerance sur `Process.ping` et `Process.is_alive`. Rend la
    valeur effectivement posee, pour la garde."""
    import uvicorn.supervisors.multiprocess as m

    m.Process.ping.__defaults__ = (float(secondes),)
    m.Process.is_alive.__defaults__ = (float(secondes),)
    return m.Process.is_alive.__defaults__[0]


def main() -> None:
    elargir_la_tolerance()
    from uvicorn.main import main as uvicorn_main

    sys.argv[0] = "uvicorn"
    uvicorn_main()


if __name__ == "__main__":
    main()

"""Budget de recherche du routeur et garde-fou de processus sont deux choses.

Le même nombre servait aux deux :

    "--timeout", str(timeout_s)     -> budget de RECHERCHE donné à kct route
    timeout=timeout_s + 60          -> garde-fou anti-processus figé

Ce ne sont pas des limites de même nature :

* le budget de recherche est une RESSOURCE. `kct route` rend la main dès 100 %
  atteint, et conserve ce qu'il a trouvé quand l'échéance tombe. Mesuré sur
  STM32 LQFP-48 : 60 s -> 9 %, 300 s -> 36 %, 600 s -> 55 %. Lui donner plus de
  temps améliore le résultat sans rien coûter quand le routage finit tôt ;
* le garde-fou est un FILET. Il ne sert qu'au cas où le processus se fige.

Invariant central, et raison d'être de ce fichier : le garde-fou doit laisser
au routeur le temps d'atteindre sa PROPRE échéance ET d'écrire sa sortie. S'il
tirait le premier, `subprocess.run` tuerait un routeur qui s'apprêtait à rendre
un résultat partiel exploitable — on perdrait un routage réel pour une panne
imaginaire. La marge de 60 s ne le garantissait pas sur un board lourd.

Contexte produit : un routage complexe dure 15-20 min et davantage. Le plafond
n'est plus l'invocation web (le pipeline part dans un worker), donc rien ne
justifie plus de brider la recherche.
"""
from __future__ import annotations

import re
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "tools" / "kct_route.py").read_text(
    encoding="utf-8"
)


def _int_const(name: str) -> int:
    match = re.search(rf"^{name}:\s*int\s*=\s*(\d+)", SOURCE, re.M)
    assert match, f"constante {name} introuvable dans kct_route.py"
    return int(match.group(1))


def test_budget_de_recherche_couvre_un_routage_complexe() -> None:
    """20 min minimum : c'est l'ordre de grandeur mesuré d'un board complexe."""
    assert _int_const("_ROUTE_TIMEOUT_S") >= 1200


def test_garde_fou_laisse_le_routeur_atteindre_sa_propre_echeance() -> None:
    """Le filet ne doit jamais tirer avant le routeur.

    Sinon on tue un processus qui allait rendre un routage partiel valide.
    """
    marge = _int_const("_WATCHDOG_MARGIN_S")
    # Assez pour que kct route detecte son echeance, arrete sa recherche et
    # ecrive le .kicad_pcb resultant sur un board lourd.
    assert marge >= 300


def test_le_garde_fou_est_bien_derive_de_la_marge_dediee() -> None:
    """Garde de cablage : la marge doit etre CELLE-CI, pas un litteral reintroduit."""
    assert "timeout=timeout_s + _WATCHDOG_MARGIN_S" in SOURCE
    assert "timeout=timeout_s + 60" not in SOURCE

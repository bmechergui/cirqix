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


# --- La frontiere HTTP doit accepter ce que le client peut envoyer -----------
#
# Le budget vit a TROIS endroits : le client TypeScript le calcule
# (`routingSearchBudgetS`), la route FastAPI le valide, `kct route` le consomme.
# Relever les deux extremites en laissant la validation au milieu ne donne pas
# un routage plus long : il donne un 422.
#
# Mesure du 2026-08-20 : apres avoir porte le client a 1800 s sur 4 couches et
# `_ROUTE_TIMEOUT_S` a 3600 s, `POST /route/auto` a repondu **422 Unprocessable
# Entity** -- la borne `le=900` du modele n'avait pas suivi. Le routage n'a pas
# ete raccourci, il n'a PAS EU LIEU. Invisible en test : le client est mocke
# dans les tests TypeScript, et aucun test Python ne confrontait la borne du
# modele aux valeurs que le client produit.

ROUTER_SOURCE = (
    Path(__file__).resolve().parents[1] / "routers" / "routing.py"
).read_text(encoding="utf-8")


def _timeout_field_upper_bound() -> int:
    match = re.search(r"timeout_s:\s*int\s*=\s*Field\([^)]*?\ble=(\w+)", ROUTER_SOURCE)
    assert match, "borne superieure de timeout_s introuvable dans routers/routing.py"
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    const = re.search(rf"^{raw}:\s*int\s*=\s*(\d+)", ROUTER_SOURCE, re.M)
    assert const, f"constante {raw} introuvable dans routers/routing.py"
    return int(const.group(1))


def test_la_route_accepte_le_budget_maximal_du_routeur() -> None:
    """La borne HTTP ne doit pas etre plus serree que le budget du routeur."""
    assert _timeout_field_upper_bound() >= _int_const("_ROUTE_TIMEOUT_S")


def test_la_route_accepte_le_budget_calcule_par_le_client() -> None:
    """`routingSearchBudgetS(layers) = 600 + layers * 300`, plafonne a 3600.

    Le pire cas envoyable est donc 3600 s (8 couches). La route doit l'accepter.
    """
    worst_case_client_budget = min(600 + 8 * 300, 3600)
    assert _timeout_field_upper_bound() >= worst_case_client_budget


# --- Le budget doit ATTEINDRE le routeur ------------------------------------
#
# Relever la borne HTTP ne sert a rien si la route jette ensuite la valeur
# recue. `_route_with_kicad_tools` appelait `route_kct(..., timeout_s=
# _PYTHON_ROUTER_TIMEOUT_S)` -- une constante de 300 s -- en ignorant
# `req.timeout_s`. Le chemin PRINCIPAL de routage (kct route) etait donc plafonne
# a 300 s quoi que demande le client ; seul le repli Freerouting honorait la
# demande. C'etait le vrai plafond, celui qui rendait un routage de 15-20 min
# impossible a obtenir par l'API.


def test_le_budget_recu_est_transmis_au_routeur_principal() -> None:
    assert "def _route_with_kicad_tools(pcb_bytes: bytes, timeout_s: int)" in ROUTER_SOURCE
    assert "timeout_s=_PYTHON_ROUTER_TIMEOUT_S" not in ROUTER_SOURCE


def test_les_appelants_passent_le_budget_de_la_requete() -> None:
    calls = re.findall(r"(?<!def )_route_with_kicad_tools\((.*?)\)", ROUTER_SOURCE)
    invocations = [c for c in calls if "pcb_bytes" in c]
    assert invocations, "aucun appel a _route_with_kicad_tools trouve"
    for call in invocations:
        assert "req.timeout_s" in call, f"appel sans budget de requete : {call}"

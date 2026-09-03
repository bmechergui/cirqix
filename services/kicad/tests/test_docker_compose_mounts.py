"""Tout module importé par `main.py` doit être monté dans le conteneur.

Panne mesurée le 2026-08-19 : le commit Sentry a ajouté `observability.py` ET son
import dans `main.py` (ligne 102), mais PAS le montage correspondant dans
`docker-compose.yml`. Le compose monte `main.py` — donc la version NEUVE, celle
qui importe — au-dessus d'une image plus ancienne qui ne contient pas le module.

Résultat : `ModuleNotFoundError: No module named 'observability'`, les quatre
workers uvicorn meurent au démarrage, et le service ne sert AUCUNE route HTTP.
La panne est totale et silencieuse — `docker ps` affiche le conteneur « Up »,
seul `docker logs` révèle la cause.

Ce mode d'échec se reproduira à chaque nouveau module de premier niveau : monter
`main.py` sans monter ce qu'il importe est un piège structurel, pas un oubli
isolé. Cette garde le rend impossible à réintroduire en silence.
"""
from __future__ import annotations

import re

import pytest
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
MAIN_PY = SERVICE_ROOT / "main.py"
COMPOSE = SERVICE_ROOT / "docker-compose.yml"

# Modules de premier niveau vivant à côté de `main.py`. Les paquets (`routers/`,
# `tools/`) sont montés en tant que répertoires et traités plus bas.
_LOCAL_MODULES = {
    p.stem for p in SERVICE_ROOT.glob("*.py") if p.name not in {"main.py", "run_dev.py"}
}


def _imported_local_modules() -> set[str]:
    """Modules locaux réellement importés par `main.py`."""
    source = MAIN_PY.read_text(encoding="utf-8")
    found: set[str] = set()
    for line in source.splitlines():
        match = re.match(r"^\s*(?:from|import)\s+([a-zA-Z_][\w]*)", line)
        if match and match.group(1) in _LOCAL_MODULES:
            found.add(match.group(1))
    return found


def _mounted_paths() -> set[str]:
    """Chemins hôte montés par le service kicad, tels qu'écrits dans le compose."""
    compose = COMPOSE.read_text(encoding="utf-8")
    # Forme : `- ./chemin:/app/chemin:ro`
    return set(re.findall(r"-\s+\./([\w./-]+):/app/", compose))


def test_main_py_est_monte() -> None:
    """Prémisse de la panne : c'est parce que `main.py` est monté que l'image
    ancienne ne suffit plus — le fichier neuf importe ce qu'elle ne contient pas."""
    assert "main.py" in _mounted_paths()


def _compose_est_du_depot() -> bool:
    """Le compose lu est-il celui du depot, ou la copie figee de l image ?

    ⚠️ La suite tourne le plus souvent DANS le conteneur, ou `/app` melange
    des fichiers montes a chaud (`routers/`, `tools/`, `main.py`) et des
    fichiers cuits dans l image (`docker-compose.yml`, `tests/`). Le
    2026-08-23, le test ci-dessous a echoue toute une soiree en annoncant
    `observability` non monte — alors que le montage existait depuis
    longtemps sur l hote. Il lisait un compose anterieur a son ajout et
    rendait un verdict sur un etat disparu.

    Un test qui mesure un fichier perime est pire qu absent : il fabrique un
    defaut, et on finit par apprendre a ignorer son echec. On preferera
    donc SAUTER, en disant pourquoi.
    """
    # ⚠️ Le critere ne doit pas etre CIRCULAIRE : chercher dans le compose une
    # marque de fraicheur reviendrait a tester ce qu on veut mesurer. On
    # regarde donc si le fichier vit dans un arbre de travail Git — vrai sur
    # l hote, faux dans l image, ou seuls des fichiers copies subsistent.
    for parent in [COMPOSE.parent, *COMPOSE.parents]:
        if (parent / ".git").exists():
            return True
    return False


def test_tout_module_importe_par_main_est_monte() -> None:
    if not _compose_est_du_depot():
        pytest.skip(
            f"{COMPOSE} est la copie cuite dans l image, pas le fichier du "
            "depot : le verdict porterait sur un etat disparu. Relancer "
            "depuis l hote, ou reconstruire l image.")
    mounted = _mounted_paths()
    manquants = sorted(
        module for module in _imported_local_modules() if f"{module}.py" not in mounted
    )
    assert not manquants, (
        "modules importés par main.py mais NON montés dans docker-compose.yml : "
        f"{manquants}. Le conteneur mourra au démarrage avec ModuleNotFoundError, "
        "sans servir aucune route HTTP."
    )


def test_observability_est_bien_importe_par_main() -> None:
    """Ancre de la régression : si cet import disparaît, la garde ci-dessus
    deviendrait vraie pour une mauvaise raison (plus rien à monter)."""
    assert "observability" in _imported_local_modules()

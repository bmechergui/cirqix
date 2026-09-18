"""Un `docker restart` ne doit jamais laisser le service sans affichage.

⚠️ Mesure du 2026-09-19. `docker restart` CONSERVE `/tmp`. Le verrou
`/tmp/.X99-lock` de l execution precedente (15 septembre) etait toujours la ;
au redemarrage, l entrypoint relance `Xvfb :99`, qui s arrete aussitot :

    Fatal server error:
    (EE) Server is already active for display 99

Le service repond pourtant 200 sur /health, la JVM Freerouting revient, et rien
ne signale que `pcbnew` n a plus d affichage. CLAUDE.md disait ce defaut
« corrige » depuis le 2026-09-05 ; l entrypoint ne supprimait aucun verrou.

Un verrou laisse par un conteneur arrete ne designe aucun serveur vivant :
l entrypoint est le premier processus du conteneur, rien ne peut encore tenir
l affichage :99 quand il demarre. On le supprime AVANT de lancer Xvfb.
"""
from __future__ import annotations

import re
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
_TEXTE = (_SERVICE / "docker-entrypoint.sh").read_text(encoding="utf-8")
# Le CODE seul : une garde qui trouverait sa phrase dans un commentaire
# mesurerait la documentation, pas le comportement.
_CODE = "\n".join(l.split("#")[0] for l in _TEXTE.splitlines())


def _ligne(motif: str) -> int:
    for i, ligne in enumerate(_CODE.splitlines()):
        if re.search(motif, ligne):
            return i
    raise AssertionError(f"introuvable dans le code de l entrypoint : {motif}")


def test_le_verrou_orphelin_est_supprime_avant_xvfb():
    suppression = _ligne(r"rm\s+-f\b.*/tmp/\.X99-lock")
    lancement = _ligne(r"^\s*Xvfb\s+:99\b")
    assert suppression < lancement, "le verrou est supprime APRES le lancement de Xvfb"


def test_une_suppression_refusee_ne_tue_pas_l_entrypoint():
    """⚠️ Le script tourne sous `set -e`. `rm -f` avale « fichier absent »
    mais PAS « Operation not permitted » (sticky bit de /tmp, verrou d un autre
    utilisateur) : sans rattrapage, l entrypoint entier mourait — pire que le
    defaut corrige, qui ne privait que pcbnew d affichage. Releve en revue."""
    assert "set -e" in _CODE, "si le script quitte set -e, cette garde est a revoir"
    lignes = _CODE.splitlines()
    i = _ligne(r"rm\s+-f\b.*/tmp/\.X99-lock")
    # La commande peut continuer sur la ligne suivante (`\`).
    commande = lignes[i] + (lignes[i + 1] if lignes[i].rstrip().endswith("\\") else "")
    assert "||" in commande, "un rm refuse tuerait l entrypoint sous set -e"


def test_la_socket_x_orpheline_est_supprimee_aussi():
    # Le verrou seul ne suffit pas : une socket /tmp/.X11-unix/X99 restee
    # d avant fait echouer l ecoute du nouveau serveur de la meme facon.
    assert re.search(r"rm\s+-f\b.*/tmp/\.X11-unix/X99", _CODE)

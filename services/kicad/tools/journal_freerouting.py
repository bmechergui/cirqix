"""Lecture INCREMENTALE du journal Freerouting — jamais le fichier entier.

⚠️ MESURE DU 2026-09-10, la vraie cause des `RemoteDisconnected` (« Child
process died ») qui perdaient trois tirages sur quatre, cartes denses ou non.

Le superviseur d uvicorn 0.30 envoie un ping a chaque worker et le TUE
(`process.kill()`, SIGKILL — donc sans la moindre trace, `faulthandler`
compris) s il ne repond pas en CINQ secondes :

    uvicorn/supervisors/multiprocess.py:170   process.kill()  # process is hung

La boucle de sondage de `_route_with_freerouting_api` relisait le journal
ENTIER a chaque tour — deux fois — par `read_text()`. Ce journal grossit
pendant toute la vie de la JVM : **564 Mo** apres deux jours. Le decodage
UTF-8 d un tel fichier tient le GIL pendant 6 a 9 s ; le thread qui repond au
ping ne tourne pas ; le worker est abattu deux secondes apres la fin du
routage — precisement quand la sonde reprenait.

Sonde a l appui (`faulthandler.dump_traceback_later` depuis un thread C, qui
n a pas besoin du GIL) sur `carte-05`, 26 composants :

    famines du thread de ping : 9,1 s · 6,0 s · 3,0 s · 3,0 s
    pile a cet instant       : <frozen codecs> decode <- read_text <- routing.py:850

Pourquoi « seulement les cartes denses » : elles ecrivent plus de lignes, le
journal atteint plus vite la taille qui depasse 5 s. Ce n etait ni la memoire
(`oom_kill = 0`), ni pcbnew (les asserts `PROPERTY_ENUM` sont imprimes par le
worker SUIVANT qui demarre, 3 a 5 s APRES la mort).

La regle : on ne lit que ce qui a ete ecrit DEPUIS le depart du job, par
increments, et on garde en memoire les seules lignes de ce job.
"""
from __future__ import annotations

from pathlib import Path


class LecteurIncremental:
    """Rend, a chaque `lire()`, tout ce que le fichier a recu depuis la
    creation du lecteur — sans jamais relire ce qui a deja ete lu."""

    def __init__(self, chemin: Path) -> None:
        self.chemin = Path(chemin)
        self.texte = ""
        try:
            self.offset = self.chemin.stat().st_size
        except OSError:
            self.offset = 0

    def lire(self) -> str:
        try:
            taille = self.chemin.stat().st_size
            if taille < self.offset:
                # Journal tronque ou remplace : on repart du debut, sans
                # perdre ce qu on avait deja.
                self.offset = 0
            with open(self.chemin, "rb") as f:
                f.seek(self.offset)
                nouveau = f.read()
        except OSError:
            return self.texte
        if nouveau:
            self.offset += len(nouveau)
            self.texte += nouveau.decode("utf-8", errors="replace")
        return self.texte

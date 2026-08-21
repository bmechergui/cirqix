"""`ZONE.SetFilled` n'existe plus sous KiCad 10 — il s'appelle `SetIsFilled`.

Le defaut etait DEJA CONNU et deja corrige... a un seul endroit :

    drc_pcbnew_runner.py:30   « KiCad 10: ZONE.SetFilled is gone (renamed
                                SetIsFilled); under KiCad 9 both exist. »
    drc_pcbnew_runner.py:33   zone.SetIsFilled(True)      <- corrige
    tools/routing.py:39       zone.SetFilled(True)        <- oublie
    routing_pcbnew_runner.py  zone.SetFilled(True)        <- oublie

Personne ne l'a vu parce que la boucle `for zone in board.Zones()` ne s'executait
JAMAIS : aucun board de la chaine ne portait de zone. En coulant les plans de
masse avant le routage (2026-08-21), la boucle s'est executee pour la premiere
fois et le processus enfant est sorti en erreur :

    pcbnew child exit 1
    AttributeError: 'ZONE' object has no attribute 'SetFilled'.
                    Did you mean: 'SetIsFilled'?

Freerouting echouait alors aux deux niveaux et la cascade retombait sur
kicad-tools — 570 s au lieu de 4, et une carte a 58 erreurs de fabricabilite au
lieu d'une carte propre.

⚠️ Meme motif que l'ERC et l'API Freerouting le meme jour : reparer un chemin
mort en revele les usagers. Un correctif applique a un seul appelant n'est pas
un correctif.
"""
from __future__ import annotations

from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _fichiers_python() -> list[Path]:
    return sorted(p for p in _TOOLS.glob("*.py"))


class TestApiDeZone:
    def test_aucun_fichier_n_appelle_l_api_supprimee(self):
        fautifs = []
        for chemin in _fichiers_python():
            texte = chemin.read_text(encoding="utf-8")
            for numero, ligne in enumerate(texte.splitlines(), start=1):
                if ligne.lstrip().startswith("#"):
                    continue  # les commentaires CITENT l'ancien nom exprès
                if ".SetFilled(" in ligne:
                    fautifs.append(f"{chemin.name}:{numero}")
        assert fautifs == [], (
            "`ZONE.SetFilled` n'existe plus sous KiCad 10 — utiliser "
            f"`SetIsFilled` : {fautifs}"
        )

    def test_les_preparateurs_de_zone_utilisent_le_bon_nom(self):
        """Seuls les fichiers qui PREPARENT les zones sont concernes.

        `ZONE_FILLER.Fill()` marque lui-meme les zones remplies : appeler
        `Fill()` seul est parfaitement valide (c est ce que fait
        `drc.py::refill_zones`). Exiger `SetIsFilled` partout ou un
        ZONE_FILLER apparait serait une regle inventee, pas un invariant.

        Ce test ne vise donc que les fichiers qui forcent explicitement le
        drapeau avant de remplir.
        """
        for nom in ("drc_pcbnew_runner.py", "routing_pcbnew_runner.py", "routing.py"):
            texte = (_TOOLS / nom).read_text(encoding="utf-8")
            if "for zone in board.Zones():" not in texte:
                continue
            assert "SetIsFilled(" in texte, (
                f"{nom} prepare ses zones avec une methode qui n existe plus"
            )
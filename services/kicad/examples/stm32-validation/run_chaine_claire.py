"""Chaîne complète, trois sorties nommées : génération → placement → routage.

Rejoue la chaîne de production avec les fonctions réelles (pas de mock) et
écrit un fichier par étape, plus un rapport de qualité pour chacun :

    output/1_generation.kicad_pcb   composants posés par le générateur
    output/2_placement.kicad_pcb    placement validé (Architecte + Inspecteur
                                    + Géomètre CMA-ES + filets de sécurité)
    output/3_routage.kicad_pcb      routage kct + réparations Cirqix

Usage (dans le conteneur, depuis services/kicad) :

    python -u examples/stm32-validation/run_chaine_claire.py

Le DRC exige le profil fabricant : sans lui, le juge applique des règles par
défaut qui n'ont rien à voir avec la carte livrée.
"""
from __future__ import annotations

import base64
import collections
import json
import re
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]          # services/kicad
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "kicad-tools" / "src"))

from tools import drc as drc_tools                     # noqa: E402
from tools import kct_route                            # noqa: E402
from tools.placement import auto_place                 # noqa: E402

EXEMPLE = Path(__file__).resolve().parent
SORTIE = EXEMPLE / "output"
LARGEUR_MM, HAUTEUR_MM = 60.0, 40.0

# kicad-cli d'une version au moins egale a celle qui a ecrit le board.
_CLI_CANDIDATS = ("/usr/lib/kicad-nightly/bin/kicad-cli", "kicad-cli")
_CLI_ENV = {"LD_LIBRARY_PATH": "/usr/lib/kicad-nightly/lib/x86_64-linux-gnu",
            "PATH": "/usr/bin:/bin", "HOME": "/tmp"}


def _cli() -> tuple[str, dict | None]:
    for chemin in _CLI_CANDIDATS:
        if chemin == "kicad-cli" or Path(chemin).exists():
            return chemin, (_CLI_ENV if "nightly" in chemin else None)
    return "kicad-cli", None


def qualite(board: Path) -> str:
    """Erreurs DRC + connexions manquantes, sous le profil fabricant du board."""
    texte = board.read_text(errors="replace")
    tier = re.search(r'"cirqix_mfr_tier"\s+"([^"]+)"', texte)
    try:
        drc_tools.write_mfr_project_sidecar(
            board, tier.group(1) if tier else "jlcpcb",
            drc_tools.copper_layer_count(texte), pcb_text=texte)
    except Exception as exc:                            # noqa: BLE001
        return "profil fabricant indisponible (%s)" % exc

    binaire, env = _cli()
    rapport = board.with_suffix(".drc.json")
    subprocess.run([binaire, "pcb", "drc", "--severity-all", "--refill-zones",
                    "--format", "json", "-o", str(rapport), str(board)],
                   capture_output=True, text=True, timeout=900, check=False, env=env)
    if not rapport.exists():
        return "DRC indisponible"

    donnees = json.loads(rapport.read_text(encoding="utf-8"))
    erreurs = [v for v in donnees.get("violations", []) if v.get("severity") == "error"]
    par_net: collections.Counter = collections.Counter()
    for item in donnees.get("unconnected_items", []):
        for detail in item.get("items", []):
            nom = re.search(r"\[([^\]]+)\]", detail.get("description", ""))
            if nom:
                par_net[nom.group(1)] += 1
    manquantes = len(donnees.get("unconnected_items", []))
    return "%d erreur(s) %s · %d connexion(s) manquante(s) %s" % (
        len(erreurs), dict(collections.Counter(v["type"] for v in erreurs)) or "",
        manquantes, dict(par_net) or "")


def resume(board: Path) -> str:
    texte = board.read_text(errors="replace")
    return "%d segments · %d vias · %d empreintes" % (
        len(re.findall(r"\(segment[\s\n]", texte)),
        len(re.findall(r"\(via[\s\n]", texte)),
        len(re.findall(r"\(footprint[\s\n]", texte)))


def etape(numero: int, titre: str) -> None:
    print("\n" + "=" * 64, flush=True)
    print("[%d/3] %s" % (numero, titre), flush=True)


SORTIE.mkdir(parents=True, exist_ok=True)

# ─── 1. Génération ────────────────────────────────────────────────────────────
etape(1, "GÉNÉRATION — composants et nets depuis le schéma")
t0 = time.time()
brut = SORTIE / "_gen"
subprocess.run([sys.executable, str(EXEMPLE / "input" / "generate_design.py"), str(brut)],
               capture_output=True, text=True, timeout=900, check=False)
produit = next(brut.glob("*.kicad_pcb"), None)
if produit is None:
    raise SystemExit("échec de la génération — aucun .kicad_pcb produit")

generation = SORTIE / "1_generation.kicad_pcb"
generation.write_bytes(produit.read_bytes())
print("   %s" % generation.name, flush=True)
print("   %s  en %.0f s" % (resume(generation), time.time() - t0), flush=True)
print("   %s" % qualite(generation), flush=True)

# ─── 2. Placement ─────────────────────────────────────────────────────────────
etape(2, "PLACEMENT — Architecte, Inspecteur, Géomètre CMA-ES, filets")
t0 = time.time()
resultat = auto_place(base64.b64encode(generation.read_bytes()).decode(),
                      LARGEUR_MM, HAUTEUR_MM)
placement = SORTIE / "2_placement.kicad_pcb"
placement.write_bytes(base64.b64decode(resultat["kicad_pcb_b64"]))
print("   %s" % placement.name, flush=True)
print("   %d composants placés en %.0f s"
      % (resultat.get("placed_count", 0), time.time() - t0), flush=True)
print("   %s" % resume(placement), flush=True)
print("   %s" % qualite(placement), flush=True)

# ─── 3. Routage ───────────────────────────────────────────────────────────────
etape(3, "ROUTAGE — kct route + réparations Cirqix (vias, fragments)")
t0 = time.time()
board, pourcentage, analyse = kct_route.route_kct(placement.read_bytes(), timeout_s=900)
routage = SORTIE / "3_routage.kicad_pcb"
routage.write_bytes(board)
print("   %s" % routage.name, flush=True)
print("   routé à %s %% en %.0f s" % (pourcentage, time.time() - t0), flush=True)
print("   %s" % resume(routage), flush=True)
print("   %s" % qualite(routage), flush=True)
if analyse:
    print("   — nets non terminés —", flush=True)
    for ligne in analyse.splitlines()[:8]:
        if ligne.strip():
            print("     %s" % ligne.strip()[:120], flush=True)

print("\n" + "=" * 64, flush=True)
print("Sorties dans %s" % SORTIE, flush=True)
for nom in ("1_generation", "2_placement", "3_routage"):
    fichier = SORTIE / (nom + ".kicad_pcb")
    if fichier.exists():
        print("   %-24s %7d octets" % (fichier.name, fichier.stat().st_size), flush=True)

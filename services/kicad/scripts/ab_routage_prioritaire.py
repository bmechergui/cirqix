#!/usr/bin/env python3
"""A/B : le routage PRIORITAIRE des liaisons critiques (D-2026-09-25-a).

Question : faut-il activer `routage_prioritaire` par défaut ? La passe pose les
découplages par des pistes courtes AVANT Freerouting, puis les protège. Elle ne
se juge ni au seul pourcentage routé, ni au seul DRC : son objet est la
QUALITÉ des liaisons critiques. On mesure donc les deux. Le critère de décision
est fixé AVANT la mesure (D-2026-09-25-c).

## Protocole

- Placement GELÉ (`expected/placement.kicad_pcb`), le même pour les deux bras :
  re-placer ferait mesurer le placement au lieu de la passe.
- Bras A : aucun fichier de réglages. Bras B : `{"routage_prioritaire": true}`.
  Le service relit le fichier à CHAQUE appel (`tools/reglages_banc.py`) ; une
  variable d'environnement du client ne l'atteindrait jamais (A/B du 2026-09-09
  qui comparait deux bras identiques).
- Voie HTTP réelle (`POST /route/auto`), comme le worker : `banc_exemples.py`
  importe `route_auto` et n'exerce jamais cette voie.
- Ordre ABBA (A B, puis B A, puis A B…) : une dérive de la machine ou de la JVM
  pèse sur les deux bras, pas sur un seul.
- Plafond 8 couches et budget du client du banc (`run_pipeline.py`).

## Mesures, et ce qui les rend fiables

- Précondition : le service a démarré APRÈS la dernière modification du code
  de la passe, et aucun réglage ne vient de son environnement. Sinon le bras B
  exécuterait l'ancien code, identique à A, sans la moindre erreur.
- Verdict de fabrication : `kicad-cli pcb drc` sur le board RENDU, erreurs
  bloquantes lues par `tools.drc.est_bloquante`. Un DRC qui n'a pas pu juger, ou
  un rapport sans ses sections, est écrit `sans_verdict`, jamais « 0 erreur ».
- Qualité : pour chaque liaison critique détectée sur le placement, le chemin
  de CUIVRE (pistes et vias du net) entre ses deux pastilles, avec un STATUT :
  `mesuree`, `aucun_chemin`, `pastille_absente` ou `net_incoherent`. Seul
  `aucun_chemin` est un résultat de routage ; les deux derniers sont des défauts
  de la sonde, qui invalident la ligne.
- Preuve que la passe est DANS le board rendu : ses pistes ont la largeur de la
  liaison (0,4 mm pour un découplage), qu'aucun board livré sans passe ne porte
  (compté le 2026-09-25 sur carte-03, 05, 08 et 10 : 0,2 et 0,25 mm seulement).
  Une liaison dont tout le chemin a cette largeur, et tient sous
  `LONGUEUR_MAX_MM`, porte la signature. Le bras B ne tourne la passe qu'un
  tirage sur deux et `route_auto` garde le meilleur : sans cette preuve, un B
  identique à A ne départagerait rien.
- Le journal du service porte « routage prioritaire : RETENUE » quand la passe
  franchit ses gardes ; chaque ligne garde `debut` et `fin` pour le retrouver.

S'exécute DANS le conteneur, où vit `KICAD_SERVICE_TOKEN`. Arrêter par
`kill -INT` ou `-TERM` (jamais `-9`) : le réglage est alors retiré.

Usage :
    python3 scripts/ab_routage_prioritaire.py <sortie.jsonl> <dossier_boards> \\
        [--tirages=3] [--budget=3000] carte-05-capteur-i2c carte-10-maximale …
"""
from __future__ import annotations

import argparse
import base64
import heapq
import http.client
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import nets_critiques as N  # noqa: E402

_URL = "http://127.0.0.1:8766/route/auto"
_REGLAGES = Path(os.environ.get("CIRQIX_REGLAGES", "/tmp/cirqix-reglages.json"))
_BRAS = {"A": None, "B": {"routage_prioritaire": True}}
# Le code dont dépend la passe : s'il est plus récent que le service, le
# service exécute l'ancien.
_CODE_DE_LA_PASSE = ("routers/routing.py", "tools/nets_critiques.py",
                     "tools/routing_pcbnew_runner.py", "tools/reglages_banc.py")

_XY_RE = re.compile(r"\((start|end|at)\s+(-?[\d.]+)\s+(-?[\d.]+)")
_LAYER_RE = re.compile(r'\(layer\s+"([^"]+)"\)')
_LAYERS_RE = re.compile(r"\(layers\s+([^)]*)\)")
_WIDTH_RE = re.compile(r"\(width\s+([\d.]+)\)")
_NET_NUM_SEUL_RE = re.compile(r"\(net\s+(\d+)\s*\)")
_DECL_RE = re.compile(r'\(net\s+(\d+)\s+"([^"]*)"\)')

# Deux extrémités à moins de 5 µm sont le même nœud : Freerouting et pcbnew
# écrivent au micromètre près, un écart plus grand est un autre point.
_MEME_POINT_MM = 0.005
_TOLERANCE_LARGEUR_MM = 0.001
# Les pistes de la passe partent de points calés sur la grille, pas du centre
# exact des pastilles : on tolère ce décalage dans la longueur de la signature.
_MARGE_SIGNATURE_MM = 0.5


# ---------------------------------------------------------------------------
# La sonde : chemin de cuivre entre deux pastilles d'un net
# ---------------------------------------------------------------------------

def _net_du_bloc(bloc: str, noms: dict) -> str:
    """Les deux écritures : `(net "GND")` (KiCad 10) et `(net 3)` (≤ 9)."""
    nom = N._net_de(bloc)
    if nom:
        return nom
    m = _NET_NUM_SEUL_RE.search(bloc)
    return noms.get(m.group(1), "") if m else ""


def cuivre_du_net(texte: str, net: str) -> tuple:
    """(segments, vias) du net : segments = [(couche, (x1, y1), (x2, y2), largeur)],
    vias = [(x, y, couches)] — `couches` vaut None pour un via traversant."""
    noms = {num: nom for num, nom in _DECL_RE.findall(texte)}
    segments, vias = [], []
    for tete in ("(segment", "(arc"):
        for bloc in N._blocs(texte, tete):
            if _net_du_bloc(bloc, noms) != net:
                continue
            pts = {k: (float(x), float(y)) for k, x, y in _XY_RE.findall(bloc)}
            couche = _LAYER_RE.search(bloc)
            largeur = _WIDTH_RE.search(bloc)
            if "start" in pts and "end" in pts and couche:
                # Un arc est compté par sa corde : Freerouting n'en écrit pas.
                segments.append((couche.group(1), pts["start"], pts["end"],
                                 float(largeur.group(1)) if largeur else None))
    for bloc in N._blocs(texte, "(via"):
        if _net_du_bloc(bloc, noms) != net:
            continue
        at = _XY_RE.search(bloc)
        couches = _LAYERS_RE.search(bloc)
        if at:
            liste = re.findall(r'"([^"]+)"', couches.group(1)) if couches else []
            # Un via borgne ou enterré ne relie que ses couches.
            traversant = not liste or ("F.Cu" in liste and "B.Cu" in liste)
            vias.append((float(at.group(2)), float(at.group(3)),
                         None if traversant else tuple(liste)))
    return segments, vias


def _sur_la_couche(pastille, couche: str) -> bool:
    return pastille.couche == "*" or pastille.couche == couche


def chemin_de_liaison(texte: str, a, b) -> tuple | None:
    """Plus court chemin de PISTES entre les pastilles `a` et `b` d'un même net :
    `(longueur_mm, largeurs)` où `largeurs` liste la largeur de chaque piste du
    chemin, ou None s'il n'en existe aucun.

    Nœuds : les extrémités de pistes (par couche) et les pastilles du net. Une
    extrémité touche une pastille si elle tombe dans sa demi-diagonale, sur une
    couche qu'elle occupe ; un via relie ses couches en son centre. Un plan
    coulé n'est PAS un chemin : on mesure une piste, pas une zone.

    Deux pastilles du même boîtier au même numéro sont UNE broche (la languette
    d'un SOT-223 porte le numéro de la broche 2) : elles forment un seul nœud.
    """
    if a.net != b.net or not a.net:
        return None
    segments, vias = cuivre_du_net(texte, a.net)
    pastilles = [p for p in N.pastilles_du_board(texte) if p.net == a.net]

    noeuds: list = []  # (couche, x, y)

    def noeud(couche: str, x: float, y: float) -> int:
        for i, (c, nx, ny) in enumerate(noeuds):
            if c == couche and math.hypot(nx - x, ny - y) <= _MEME_POINT_MM:
                return i
        noeuds.append((couche, x, y))
        return len(noeuds) - 1

    aretes: dict = {}

    def relier(i, j, poids: float, largeur) -> None:
        aretes.setdefault(i, []).append((j, poids, largeur))
        aretes.setdefault(j, []).append((i, poids, largeur))

    for couche, p1, p2, largeur in segments:
        relier(noeud(couche, *p1), noeud(couche, *p2), math.dist(p1, p2), largeur)
    for x, y, couches in vias:
        presentes = sorted({c for c, nx, ny in noeuds
                            if math.hypot(nx - x, ny - y) <= _MEME_POINT_MM})
        if couches is not None:
            presentes = [c for c in presentes if c in couches]
        for c1, c2 in zip(presentes, presentes[1:]):
            relier(noeud(c1, x, y), noeud(c2, x, y), 0.0, None)

    for p in pastilles:
        cle = ("pad", p.ref, p.nom)
        for i, (c, nx, ny) in enumerate(list(noeuds)):
            d = math.hypot(nx - p.x, ny - p.y)
            if _sur_la_couche(p, c) and d <= max(p.demi_taille, 0.05):
                relier(cle, i, d, None)

    depart, arrivee = ("pad", a.ref, a.nom), ("pad", b.ref, b.nom)
    distances = {depart: 0.0}
    precedent: dict = {}
    tas = [(0.0, 0, depart)]
    compteur = 1
    while tas:
        d, _, n = heapq.heappop(tas)
        if n == arrivee:
            largeurs = []
            while n in precedent:
                n, largeur = precedent[n]
                if largeur is not None:
                    largeurs.append(largeur)
            return d, largeurs
        if d > distances.get(n, math.inf):
            continue
        for voisin, poids, largeur in aretes.get(n, []):
            nd = d + poids
            if nd < distances.get(voisin, math.inf):
                distances[voisin] = nd
                precedent[voisin] = (n, largeur)
                heapq.heappush(tas, (nd, compteur, voisin))
                compteur += 1
    return None


def longueur_de_liaison(texte: str, a, b) -> float | None:
    """Longueur (mm) du plus court chemin de pistes, ou None sans chemin."""
    chemin = chemin_de_liaison(texte, a, b)
    return None if chemin is None else chemin[0]


def mesurer_liaisons(place: str, route: str) -> list:
    """Pour chaque liaison critique du PLACEMENT, son chemin sur le board ROUTÉ,
    avec un statut qui distingue un échec de routage d'un défaut de la sonde."""
    pads = {}
    for p in N.pastilles_du_board(route):
        pads.setdefault((p.ref, p.nom), p)
    sortie = []
    for l in N.liaisons_critiques(place):
        ligne = {**l.en_dict(), "cuivre_mm": None, "signature_passe": False}
        a, b = pads.get(tuple(l.a)), pads.get(tuple(l.b))
        if a is None or b is None:
            sortie.append({**ligne, "statut": "pastille_absente"})
            continue
        if not a.net or a.net != b.net or a.net != l.net:
            sortie.append({**ligne, "statut": "net_incoherent",
                           "nets_lus": [a.net, b.net]})
            continue
        chemin = chemin_de_liaison(route, a, b)
        if chemin is None:
            sortie.append({**ligne, "statut": "aucun_chemin"})
            continue
        longueur, largeurs = chemin
        signature = (bool(largeurs)
                     and all(abs(w - l.largeur_mm) <= _TOLERANCE_LARGEUR_MM for w in largeurs)
                     and longueur <= N.LONGUEUR_MAX_MM + _MARGE_SIGNATURE_MM)
        sortie.append({**ligne, "statut": "mesuree", "cuivre_mm": round(longueur, 3),
                       "largeurs": sorted(set(largeurs)), "signature_passe": signature})
    return sortie


# ---------------------------------------------------------------------------
# Préconditions : le service exécute le bon code, sans réglage caché
# ---------------------------------------------------------------------------

def _demarrage_du_pid(pid: int) -> float:
    """Heure de démarrage (epoch) d'un processus, depuis /proc."""
    ticks = os.sysconf("SC_CLK_TCK")
    champs = Path("/proc/%d/stat" % pid).read_text().rsplit(")", 1)[1].split()
    depuis_boot = int(champs[19]) / ticks
    boot = next(int(l.split()[1]) for l in Path("/proc/stat").read_text().splitlines()
                if l.startswith("btime"))
    return boot + depuis_boot


def verifier_le_service() -> dict:
    """Refuse de mesurer un service qui exécute un code plus ancien que le dépôt
    monté, ou qui porte le réglage dans son environnement."""
    demarre = _demarrage_du_pid(1)
    for relatif in _CODE_DE_LA_PASSE:
        mtime = (_SERVICE_ROOT / relatif).stat().st_mtime
        if mtime > demarre:
            raise RuntimeError("%s modifié après le démarrage du service : recréer le conteneur"
                               % relatif)
    environ = Path("/proc/1/environ").read_bytes().split(b"\0")
    if any(v.startswith(b"CIRQIX_ROUTAGE_PRIORITAIRE=") for v in environ):
        raise RuntimeError("CIRQIX_ROUTAGE_PRIORITAIRE dans l'environnement du service : bras A faussé")
    if _REGLAGES.exists():
        raise RuntimeError("%s existe déjà : un réglage oublié fausserait la mesure" % _REGLAGES)
    return {"service_demarre": demarre}


# ---------------------------------------------------------------------------
# Le banc
# ---------------------------------------------------------------------------

def _lire_reglage() -> bool:
    from tools import reglages_banc
    return bool(reglages_banc.reglage("routage_prioritaire", False))


def _poser_reglages(bras: str) -> None:
    contenu = _BRAS[bras]
    if contenu is None:
        _REGLAGES.unlink(missing_ok=True)
    else:
        provisoire = _REGLAGES.with_suffix(".tmp")
        provisoire.write_text(json.dumps(contenu), encoding="utf-8")
        os.replace(provisoire, _REGLAGES)
    # Relu comme le SERVICE le relit : un bras mal posé fausserait tout.
    if _lire_reglage() != (bras == "B"):
        raise RuntimeError("reglage mal pose pour le bras %s" % bras)


def _router(board: bytes, budget: int) -> dict:
    jeton = os.environ.get("KICAD_SERVICE_TOKEN", "")
    if not jeton:
        raise RuntimeError("KICAD_SERVICE_TOKEN absent du conteneur")
    corps = json.dumps({"kicad_pcb_b64": base64.b64encode(board).decode("ascii"),
                        "layers": 8, "timeout_s": budget}).encode("utf-8")
    requete = urllib.request.Request(_URL, data=corps, method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + jeton})
    with urllib.request.urlopen(requete, timeout=budget * 4 + 900) as r:
        return json.loads(r.read().decode("utf-8"))


def _juger(board: bytes) -> dict:
    from routers import routing as R
    from tools.drc import est_bloquante
    rapport = R._rapport_drc(board)
    if R._sans_verdict(rapport):
        return {"sans_verdict": True, "raison": "drc_indisponible"}
    violations = rapport.get("violations")
    manquantes = rapport.get("unconnected_items")
    # Un rapport sans ses sections n'est pas « 0 erreur, 0 manquante ».
    if not isinstance(violations, list) or not isinstance(manquantes, list):
        return {"sans_verdict": True, "raison": "structure"}
    return {
        "sans_verdict": False,
        "manquantes": len(manquantes),
        "bloquantes": sum(1 for v in violations if est_bloquante(v)),
        "violations": len(violations),
    }


def _charge() -> list:
    return [round(x, 2) for x in os.getloadavg()]


def _un_essai(carte: str, bras: str, rang: int, place: bytes, budget: int,
              boards: Path, campagne: str) -> dict:
    _poser_reglages(bras)
    debut = time.time()
    ligne = {"campagne": campagne, "carte": carte, "bras": bras, "rang": rang,
             "debut": debut, "charge_avant": _charge()}
    try:
        rep = _router(place, budget)
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        return {**ligne, "fin": time.time(), "erreur": "%s: %s" % (type(exc).__name__, exc)}
    ligne.update(fin=time.time(), duree_s=round(time.time() - debut, 1),
                 charge_apres=_charge(), reglage_apres=_lire_reglage(),
                 pct=rep.get("routed_percent"), couches=rep.get("layers"),
                 skipped=rep.get("skipped"), moteur=rep.get("engine"),
                 verdict=rep.get("verdict"), vias=rep.get("via_count"),
                 longueur_pistes_mm=rep.get("track_length_mm"),
                 avertissement=(rep.get("warning") or "")[:300])
    if ligne["reglage_apres"] != (bras == "B"):
        ligne["invalide"] = "reglage modifie pendant l'essai"
    if not rep.get("kicad_pcb_b64"):
        return {**ligne, "erreur": "aucun board rendu"}
    try:
        route = base64.b64decode(rep["kicad_pcb_b64"])
        (boards / ("%s-%s-%d.kicad_pcb" % (carte, bras, rang))).write_bytes(route)
        ligne["drc"] = _juger(route)
        liaisons = mesurer_liaisons(place.decode("utf-8"), route.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — la ligne dit l'échec, le banc continue
        return {**ligne, "erreur_mesure": "%s: %s" % (type(exc).__name__, exc)}
    ligne["liaisons"] = liaisons
    ligne["passe_dans_le_board"] = sum(1 for l in liaisons if l["signature_passe"])
    if any(l["statut"] in ("pastille_absente", "net_incoherent") for l in liaisons):
        ligne["invalide"] = "sonde : pastille absente ou net incohérent"
    return ligne


def _arreter_proprement(signum, _frame) -> None:
    # Lève SystemExit : le `finally` de main retire le réglage.
    raise SystemExit(128 + signum)


def _commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(_SERVICE_ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sortie")
    ap.add_argument("boards")
    ap.add_argument("cartes", nargs="+")
    ap.add_argument("--tirages", type=int, default=3)
    ap.add_argument("--budget", type=int, default=3000)
    args = ap.parse_args(argv[1:])

    sortie_chemin = Path(args.sortie)
    if sortie_chemin.exists():
        raise SystemExit("%s existe déjà : une campagne par fichier" % sortie_chemin)
    signal.signal(signal.SIGTERM, _arreter_proprement)
    signal.signal(signal.SIGINT, _arreter_proprement)
    etat = verifier_le_service()
    campagne = "%d-%d" % (int(time.time()), os.getpid())

    racine = _SERVICE_ROOT / "examples"
    boards = Path(args.boards)
    boards.mkdir(parents=True, exist_ok=True)
    try:
        with open(sortie_chemin, "w", encoding="utf-8") as sortie:
            sortie.write(json.dumps({"campagne": campagne, "commit": _commit(),
                                     "cartes": args.cartes, "tirages": args.tirages,
                                     "budget": args.budget, **etat}) + "\n")
            for carte in args.cartes:
                place = (racine / carte / "expected" / "placement.kicad_pcb").read_bytes()
                for rang in range(1, args.tirages + 1):
                    # ABBA : l'ordre alterne d'un rang à l'autre.
                    for bras in (("A", "B") if rang % 2 else ("B", "A")):
                        ligne = _un_essai(carte, bras, rang, place, args.budget,
                                          boards, campagne)
                        sortie.write(json.dumps(ligne, ensure_ascii=False) + "\n")
                        sortie.flush()
                        print(json.dumps({k: ligne.get(k) for k in (
                            "carte", "bras", "rang", "pct", "couches", "duree_s", "drc",
                            "passe_dans_le_board", "invalide", "erreur", "erreur_mesure")},
                            ensure_ascii=False), flush=True)
    finally:
        # Un réglage oublié fausserait la mesure SUIVANTE, quelle qu'elle soit.
        _REGLAGES.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

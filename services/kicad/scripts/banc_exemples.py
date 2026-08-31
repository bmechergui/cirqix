"""Passe chaque exemple dans la chaine complete et resume les resultats.

    python3 scripts/banc_exemples.py

⚠️ Le nombre de COUCHES n est jamais impose : `route_auto` escalade seul
(2 -> 4 -> 6 ...) tant que le routage n aboutit pas. Le banc verifie donc aussi
que l escalade se declenche quand la densite l exige, et pas avant.

Le verdict qui compte est celui du DRC, pas le pourcentage : une carte peut etre
annoncee routee et porter des connexions manquantes. On imprime les deux.
"""
from __future__ import annotations

import base64
import getpass
import logging
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

_RACINE = next(
    (p for p in [Path(__file__).resolve().parents[1], Path("/app"), Path.cwd()]
     if (p / "routers").is_dir()),
    Path(__file__).resolve().parents[1],
)
sys.path.insert(0, str(_RACINE))

_EXEMPLES = _RACINE / "examples"

# ⚠️ La JVM peut mettre quelques secondes a rendre la main apres un SIGKILL
# (2,4 Go a liberer). En dessous on declarerait vivante une JVM qui meurt ;
# au-dela on ferait attendre le banc pour rien.
_ATTENTE_MORT_JVM_S: float = 15.0


# ⚠️ Sans cette configuration, les `logger.info` du service ne s ecrivent
# NULLE PART. Le banc devenait alors aveugle a ses propres decisions, et j en
# ai tire DEUX conclusions fausses le 2026-08-27 : « la detection de boitier
# dominant ne se declenche jamais » (elle tournait) et « le placement
# deterministe n a pas ete essaye » (impossible a dire). On ne corrige pas ce
# qu on ne voit pas.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _passer(circuit: dict, sortie: Path, tirages: int = 1) -> dict:
    """Enchaine la chaine `tirages` fois et garde le MEILLEUR board.

    ⚠️ Le placement est STOCHASTIQUE — `OptimizationWorkflow` n a pas de seed
    fixe. Mesure du 2026-08-27 : l ESP32 rend 3 erreurs a un tirage et 10 au
    suivant, sans qu une ligne de code ait change.

    Un banc a tirage unique mesure donc le HASARD, pas la chaine. Et il la
    sous-represente : la production re-tire quand le DRC echoue et garde le
    meilleur (`shouldRetryForDrc` / `keepBestDrc` dans l orchestrateur).

    On classe par (erreurs, connexions manquantes) : une erreur de
    fabricabilite fait refuser la carte, une connexion manquante se voit au
    DRC. La premiere prime.
    """
    meilleur = None
    premier_echec = None
    rates = 0
    for n in range(max(1, tirages)):
        r = _un_tirage(circuit, sortie)
        # ⚠️ UN TIRAGE RATE NE JETTE PAS LES REUSSIS. On sortait ici en rendant
        # l erreur, ce qui abandonnait tout ce qui precedait. Mesure du
        # 2026-08-31 sur `stm32-100` :
        #
        #     tirage 1  ->  99 %, 1 manquante, 0 erreur DRC
        #     tirage 2  ->  99 %, 1 manquante, 0 erreur DRC
        #     tirage 3  ->  ECHEC (tirages de routage tous stagnes)
        #     rendu     ->  ECHEC
        #
        # Deux boards livrables mesures, et le banc concluait a l echec de la
        # chaine. Le board etait sur le disque, intact : 2 couches, 0 erreur,
        # 647 segments, 141 vias. Le defaut etait dans l INSTRUMENT, ce qui le
        # rend pire — il fait conclure a l echec d une chaine qui a reussi.
        #
        # On retient le PREMIER echec : il porte la cause d origine, les
        # suivants en decoulent souvent (JVM degradee, budget entame).
        if "erreur" in r:
            rates += 1
            if premier_echec is None:
                premier_echec = r
            continue
        cle = (r["erreurs"], r["manquantes"])
        if meilleur is None or cle < (meilleur["erreurs"], meilleur["manquantes"]):
            meilleur = r
            meilleur["tirage_retenu"] = n + 1
        if cle == (0, 0):
            break  # rien de mieux a esperer
    if meilleur is None:
        # Rien a sauver : l echec prime, et il est rendu tel quel. Ne JAMAIS
        # fabriquer un succes — c est l autre moitie de la regle.
        return premier_echec if premier_echec is not None else {
            "etape": "banc", "erreur": "aucun tirage effectue"}
    meilleur["tirages"] = max(1, tirages)
    # ⚠️ Les rates restent DITS : les taire ferait croire a une chaine plus
    # stable qu elle n est, alors que la dispersion est le sujet meme.
    meilleur["tirages_rates"] = rates
    return meilleur


def _un_tirage(circuit: dict, sortie: Path) -> dict:
    from routers.schematic import SchematicRequest
    from routers.schematic import generate as generer_schema
    from routers.erc import ERCRequest, run_erc
    from routers.pcb import PcbRequest
    from routers.pcb import generate as generer_pcb
    from routers.placement import AutoPlacementRequest, place_auto
    from routers.routing import RouteAutoRequest, route_auto
    from routers import routing as R

    liaisons = circuit.get("nets") or []
    charge = {
        "components": circuit["components"],
        "nets": [n["name"] for n in liaisons],
        "connections": liaisons,
        "board_width_mm": circuit.get("board_width_mm", 50.0),
        "board_height_mm": circuit.get("board_height_mm", 50.0),
    }
    t0 = time.time()
    sch = generer_schema(SchematicRequest(**charge))
    if not sch.success:
        return {"etape": "schema", "erreur": sch.error}
    kicad_sch = sch.kicad_sch_content.encode()

    erc = run_erc(ERCRequest(kicad_sch_b64=_b64(kicad_sch)))
    if erc.kicad_sch_b64:
        kicad_sch = base64.b64decode(erc.kicad_sch_b64)

    pcb = generer_pcb(PcbRequest(kicad_sch_b64=_b64(kicad_sch), **charge))
    if not pcb.success:
        return {"etape": "pcb", "erreur": pcb.error}
    board = pcb.kicad_pcb_content.encode()

    board = base64.b64decode(place_auto(
        AutoPlacementRequest(kicad_pcb_b64=_b64(board))).kicad_pcb_b64)

    # ⚠️ CONSERVER le board PLACE, pas seulement le route. Sans lui, toute
    # experience comparant deux facons de router compare en realite deux
    # PLACEMENTS — or le placement est stochastique (mesure : 6, 8 et 12
    # connexions manquantes selon le tirage sur la meme carte). On ne pourrait
    # imputer aucun ecart a la variable etudiee.
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "2_placement.kicad_pcb").write_bytes(board)

    # ⚠️ `layers` est le PLAFOND, pas le palier vise : le service part
    # toujours de 2 et s arrete au premier palier qui route a 100 %. Passer 2
    # ici donnait une echelle a UN barreau et interdisait toute escalade —
    # c est ce qui bloquait l ESP32 a 25 % de routage.
    # ⚠️ Le budget suit la TAILLE de la carte. Il valait 1800 s pour toutes.
    # Mesure du 2026-08-29 : dix-sept composants routent en 300 s et laissent
    # de quoi faire neuf tirages ; cent composants consomment les 1800 s au
    # PREMIER tirage, donc sans re-tirage ni escalade — la carte sortait a
    # 59 %, contre 100 % pour les six autres.
    #
    # Partager le budget entre les essais a ete essaye et s est revele
    # desastreux (tous les paliers a 0 %) : un essai tronque ne route rien.
    # C est le TOTAL qu il faut donner, pas le decouper.
    # ⚠️ Plafonne a 3600 s, borne de `RouteAutoRequest.timeout_s` — elle-meme
    # alignee sur `_ROUTE_TIMEOUT_S` du routeur. Un budget de 6000 s a ete
    # refuse par 422 : la frontiere HTTP ne doit jamais etre plus large que ce
    # que le routeur sait consommer, et la deplacer desynchroniserait la
    # chaine (defaut « quatre frontieres » documente dans CLAUDE.md).
    budget = min(3600, max(1800, 60 * len(circuit["components"])))
    route = route_auto(RouteAutoRequest(kicad_pcb_b64=_b64(board), layers=8,
                                        timeout_s=budget))
    # ⚠️ `route_auto` peut ne rendre AUCUN board — c est son contrat quand tous
    # les paliers ont stagne ou echoue, et c est VOULU : rendre le board
    # d entree ferait passer une carte non routee pour un routage aupres d un
    # appelant distrait. Le banc plantait ici sur `b64decode(None)`, ce qui
    # sortait « ECHEC [exception] argument should be a bytes-like object ».
    # Un echec attendu doit se lire comme un echec, pas comme un bug.
    if not route.kicad_pcb_b64:
        return {"etape": "routage",
                "erreur": route.warning or "aucun board rendu (tous paliers en echec)"}
    board = base64.b64decode(route.kicad_pcb_b64)

    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "final.kicad_pcb").write_bytes(board)

    rapport = R._rapport_drc(board)
    violations = rapport.get("violations", []) or []
    txt = board.decode("utf-8", "replace")
    import re
    from collections import Counter
    par_net = Counter()
    for s in re.findall(r"\(segment.*?\n\t*\)", txt, re.DOTALL):
        m = re.search(r'\(net (?:\d+ )?"([^"]*)"\)', s)
        par_net[m.group(1) if m else "?"] += 1
    return {
        "erc_violations": len(erc.violations),
        "routed_percent": route.routed_percent,
        "moteur": route.engine,
        "couches": route.layers,
        "manquantes": len(rapport.get("unconnected_items", []) or []),
        "erreurs": sum(1 for v in violations if v.get("severity") == "error"),
        "avertissements": sum(1 for v in violations if v.get("severity") == "warning"),
        "segments": sum(par_net.values()),
        "segments_gnd": par_net.get("GND", 0),
        "zones": txt.count("(zone"),
        "remplies": txt.count("filled_polygon"),
        "duree_s": round(time.time() - t0, 1),
    }


def _ps_brut() -> str:
    """La table des processus, brute. Isole pour etre falsifiable en test."""
    out = subprocess.run(["ps", "-eo", "pid,args"], check=True,
                         capture_output=True, text=True, timeout=20)
    return out.stdout


def _jvm_freerouting_survivantes() -> list[str]:
    """PID des JVM Freerouting encore VIVANTES.

    ⚠️ Les zombies sont exclus : un `[java] <defunct>` ne consomme ni CPU ni
    RAM, et il y en avait 41 dans le conteneur. Les compter ferait echouer le
    banc pour rien.

    ⚠️ Ne rattrape AUCUNE exception : `ps` injoignable veut dire « je n ai pas
    pu regarder », pas « il n y a rien ». Rendre une liste vide ici serait le
    rapport DRC vide lu « 0 erreur », une fois de plus.
    """
    vivantes = []
    for ligne in _ps_brut().splitlines():
        if "freerouting.jar" not in ligne or "<defunct>" in ligne:
            continue
        champs = ligne.split(None, 1)
        if champs and champs[0].isdigit():
            vivantes.append(champs[0])
    return vivantes


def _redemarrer_freerouting() -> None:
    """Redemarre la JVM Freerouting AVANT chaque carte, et le VERIFIE.

    ⚠️ Elle se degrade, et c est MESURE. Meme carte `stm32-100`, meme code :

        JVM neuve, run isole        97 %, 96 %, 99 %  ->  100 % livre
        JVM de 2 h, 4e carte        38 %, 30 %, 11 %  ->  aucun board

    La fuite est documentee — 400 Mo nominal, jusqu a 2,4 Go apres une journee
    de jobs. Une passe qui durait 0,15 s en prend plusieurs minutes, et la
    detection de stagnation, qui compte le temps SANS PROGRES, coupe alors des
    tirages parfaitement vivants.

    ⚠️ CE REDEMARRAGE N A JAMAIS EU LIEU jusqu au 2026-08-30 :

        pkill: killing pid 56869 failed: Operation not permitted

    Le banc tourne en `cirqix`, la JVM tournait en `root`. L erreur etait avalee
    par `check=False, capture_output=True`, et le message de succes s imprimait
    quand meme — donc a chaque carte le banc AJOUTAIT une JVM. Etat trouve apres
    sept cartes : une orpheline root a 550 % de CPU et 2,4 Go, swap sature. Le
    banc de reference a mesure exactement l usure qu il devait supprimer.

    ⚠️ Le silence etait DELIBERE (« doit tourner meme sans droits ») et c est
    lui qui a cache le defaut une journee entiere. Une survivante leve
    desormais : mieux vaut un banc arrete qu un banc qui mesure la JVM d hier.
    Aucun `except Exception` ici — c est le silence qu on retire.
    """
    if not shutil.which("java"):
        return

    subprocess.run(["pkill", "-9", "-f", "freerouting.jar"],
                   check=False, capture_output=True, timeout=20)

    limite = time.time() + _ATTENTE_MORT_JVM_S
    survivantes = _jvm_freerouting_survivantes()
    while survivantes and time.time() < limite:
        time.sleep(1.0)
        survivantes = _jvm_freerouting_survivantes()

    if survivantes:
        raise RuntimeError(
            "JVM Freerouting survivante(s) apres le pkill : PID %s. Le banc "
            "tourne en %s et ne peut pas tuer un processus d un autre "
            "utilisateur. Mesurer maintenant, c est mesurer l usure de la JVM "
            "precedente — on arrete." % (", ".join(survivantes),
                                         getpass.getuser()))

    Path("/tmp/freerouting").mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        ["java", "-jar", "/opt/freerouting/freerouting.jar",
         "--api_server.enabled=true", "--user_data_path=/tmp/freerouting"],
        cwd="/tmp/freerouting",
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    time.sleep(30)
    print("  (JVM Freerouting redemarree)", flush=True)


def _fichier_de_cas(dossier: Path) -> Optional[Path]:
    """Le fichier d entree d un cas, quel que soit son nom.

    ⚠️ Deux noms coexistent dans `examples/`, et ils portent la MEME chose :

        input/circuit.json   nets = [{name, pins}]
        input/schema.json    nets = ["VCC", ...]  +  connections = [{name, pins}]

    Le second est deja la forme que ce banc CONSTRUIT pour appeler le service.
    Ne reconnaitre que le premier ecartait `led-blinker-full-pipeline` — le cas
    de reference du pipeline complet selon CLAUDE.md — sans rien dire.
    """
    for nom in ("circuit.json", "schema.json"):
        f = dossier / "input" / nom
        if f.is_file():
            return f
    return None


def _pourquoi_ecarte(dossier: Path) -> str:
    """Motif LISIBLE d un cas non mesurable — jamais un silence."""
    entree = dossier / "input"
    if not entree.is_dir():
        return "pas de dossier input/"
    presents = sorted(f.name for f in entree.iterdir() if f.is_file())
    if not presents:
        return "input/ vide"
    return "input/ ne contient que : %s" % ", ".join(presents[:4])


def _normaliser(brut: dict) -> dict:
    """Ramene les deux formats d entree a une seule forme : nets = [{name, pins}].

    `schema.json` separe deja les noms (`nets`) des liaisons (`connections`) ;
    `circuit.json` met tout dans `nets`. On rend la forme detaillee.
    """
    if isinstance(brut.get("connections"), list):
        return {**brut, "nets": brut["connections"]}
    return brut


def main(argv: list[str]) -> int:
    # ⚠️ `examples/` n est PAS monte dans le conteneur : il est cuit dans
    # l image. On accepte donc une racine d exemples explicite, sinon le banc
    # ne verrait que les cas de l image.
    global _EXEMPLES
    if argv[1:] and Path(argv[1]).is_dir():
        _EXEMPLES = Path(argv.pop(1))
    tirages = 1
    for arg in list(argv[1:]):
        if arg.startswith("--tirages="):
            tirages = int(arg.split("=", 1)[1])
            argv.remove(arg)
    if argv[1:]:
        cas = argv[1:]
    else:
        cas, ecartes = [], []
        for d in sorted(_EXEMPLES.iterdir()):
            if not d.is_dir():
                continue
            if _fichier_de_cas(d):
                cas.append(d.name)
            else:
                ecartes.append((d.name, _pourquoi_ecarte(d)))
        # ⚠️ DIRE ce qu on n a pas mesure. La decouverte filtrait EN SILENCE
        # sur `input/circuit.json` : `led-blinker-full-pipeline` fournit un
        # `input/schema.json` — deja au bon format, seulement sous un autre nom
        # — et n a donc JAMAIS ete mesure par ce banc, alors que CLAUDE.md le
        # presente comme le cas de reference du pipeline complet. Personne ne
        # pouvait le voir : un banc qui omet une carte rend exactement la meme
        # sortie qu un banc qui n en a que six.
        for nom, raison in ecartes:
            print("  (ecarte : %-26s %s)" % (nom, raison), flush=True)
    print(f"{'cas':<18}{'comp':>5}{'couches':>8}{'%':>5}{'manq':>6}"
          f"{'err':>5}{'warn':>6}{'seg':>6}{'GND':>5}{'duree':>8}")
    resultats = {}
    for nom in cas:
        f = _fichier_de_cas(_EXEMPLES / nom)
        if f is None:
            # ⚠️ Ne PAS sauter en silence. Le 2026-08-27, trois lancements de
            # suite n ont produit que la ligne d en-tete : la racine d exemples
            # etait la mauvaise, aucun cas ne correspondait, et le banc sortait
            # en rc=0 comme s il avait travaille. J ai conclu deux fois que le
            # processus « mourait ».
            print("cas introuvable : %s (%s)"
                  % (_EXEMPLES / nom, _pourquoi_ecarte(_EXEMPLES / nom)),
                  file=sys.stderr)
            continue
        circuit = _normaliser(json.loads(f.read_text(encoding="utf-8")))
        _redemarrer_freerouting()
        try:
            r = _passer(circuit, _EXEMPLES / nom / "output", tirages)
        except Exception as exc:
            # ⚠️ Le TYPE et la PILE, pas seulement le message. Une exception au
            # message vide sortait « ECHEC [exception] » et rien d autre —
            # mesure du 2026-08-30 sur `nucleo-f401`, impossible a diagnostiquer.
            # Un rapport d echec qui ne dit pas ce qui a echoue ne vaut rien.
            import traceback
            trace = traceback.format_exc().strip().splitlines()
            derniere = next((l.strip() for l in reversed(trace)
                             if l.strip() and not l.strip().startswith("File ")), "")
            r = {"etape": "exception",
                 "erreur": "%s: %s" % (type(exc).__name__,
                                       str(exc)[:70] or derniere[:70])}
            print("  trace : " + " | ".join(l.strip() for l in trace[-4:]),
                  file=sys.stderr, flush=True)
        resultats[nom] = r
        if "erreur" in r:
            print(f"{nom:<18} ECHEC [{r.get('etape')}] {r['erreur'][:60]}", flush=True)
            continue
        print(f"{nom:<18}{len(circuit['components']):>5}{r['couches']:>8}"
              f"{r['routed_percent']:>5}{r['manquantes']:>6}{r['erreurs']:>5}"
              f"{r['avertissements']:>6}{r['segments']:>6}{r['segments_gnd']:>5}"
              f"{r['duree_s']:>7}s", flush=True)
    (_EXEMPLES / "banc.json").write_text(
        json.dumps(resultats, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

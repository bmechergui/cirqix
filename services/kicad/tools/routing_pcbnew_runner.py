#!/usr/bin/env python3
"""Run routing-related pcbnew work in a short-lived isolated process.

Usage (internal): ``python routing_pcbnew_runner.py '<json>'``.
All inputs and outputs are file paths.  The parent process owns the timeout and
temporary directory, so a hung or crashing pcbnew instance cannot corrupt an
uvicorn worker that is concurrently serving other routing requests.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
import os
import time
from pathlib import Path


# Boards que pcbnew a refuse de charger. On les conserve pour pouvoir les
# examiner : sans cela le fichier fautif est perdu avec le repertoire
# temporaire, et il ne reste qu une AttributeError sans contexte.
_DOSSIER_ILLISIBLES = Path(os.environ.get("KICAD_JOBS_DIR", "/tmp/kicad-jobs")) / "boards-illisibles"
_MAX_ILLISIBLES = 10


def _charger_board(pcbnew, chemin: str):
    """`LoadBoard` avec un echec EXPLICITE et le board fautif conserve.

    ⚠️ `_charger_board(pcbnew, )` rend `None` — pas une exception, `None` — quand il
    ne sait pas lire un fichier. Utiliser ce None donne une
    `AttributeError: NoneType has no attribute GetTracks`, a trois niveaux du
    vrai probleme.

    Mesure du 2026-08-26 : c est exactement ce qui arrivait a l ESP32 du banc.
    L export Specctra echouait, Freerouting n etait jamais appele, et la
    cascade retombait sur kicad-tools — 19 connexions manquantes et 5 erreurs,
    quand les quatre autres cartes etaient propres. Le board fautif partait
    avec le repertoire temporaire : impossible de savoir lequel, ni pourquoi.
    """
    board = pcbnew.LoadBoard(chemin)
    if board is not None:
        return board
    garde = ""
    try:
        _DOSSIER_ILLISIBLES.mkdir(parents=True, exist_ok=True)
        anciens = sorted(_DOSSIER_ILLISIBLES.glob("*.kicad_pcb"))
        for vieux in anciens[: max(0, len(anciens) - _MAX_ILLISIBLES + 1)]:
            vieux.unlink(missing_ok=True)
        copie = _DOSSIER_ILLISIBLES / ("%d.kicad_pcb" % int(time.time() * 1000))
        copie.write_bytes(Path(chemin).read_bytes())
        garde = " — copie conservee : %s" % copie
    except Exception:
        garde = " — copie impossible"
    raise RuntimeError(
        "pcbnew n a pas pu charger le board %s (LoadBoard a rendu None)%s"
        % (chemin, garde))

def _export_specctra(pcbnew, args: dict[str, str]) -> None:
    board = _charger_board(pcbnew, args["pcb"])
    for track in list(board.GetTracks()):
        board.Remove(track)
    pcbnew.ExportSpecctraDSN(board, args["dsn"])


def _specctra_roundtrip(pcbnew, args: dict[str, str]) -> None:
    board = _charger_board(pcbnew, args["pcb"])
    # Freerouting's SES replaces every old route; retaining stale tracks can
    # create dangling ends after placement changes.
    for track in list(board.GetTracks()):
        board.Remove(track)
    pcbnew.ImportSpecctraSES(board, args["ses"])
    for zone in board.Zones():
        # KiCad 10 : ZONE.SetFilled a disparu (renomme SetIsFilled) ; sous
        # KiCad 9 les deux existent. La boucle ne s executait JAMAIS —
        # aucun board de la chaine ne portait de zone — donc l erreur est
        # restee invisible jusqu au 2026-08-21, ou les plans de masse
        # coules avant le routage l ont declenchee : le processus enfant
        # sortait en AttributeError et Freerouting echouait aux deux
        # niveaux. Garde : tests/test_zone_setisfilled.py.
        # ⚠️ Selon le board, `board.Zones()` rend des `ZONE` types ou de
        # simples `SwigPyObject` sans methodes — constate le 2026-08-21 sur
        # un board issu de `kct stitch` :
        #     AttributeError: 'SwigPyObject' object has no attribute
        #                     'SetIsFilled'
        # On ne force le drapeau que s il est atteignable : `ZONE_FILLER.Fill`
        # le pose de toute facon. Le nom differe aussi entre KiCad 9
        # (`SetFilled`) et 10 (`SetIsFilled`).
        marque = getattr(zone, "SetIsFilled", None) or getattr(zone, "SetFilled", None)
        if marque is not None:
            marque(True)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(args["output"], board)


def _fill_zones(pcbnew, args: dict[str, str]) -> None:
    """Remplit les zones de CUIVRE. Sans cela un plan n est qu un contour."""
    board = _charger_board(pcbnew, args["pcb"])
    # ⚠️ `SetIsFilled(True)` DECLARE la zone remplie sans calculer un seul
    # polygone : le fichier sort avec des zones et zero `filled_polygon`.
    # C est exactement le defaut trouve le 2026-08-23. Seul `ZONE_FILLER.Fill`
    # produit du cuivre ; le drapeau ne sert qu a autoriser le calcul.
    for zone in board.Zones():
        marque = getattr(zone, "SetIsFilled", None) or getattr(zone, "SetFilled", None)
        if marque is not None:
            marque(True)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(args["output"], board)


def _connected_pads(connectivity, pad, pcbnew):
    """Pads relies au pad donne, quelle que soit la version de KiCad.

    ⚠️ `GetConnectedItems()` a change de signature. Lue dans la bibliotheque
    du conteneur (KiCad 10) :

        GetConnectedItems(self, aItem, int aFlags=0)

    La liste de types a disparu : KiCad 10 rend TOUS les items relies, et le
    filtrage revient a l appelant. KiCad 9, lui, exigeait cette liste. On
    tente donc la forme recente puis l ancienne, et on filtre en Python dans
    les deux cas — un filtre local est correct partout.

    Defaut reste invisible : cette mesure ne sert qu aux chemins FREEROUTING,
    morts jusqu au 2026-08-21. Garde : tests/test_mesure_connectivite.py.
    """
    try:
        # KiCad 10 : rend TOUS les items relies, le filtrage revient a l appelant.
        items = connectivity.GetConnectedItems(pad)
        return [i for i in items if i.Type() == pcbnew.PCB_PAD_T]
    except TypeError:
        # KiCad 9 : la liste de types est exigee, et le filtrage est fait par
        # la bibliotheque — inutile de refiltrer ici.
        return connectivity.GetConnectedItems(pad, [pcbnew.PCB_PAD_T])


# Geometrie de l echappement — PURE, sans pcbnew, donc testable.
#
# ⚠️ Pose a l aveugle, le fanout ajoutait 6 ERREURS dont deux courts-circuits
# GND/+3.3V (mesure du 2026-08-23, board STM32). Choisir une direction de
# sortie est de la geometrie : on la separe de la manipulation de board.
_ROTATIONS = tuple(range(0, 360, 15))   # la naturelle d abord, puis on tourne
_ECHANTILLON = 100_000                  # 0,1 mm entre deux points du trajet
# Facteurs de distance essayes, la nominale d abord. Une sortie n est pas
# seulement une DIRECTION : a direction egale, quelques dixiemes de plus ou de
# moins font passer le via entre deux obstacles ou non. Mesure du 2026-08-23 :
# a distance unique, 2 pastilles du LQFP-48 restaient orphelines a chaque
# tirage. Rallonger SEULEMENT (1,2 -> 2,0 mm) avait empire le resultat — il
# faut pouvoir raccourcir aussi.
# La portee de la sortie est DERIVEE de la geometrie, jamais listee.
#
# ⚠️ Une liste de facteurs reglee sur un board ne vaut que pour ce board.
# Mesure du 2026-08-23 : la patte 8 du LQFP-48 avait besoin de 2,5 mm quand
# la portee s arretait a 1,8 — mais un QFN de 5 mm ou un BGA de 15 en
# demanderaient tout autre chose. Ce qui borne la recherche, c est la TAILLE
# DU BOITIER : au-dela de son encombrement, on n est plus dans la zone que
# ses propres broches encombrent.
#
# Le pas vaut le diametre du via : plus grand, on sauterait par-dessus un
# interstice ou il tenait ; plus petit, on paie des essais sans gain.
_PAS_MAX_ESSAIS = 40          # borne de securite, jamais atteinte en pratique


def _distances_a_essayer(nominal: float, portee: float, pas: float):
    """Distances de sortie : le nominal, puis on s en ecarte alternativement.

    ⚠️ Il faut pouvoir RACCOURCIR autant qu allonger. Mesure du 2026-08-23 :
    porter la sortie de 1,2 a 2,0 mm avait EMPIRE le resultat — 0 sortie posee
    au lieu de 7 — un trajet plus long croisant simplement davantage
    d obstacles. Balayer seulement vers le haut reproduirait cette erreur.

    Le nominal vient en premier : c est la distance qui marche presque
    toujours, et une sortie courte est plus propre qu une longue.
    """
    pas = max(pas, 50_000.0)
    yield nominal
    for i in range(1, _PAS_MAX_ESSAIS):
        court = nominal - i * pas
        if court >= pas:
            yield court
        long = nominal + i * pas
        if long <= portee:
            yield long
        elif court < pas:
            return


def _dist_point_boite(x: float, y: float, boite) -> float:
    """Distance d un point a une boite (gauche, haut, droite, bas). 0 si dedans."""
    gauche, haut, droite, bas = boite
    dx = max(gauche - x, 0.0, x - droite)
    dy = max(haut - y, 0.0, y - bas)
    return (dx * dx + dy * dy) ** 0.5


def _trajet_libre(x0, y0, x1, y1, obstacles, marge, exempt=None) -> bool:
    """Vrai si tout le segment reste a `marge` des obstacles d un autre net.

    ⚠️ `exempt` est la boite du PAD lui-meme, et l exemption est necessaire :
    sur un LQFP-48 les pastilles font 0,3 mm au pas de 0,5 — 0,2 mm d espace
    entre deux voisines. Le long de sa propre pastille, la piste d echappement
    (0,25 mm) reste DANS l empreinte du pad : sa distance aux voisines est
    celle du pad, que la carte accepte deja. Sans cette exemption le controle
    echoue des le point de depart et AUCUNE broche fine-pitch ne peut sortir
    — mesure du 2026-08-23 : 0 broche sortie, 3 connexions manquantes.

    Au-dela du pad, la marge pleine s applique : c est la que le via se pose
    et que les courts-circuits se creaient.
    """
    if not obstacles:
        return True
    dx, dy = x1 - x0, y1 - y0
    longueur = (dx * dx + dy * dy) ** 0.5
    pas = max(2, int(longueur / _ECHANTILLON) + 1)
    for i in range(pas + 1):
        t = i / pas
        px, py = x0 + dx * t, y0 + dy * t
        if exempt is not None and _dist_point_boite(px, py, exempt) == 0:
            continue  # dans sa propre pastille : la clearance est celle du pad
        for boite in obstacles:
            if _dist_point_boite(px, py, boite) < marge:
                return False
    return True


def _choisir_sortie(x0, y0, vx, vy, distance, obstacles, marge, exempt=None,
                    marge_piste=None, portee=None, pas=None):
    """Premiere direction dont le trajet ENTIER est degage, sinon None.

    La direction naturelle (a l oppose du centre du boitier) est essayee en
    premier : c est le canal que le halo d escape du placement a reserve. On
    ne tourne que si elle est occupee.

    ⚠️ Rendre None est un resultat LEGITIME : ne rien poser vaut mieux qu un
    court-circuit. Une broche orpheline se voit au DRC et bloque la commande ;
    un court-circuit peut partir en fabrication.
    """
    import math
    norme = (vx * vx + vy * vy) ** 0.5
    if norme < 1e-9:
        return None
    base = math.atan2(vy / norme, vx / norme)
    # `distance` reste le point de depart naturel ; `portee` et `pas` sont
    # derives du boitier par l appelant. Sans eux on garde le comportement
    # historique — une seule distance — plutot que d inventer une borne.
    depart = distance
    portee = portee if portee is not None else distance
    pas = pas if pas is not None else max(distance / 4.0, 1.0)
    # ⚠️ La DIRECTION prime sur la longueur : on epuise toutes les distances
    # d une direction avant de tourner. Le couloir reserve par le halo
    # d escape du placement vaut mieux qu une deviation — l ordre inverse
    # faisait devier de 45 degres la ou raccourcir de 0,4 mm suffisait.
    for degres in _ROTATIONS:
        for signe in ((1, -1) if degres else (1,)):
            angle = base + math.radians(degres) * signe
            for d in _distances_a_essayer(depart, portee, pas):
                x1 = x0 + math.cos(angle) * d
                y1 = y0 + math.sin(angle) * d
                # ⚠️ La PISTE et le VIA n exigent pas la meme marge : 0,25 mm
                # de large contre 0,60. Imposer celle du via au trajet entier
                # lui demandait le DOUBLE de son besoin, et aucune broche
                # fine-pitch ne pouvait sortir — mesure du 2026-08-23 :
                # 0,318 mm disponible pour 0,500 exige, quand la piste seule
                # en reclame 0,325.
                if not _trajet_libre(x0, y0, x1, y1, obstacles,
                                     marge_piste or marge, exempt):
                    continue
                # Le via, lui, ne se pose qu au BOUT : sa marge ne vaut que la.
                if any(_dist_point_boite(x1, y1, o) < marge for o in obstacles):
                    continue
                return int(x1), int(y1)
    return None


def _direction_d_echappement(pad, centre_fp) -> tuple:
    """Direction de sortie : l AXE LONG de la pastille, oriente vers l exterieur.

    ⚠️ On utilisait la direction « a l oppose du centre du boitier ». Sur un QFP
    elle est DIAGONALE pour toute pastille qui n est pas au milieu d un cote —
    mesure du 2026-08-23 sur le LQFP-48 : 28,4 degres d ecart pour les pattes 35
    et 47, les deux seules qui echouaient. A ce biais, la sortie entre
    immediatement dans les pastilles voisines (obstacle mesure a 0,000 mm des
    0,8 mm) et aucune distance ne la sauve.

    Une patte de QFP s echappe perpendiculairement au bord du boitier, c est-a-
    dire dans le prolongement de sa propre pastille. Le centre ne sert plus qu a
    choisir le SENS — vers l exterieur, jamais vers le silicium.

    Pastille carre (via, THT rond) : pas d axe long, on retombe sur le centre.
    """
    pos = pad.GetPosition()
    dx, dy = float(pos.x - centre_fp.x), float(pos.y - centre_fp.y)
    try:
        b = pad.GetBoundingBox()
        largeur = float(b.GetRight() - b.GetLeft())
        hauteur = float(b.GetBottom() - b.GetTop())
    except Exception:
        return dx, dy
    # 20 % d ecart : en deca la pastille est trop carree pour designer un axe.
    if max(largeur, hauteur) < 1.2 * min(largeur, hauteur):
        return dx, dy
    if largeur > hauteur:
        return (1.0 if dx >= 0 else -1.0), 0.0
    return 0.0, (1.0 if dy >= 0 else -1.0)


def _portee_d_echappement(fp, via_d: float) -> tuple:
    """(portee, pas) de la recherche de sortie, derives du BOITIER lui-meme.

    ⚠️ Ce qui encombre le voisinage d une patte, ce sont les autres pattes du
    meme boitier et les pistes qui en sortent. La zone a franchir est donc
    proportionnelle a la TAILLE du composant : un LQFP-48 de 9 mm, un QFN de 5,
    un BGA de 15 n ont pas le meme besoin. Une liste de distances reglee sur un
    board ne vaudrait que pour ce board.

    Portee = l encombrement du boitier. Au-dela, on a quitte la zone que ses
    propres broches saturent ; s il n y a toujours pas de place, c est que le
    voisinage est occupe par autre chose, et allonger encore ne ferait que
    croiser davantage de pistes.

    Pas = le diametre du via. Plus grand, on sauterait par-dessus un interstice
    ou il tenait ; plus petit, on paie des essais sans gain.
    """
    try:
        b = fp.GetBoundingBox()
        taille = max(float(b.GetRight() - b.GetLeft()),
                     float(b.GetBottom() - b.GetTop()))
    except Exception:
        taille = 0.0
    return max(taille, via_d * 4), max(via_d, 100_000.0)


def _obstacles_d_un_autre_net(board, net_code) -> list:
    """Boites englobantes des pistes, vias et pads d un AUTRE net."""
    boites = []
    for item in list(board.GetTracks()) + [
        p for fp in board.GetFootprints() for p in fp.Pads()
    ]:
        try:
            if item.GetNetCode() == net_code:
                continue
            b = item.GetBoundingBox()
            boites.append((b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom()))
        except Exception:
            continue  # un item sans boite ni net ne peut pas etre un obstacle connu
    return boites

# Percage minimal fabricable. En deca, on dessinerait un trou que personne ne
# peut realiser — JLCPCB descend a 0,20 mm de diametre de via.
_VIA_MIN_MM = 200_000.0


def _diametre_via_in_pad(largeur_pad: float, via_nominal: float) -> float:
    """Diametre d un via pose DANS la pastille. 0 si aucun ne tient.

    ⚠️ Le via ne doit JAMAIS depasser la pastille. Tout l argument tient la :
    un via aussi large qu elle herite de SA clearance, celle que la carte
    accepte deja. Plus large, il redevient un obstacle pour les voisines.

    Mesure du 2026-08-26, LQFP-48 : pastille 0,30 x 1,48 mm, obstacle le plus
    proche a 0,350 mm — un via de 0,30 tient, la ou aucune sortie laterale
    n existait (0 chemin degage sur 567 candidats).

    On ne retrecit pas sans raison : un via plus fin perce plus petit et coute
    plus cher a fabriquer.
    """
    d = min(largeur_pad, via_nominal)
    return d if d >= _VIA_MIN_MM else 0.0

def _escape_pads(pcbnew, args: dict[str, str]) -> None:
    """Fanout : une courte piste depuis chaque broche isolee vers un via.

    Le plan ne peut pas atteindre les pattes d un boitier au pas de 0,5 mm.
    On sort donc la patte par une courte piste, puis on traverse par un via.

    ⚠️ La sortie CONSULTE son environnement (`_choisir_sortie`). Posee a
    l aveugle — direction opposee au centre, sans regarder le trajet — elle
    ajoutait 6 ERREURS dont deux courts-circuits GND/+3.3V sur le board STM32
    (mesure du 2026-08-23). Une broche sans sortie degagee est RENONCEE, pas
    forcee : orpheline elle bloque la commande au DRC, court-circuitee elle
    peut partir en fabrication.
    """
    board = _charger_board(pcbnew, args["pcb"])
    cibles = json.loads(args["pads"])
    largeur = int(float(args.get("trace_mm", "0.25")) * 1_000_000)
    distance = float(args.get("escape_mm", "1.2")) * 1_000_000
    via_d = int(float(args.get("via_mm", "0.6")) * 1_000_000)
    perc_d = int(float(args.get("drill_mm", "0.3")) * 1_000_000)
    # Marge : demi-via + clearance visee. Le DRC fautif mesurait 0,0181 mm.
    clearance = float(args.get("clearance_mm", "0.2")) * 1_000_000
    marge = via_d / 2 + clearance          # le via, au bout du trajet
    marge_piste = largeur / 2 + clearance  # la piste, sur tout le trajet

    poses = 0
    renonces = 0
    for ref, nom_pad in cibles:
        fp = board.FindFootprintByReference(str(ref))
        if fp is None:
            continue
        pad = next((p for p in fp.Pads() if str(p.GetPadName()) == str(nom_pad)), None)
        if pad is None:
            continue

        centre = fp.GetPosition()
        pos = pad.GetPosition()
        dx, dy = _direction_d_echappement(pad, centre)
        if (dx * dx + dy * dy) ** 0.5 < 1.0:
            continue  # pad au centre exact : pas de direction de sortie evidente

        obstacles = _obstacles_d_un_autre_net(board, pad.GetNetCode())
        b = pad.GetBoundingBox()
        propre = (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())
        portee, pas = _portee_d_echappement(fp, via_d)
        sortie = _choisir_sortie(
            pos.x, pos.y, dx, dy, distance, obstacles, marge, propre, marge_piste,
            portee, pas
        )
        if sortie is None:
            # Dernier recours : le via DANS la pastille. Il n a besoin
            # d aucune piste — pose au centre, il traverse vers le plan de
            # l autre face, et le probleme du chemin lateral disparait.
            larg = min(float(b.GetRight() - b.GetLeft()),
                       float(b.GetBottom() - b.GetTop()))
            d = _diametre_via_in_pad(larg, via_d)
            if d <= 0 or any(_dist_point_boite(pos.x, pos.y, o) < d / 2 + clearance
                             for o in obstacles):
                renonces += 1
                continue
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pos)
            via.SetWidth(int(d))
            via.SetDrill(int(max(d / 2, _VIA_MIN_MM / 2)))
            via.SetNetCode(pad.GetNetCode())
            board.Add(via)
            poses += 1
            continue
        vx, vy = sortie

        piste = pcbnew.PCB_TRACK(board)
        piste.SetStart(pos)
        piste.SetEnd(pcbnew.VECTOR2I(vx, vy))
        piste.SetWidth(largeur)
        piste.SetLayer(pad.GetLayer())
        piste.SetNetCode(pad.GetNetCode())
        board.Add(piste)

        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pcbnew.VECTOR2I(vx, vy))
        via.SetWidth(via_d)
        via.SetDrill(perc_d)
        via.SetNetCode(pad.GetNetCode())
        board.Add(via)
        poses += 1

    pcbnew.SaveBoard(args["output"], board)
    Path(args["result"]).write_text(
        json.dumps({"escaped": poses, "renonces": renonces}), encoding="utf-8"
    )


def _plan_escape(pcbnew, args: dict[str, str]) -> None:
    """Calcule les positions de via SANS toucher au board.

    ⚠️ Se lance sur le board PLACE, avant le routage des signaux. Apres, il n y
    a plus de place : mesure du 2026-08-23, 504 candidats essayes autour des
    pattes orphelines du LQFP-48 — 21 distances x 24 directions, jusqu a
    12,7 mm — aucun ne passe, le voisinage comptant alors 182 obstacles.

    Les positions rendues sont ensuite DECLAREES dans le DSN pour que le
    routeur travaille autour, puis reposees apres l aller-retour Specctra.
    """
    board = _charger_board(pcbnew, args["pcb"])
    cibles = json.loads(args["pads"])
    largeur = int(float(args.get("trace_mm", "0.25")) * 1_000_000)
    distance = float(args.get("escape_mm", "1.2")) * 1_000_000
    via_d = int(float(args.get("via_mm", "0.6")) * 1_000_000)
    clearance = float(args.get("clearance_mm", "0.2")) * 1_000_000
    marge, marge_piste = via_d / 2 + clearance, largeur / 2 + clearance

    positions = []
    renonces = 0
    for ref, nom_pad in cibles:
        fp = board.FindFootprintByReference(str(ref))
        if fp is None:
            continue
        pad = next((p for p in fp.Pads() if str(p.GetPadName()) == str(nom_pad)), None)
        if pad is None:
            continue
        pos = pad.GetPosition()
        dx, dy = _direction_d_echappement(pad, fp.GetPosition())
        if (dx * dx + dy * dy) ** 0.5 < 1.0:
            continue
        obstacles = _obstacles_d_un_autre_net(board, pad.GetNetCode())
        b = pad.GetBoundingBox()
        propre = (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())
        portee, pas = _portee_d_echappement(fp, via_d)
        sortie = _choisir_sortie(pos.x, pos.y, dx, dy, distance, obstacles,
                                 marge, propre, marge_piste, portee, pas)
        if sortie is None:
            renonces += 1
            continue
        positions.append({"ref": str(ref), "pad": str(nom_pad),
                          "pad_x": int(pos.x), "pad_y": int(pos.y),
                          "via_x": int(sortie[0]), "via_y": int(sortie[1]),
                          "layer": int(pad.GetLayer()), "net": int(pad.GetNetCode())})
    Path(args["result"]).write_text(
        json.dumps({"vias": positions, "renonces": renonces}), encoding="utf-8")

def _candidats_de_couture(x0, y0, portee, pas):
    """Positions de via candidates, du plus proche au plus lointain.

    Un ilot peut s etendre dans n importe quelle direction : chercher sur un
    seul axe reviendrait a supposer sa forme. On balaie donc en anneaux.
    """
    import math

    pas = max(pas, 50_000.0)
    rayon = pas
    while rayon <= portee:
        n = max(8, int(2 * math.pi * rayon / pas))
        for i in range(n):
            a = 2 * math.pi * i / n
            yield int(x0 + math.cos(a) * rayon), int(y0 + math.sin(a) * rayon)
        rayon += pas


def _est_relie(pcbnew, board, pad, temoin) -> bool:
    """Vrai si `pad` et `temoin` sont relies par du cuivre continu."""
    if temoin is None:
        return False
    board.BuildConnectivity()
    conn = board.GetConnectivity()
    conn.RecalculateRatsnest()
    cible = temoin.m_Uuid.AsString()
    for item in _connected_pads(conn, pad, pcbnew):
        try:
            if item.m_Uuid.AsString() == cible:
                return True
        except Exception:
            continue
    return False


def _stitch_islands(pcbnew, args: dict[str, str]) -> None:
    """Recoud par un via les pastilles isolees dans un ilot de plan.

    ⚠️ On ne DEVINE pas ou poser : on essaie et on VERIFIE. Chaque candidat est
    pose, la connectivite reconstruite, et le via n est garde que si la
    pastille rejoint un TEMOIN — une broche du meme net restee sur le plan
    principal. Un via pose au juge peut atterrir dans le meme ilot et ne rien
    relier : il ne resterait qu un trou de percage facture et un obstacle de
    plus pour le routage suivant.
    """
    board = _charger_board(pcbnew, args["pcb"])
    cibles = json.loads(args["pads"])
    via_d = int(float(args.get("via_mm", "0.6")) * 1_000_000)
    perc_d = int(float(args.get("drill_mm", "0.3")) * 1_000_000)
    portee = float(args.get("portee_mm", "8.0")) * 1_000_000

    isoles = {(str(r), str(n)) for r, n in cibles}
    poses = 0
    for ref, nom_pad in cibles:
        fp = board.FindFootprintByReference(str(ref))
        if fp is None:
            continue
        pad = next((p for p in fp.Pads() if str(p.GetPadName()) == str(nom_pad)), None)
        if pad is None:
            continue
        # Temoin : une broche du MEME net qui n est pas elle-meme isolee.
        temoin = None
        for f in board.GetFootprints():
            for q in f.Pads():
                if (q.GetNetCode() == pad.GetNetCode()
                        and (str(f.GetReference()), str(q.GetPadName())) not in isoles):
                    temoin = q
                    break
            if temoin is not None:
                break
        pos = pad.GetPosition()
        obstacles = _obstacles_d_un_autre_net(board, pad.GetNetCode())
        marge = via_d / 2 + float(args.get("clearance_mm", "0.2")) * 1_000_000
        for x, y in _candidats_de_couture(pos.x, pos.y, portee, via_d):
            if any(_dist_point_boite(x, y, o) < marge for o in obstacles):
                continue
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(x, y))
            via.SetWidth(via_d)
            via.SetDrill(perc_d)
            via.SetNetCode(pad.GetNetCode())
            board.Add(via)
            if _est_relie(pcbnew, board, pad, temoin):
                poses += 1
                break
            board.Remove(via)

    pcbnew.SaveBoard(args["output"], board)
    Path(args["result"]).write_text(json.dumps({"stitched": poses}), encoding="utf-8")

def _points_dans_boite(x1, y1, x2, y2, pas):
    """Points candidats dans une boite : le centre d abord, puis une grille.

    Le centre est le meilleur pari sur un ilot convexe — et la plupart le
    sont. On ne balaie que s il est refuse par le polygone.
    """
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    yield cx, cy
    pas = max(int(pas), 100_000)
    y = y1 + pas // 2
    while y < y2:
        x = x1 + pas // 2
        while x < x2:
            if (x, y) != (cx, cy):
                yield x, y
            x += pas
        y += pas


def _stitch_zones(pcbnew, args: dict[str, str]) -> None:
    """Pose un via dans chaque ilot d un plan, pour les relier par l autre face.

    ⚠️ Les pistes de signal DECOUPENT le plan de la face composants. Mesure du
    2026-08-26, carte a 100 composants : zone GND sur F.Cu = 5 ilots, sur B.Cu
    = 1 seul. Le DRC les signalait par des paires
    `Zone [GND] <-> Zone [GND]` que la couture de PASTILLES ne pouvait pas
    traiter — il n y a pas de pastille en cause, seulement du cuivre coupe.

    ⚠️ Le point de pose est VERIFIE dans le polygone (`Contains`) : le centre
    d une boite englobante tombe hors d un ilot concave, et un via pose dehors
    ne relierait rien.
    """
    board = _charger_board(pcbnew, args["pcb"])
    nets = set(json.loads(args.get("nets", "[]")))
    via_d = int(float(args.get("via_mm", "0.6")) * 1_000_000)
    perc_d = int(float(args.get("drill_mm", "0.3")) * 1_000_000)
    clearance = float(args.get("clearance_mm", "0.2")) * 1_000_000

    poses = 0
    for zone in board.Zones():
        try:
            nom = str(zone.GetNetname())
        except Exception:
            continue
        if nets and nom not in nets:
            continue
        obstacles = _obstacles_d_un_autre_net(board, zone.GetNetCode())
        for couche in zone.GetLayerSet().Seq():
            try:
                poly = zone.GetFilledPolysList(couche)
                total = poly.OutlineCount()
            except Exception:
                continue
            if total < 2:
                continue  # plan d un seul tenant : rien a recoudre
            for i in range(total):
                b = poly.Outline(i).BBox()
                pose = False
                for x, y in _points_dans_boite(b.GetLeft(), b.GetTop(),
                                               b.GetRight(), b.GetBottom(), via_d * 3):
                    pt = pcbnew.VECTOR2I(int(x), int(y))
                    try:
                        if not poly.Contains(pt, i):
                            continue
                    except Exception:
                        continue
                    if any(_dist_point_boite(x, y, o) < via_d / 2 + clearance
                           for o in obstacles):
                        continue
                    via = pcbnew.PCB_VIA(board)
                    via.SetPosition(pt)
                    via.SetWidth(via_d)
                    via.SetDrill(perc_d)
                    via.SetNetCode(zone.GetNetCode())
                    board.Add(via)
                    poses += 1
                    pose = True
                    break
                if not pose:
                    continue

    pcbnew.SaveBoard(args["output"], board)
    Path(args["result"]).write_text(json.dumps({"stitched": poses}), encoding="utf-8")

def _measure_connectivity(pcbnew, args: dict[str, str]) -> None:
    board = _charger_board(pcbnew, args["pcb"])
    if not board.BuildConnectivity():
        raise RuntimeError("pcbnew failed to build board connectivity")
    connectivity = board.GetConnectivity()
    connectivity.RecalculateRatsnest()

    # ⚠️ Les nets CONFIES AU PLAN sont exclus. La mesure a lieu juste apres
    # le routeur, AVANT que les plans soient coules : a cet instant ils n ont
    # aucun cuivre et comptent comme non routes. Mesure du 2026-08-26 — une
    # carte LED entierement connectee (0 manquante, 0 violation) etait
    # annoncee a 66 %, et `routed_percent < 100` declenche le reasoner, les
    # re-tirages de placement et le repli.
    exclus = {n for n in json.loads(args.get("exclure_nets", "[]")) if n}
    pads_by_net: dict[int, list] = defaultdict(list)
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            net_code = int(pad.GetNetCode())
            if net_code <= 0:
                continue
            try:
                if str(pad.GetNetname()) in exclus:
                    continue
            except Exception:
                pass
            pads_by_net[net_code].append(pad)

    unrouted_nets = 0
    for net_pads in pads_by_net.values():
        if len(net_pads) < 2:
            continue
        first_pad = net_pads[0]
        # GetConnectedPads() only returns directly touching pads.  A routed net
        # normally crosses a transitive pad -> tracks/vias -> pad chain, so use
        # KiCad's cluster search and ask it specifically for pad items.
        connected = {
            str(pad.m_Uuid.AsString())
            for pad in _connected_pads(connectivity, first_pad, pcbnew)
            if int(pad.GetNetCode()) == int(first_pad.GetNetCode())
        }
        # Some KiCad versions omit the source item from GetConnectedItems().
        connected.add(str(first_pad.m_Uuid.AsString()))
        expected = {str(pad.m_Uuid.AsString()) for pad in net_pads}
        if not expected.issubset(connected):
            unrouted_nets += 1

    Path(args["result"]).write_text(
        json.dumps({"unrouted_nets": unrouted_nets}), encoding="utf-8"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: routing_pcbnew_runner.py '<json>'", file=sys.stderr)
        return 64

    import pcbnew  # type: ignore[import-not-found]

    args = json.loads(argv[1])
    operation = args.get("operation")
    if operation == "export_specctra":
        _export_specctra(pcbnew, args)
    elif operation == "specctra_roundtrip":
        _specctra_roundtrip(pcbnew, args)
    elif operation == "stitch_zones":
        _stitch_zones(pcbnew, args)
    elif operation == "stitch_islands":
        _stitch_islands(pcbnew, args)
    elif operation == "plan_escape":
        _plan_escape(pcbnew, args)
    elif operation == "fill_zones":
        _fill_zones(pcbnew, args)
    elif operation == "escape_pads":
        _escape_pads(pcbnew, args)
    elif operation == "measure_connectivity":
        _measure_connectivity(pcbnew, args)
    else:
        raise ValueError(f"unsupported operation: {operation!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

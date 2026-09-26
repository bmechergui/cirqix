#!/usr/bin/env python3
"""Run routing-related pcbnew work in a short-lived isolated process.

Usage (internal): ``python routing_pcbnew_runner.py '<json>'``.
All inputs and outputs are file paths.  The parent process owns the timeout and
temporary directory, so a hung or crashing pcbnew instance cannot corrupt an
uvicorn worker that is concurrently serving other routing requests.
"""
from __future__ import annotations

import json
import math
import re
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

    # ⚠️ Tentative de reparation AVANT de renoncer. KiCad refuse le fichier
    # ENTIER si une valeur de keepout est entre guillemets :
    #     (keepout (tracks "not_allowed") ...)  -> None
    #     (keepout (tracks not_allowed) ...)    -> charge
    # Mesure du 2026-08-26 : c est ce qui privait l ESP32 du banc de
    # Freerouting, le renvoyant sur un chemin degrade a 19 connexions
    # manquantes. Le keepout fautif vient de kicad-tools, pas de nous.
    #
    # La reparation vit ICI, dans le chargeur, et pas chez un appelant :
    # SIX operations chargent un board, et n en corriger qu une laissait
    # echouer les cinq autres — mesure : 3 boards illisibles encore
    # capturees apres avoir corrige le seul export Specctra.
    try:
        brut = Path(chemin).read_text(encoding="utf-8", errors="replace")
        motif = (chr(92) + "((tracks|vias|pads|copperpour|footprints) " +
                 chr(34) + "([a-z_]+)" + chr(34) + chr(92) + ")")
        repare, n = re.subn(motif, lambda m: "(%s %s)" % (m.group(1), m.group(2)), brut)
        if n:
            Path(chemin).write_text(repare, encoding="utf-8")
            board = pcbnew.LoadBoard(chemin)
            if board is not None:
                return board
    except Exception:
        pass
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
            if _distance_a_obstacle(px, py, boite) < marge:
                return False
    return True


def _sortie_reservee_valide(x0, y0, x1, y1, obstacles, marge, exempt=None,
                            marge_piste=None, obstacles_via=None) -> bool:
    """La sortie reservee avant le routage tient-elle encore sur ce board ?

    Memes deux criteres que `_choisir_sortie`, appliques a UNE position au lieu
    d en chercher une : trajet degage a la marge de la PISTE, point de chute
    degage a la marge du VIA. Les deux marges different — 0,25 mm de large
    contre 0,60 — et les confondre faisait renoncer toute broche fine-pitch.

    ⚠️ Rejouer sans verifier ramenerait les 6 erreurs du 2026-08-23, dont deux
    courts-circuits GND/+3,3 V : entre le calcul et la repose, le routeur a pose
    des pistes que la reservation ne pouvait pas connaitre.
    """
    if not _trajet_libre(x0, y0, x1, y1, obstacles, marge_piste or marge, exempt):
        return False
    # ⚠️ Le trajet ne vit que sur la couche de la pastille ; le VIA traverse.
    # Voir `_choisir_sortie` : deux listes d obstacles, jamais une seule.
    pour_le_via = obstacles if obstacles_via is None else obstacles_via
    return not any(_distance_a_obstacle(x1, y1, o) < marge for o in pour_le_via)


def _choisir_sortie(x0, y0, vx, vy, distance, obstacles, marge, exempt=None,
                    marge_piste=None, portee=None, pas=None, prefere=None,
                    obstacles_via=None):
    """Premiere direction dont le trajet ENTIER est degage, sinon None.

    ⚠️ DEUX listes d obstacles, pas une. `obstacles` est ce que la PISTE doit
    eviter — le cuivre d un autre net sur la couche de la pastille, la seule
    ou elle existe. `obstacles_via` est ce que le VIA doit eviter au point de
    chute — toutes les couches, puisqu il les traverse. Mesure du 2026-09-14,
    carte-10, U1.8 (GND, F.Cu) : le couloir sur F.Cu etait libre et un via GND
    attendait a 1,2 mm, mais une piste IO_L14 sur B.Cu, SOUS la pastille,
    comptait comme obstacle du trajet — la broche restait orpheline du plan a
    tous les paliers, de 2 a 8 couches. Sans `obstacles_via`, la liste unique
    sert aux deux (comportement historique).

    ⚠️ `prefere(x, y)` ORDONNE les sorties degagees, il n en filtre aucune :
    la premiere sortie degagee que `prefere` accepte est rendue ; a defaut,
    la premiere sortie degagee tout court. Mesure du 2026-09-12 (carte-08/10,
    stm32-100) : le via d echappement d une broche GND tombait dans un ilot
    B.Cu de 1 mm2 isole par les pistes, retire ensuite comme flottant — la
    broche restait orpheline tirage apres tirage. Preferer un via qui touche
    le plan principal d en face regle le cas ; l EXIGER a deja ete refute
    (2026-09-01, 1 -> 4 manquantes).

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
    pour_le_via = obstacles if obstacles_via is None else obstacles_via
    premiere = None  # la premiere sortie degagee, si aucune n est preferee
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
                # Le via, lui, ne se pose qu au BOUT : sa marge ne vaut que la —
                # mais sur TOUTES les couches qu il traverse.
                if any(_distance_a_obstacle(x1, y1, o) < marge for o in pour_le_via):
                    continue
                if prefere is None or prefere(x1, y1):
                    return int(x1), int(y1)
                if premiere is None:
                    premiere = (int(x1), int(y1))
    return premiere


def _dans_le_plan_principal(polys, x, y, vec) -> bool:
    """Le point est-il dans le PLUS GRAND contour rempli d un des polygones ?

    Le plus grand contour est le plan lui-meme ; les autres sont des ilots que
    les pistes ont detaches. Un via qui touche un ilot ne relie rien de
    durable — l ilot part au retrait des flottants, et le via avec.
    `vec(x, y)` construit le point dans le type attendu par le polygone.
    """
    pt = vec(x, y)
    for poly in polys or ():
        try:
            n = poly.OutlineCount()
            if n <= 0:
                continue
            principal = max(range(n), key=lambda i: poly.Outline(i).Area())
            if poly.Contains(pt, principal):
                return True
        except Exception:  # noqa: BLE001 — un doute ne prefere rien
            continue
    return False


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


def _dist_point_segment(px: float, py: float,
                        x1: float, y1: float, x2: float, y2: float) -> float:
    """Distance d un point a un SEGMENT — pas a son rectangle englobant.

    ⚠️ Mesure du 2026-09-02, `stm32-30` : les trois ilots non relies
    recevaient enfin des points candidats, et 100 % etaient rejetes. Les
    obstacles etaient des BOITES ENGLOBANTES, et celle d une piste diagonale
    couvre toute la diagonale — une surface sans commune mesure avec le cuivre
    reel, large de 0,25 mm. Un petit ilot coince entre deux pistes tombait
    entierement dans l un de ces rectangles.

    Le meme symptome avait ete vu sans etre compris : l obstacle le plus proche
    de `D3.2` etait mesure a 0,000 mm, le centre de la pastille se trouvant
    « dans » la boite d une piste eloignee.
    """
    dx, dy = x2 - x1, y2 - y1
    longueur2 = dx * dx + dy * dy
    if longueur2 <= 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / longueur2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _distance_a_obstacle(px: float, py: float, obstacle) -> float:
    """Distance au CUIVRE de l obstacle, quelle que soit sa forme.

    Un obstacle est soit une boite `(x1, y1, x2, y2)` — pastille, forme dont
    le rectangle est representatif — soit un segment
    `("segment", x1, y1, x2, y2, largeur)` : une piste, dont le rectangle ne
    l est pas.
    """
    if obstacle and obstacle[0] == "segment":
        _, x1, y1, x2, y2, largeur = obstacle
        return max(0.0, _dist_point_segment(px, py, x1, y1, x2, y2)
                   - float(largeur) / 2.0)
    return _dist_point_boite(px, py, obstacle)


def _couloir_libre(depart, arrivee, obstacles, demi_largeur: float,
                   degagement: float) -> bool:
    """Le segment `depart -> arrivee` laisse-t-il passer une piste ?

    `obstacles` : au choix des cercles `(x, y, rayon)` — la forme utile pour
    un test — ou les boites et segments de `_obstacles_d_un_autre_net`. Toutes
    les valeurs dans la MEME unite (mm pour les tests, nanometres en service).

    La distance est exacte, jamais echantillonnee : un obstacle a 0,30 mm de
    l axe doit refuser une piste de 0,25 mm a 0,2 mm de degagement (0,325), et
    accepter a 0,35. Un echantillonnage a ce point rendrait le verdict
    dependant du pas.
    """
    marge = float(demi_largeur) + float(degagement)
    for o in obstacles:
        if len(o) == 3 and not (o and o[0] == "segment"):
            x, y, rayon = o
            d = _dist_point_segment(float(x), float(y), depart[0], depart[1],
                                    arrivee[0], arrivee[1]) - float(rayon)
        else:
            # Boite ou segment : on echantillonne le TRAJET, la distance au
            # cuivre etant deja exacte dans `_distance_a_obstacle`.
            # ⚠️ LE PAS ETAIT EGAL A LA MARGE, donc un bond plus court que la
            # marge n etait juge que par ses DEUX BOUTS. La distance a un
            # cuivre est convexe le long d un segment : son minimum tombe a
            # l INTERIEUR, jamais aux extremites. Mesure du 2026-09-22 : les
            # pistes reposees apres arrachage passaient ce controle et le DRC
            # de KiCad rendait 426 violations, toutes a 0,1993 mm pour 0,2000
            # exiges — sept dixiemes de micrometre, c est-a-dire exactement ce
            # qu un echantillonnage a deux points laisse passer. Un huitieme de
            # marge borne l erreur sans couter : un bond court reste a
            # quelques points.
            pas = max(marge / 8.0, 1e-9)
            longueur = math.hypot(arrivee[0] - depart[0], arrivee[1] - depart[1])
            n = max(2, int(longueur / pas) + 2)
            d = min(_distance_a_obstacle(
                depart[0] + (arrivee[0] - depart[0]) * k / (n - 1),
                depart[1] + (arrivee[1] - depart[1]) * k / (n - 1), o)
                for k in range(n))
        if d < marge:
            return False
    return True


# Combien de segments d un autre net on accepte d ARRACHER pour rouvrir le
# couloir d un amas de masse enferme. ⚠️ Sans plafond, « lesquels oter » est une
# recherche combinatoire ouverte — la faute que `_NOEUDS_MAX_CONTOURNEMENT`
# interdit deja pour l A*. Mesure du 2026-09-22 sur le board fautif de
# `carte-10` : UN seul segment coupe le couloir de chaque face (`EXT2_1` a
# 0,862 mm sur F.Cu, `EXT4_1` a 0,781 mm sur B.Cu). Trois laisse de la marge
# sans ouvrir la porte a un arrachage massif — on repare une carte, on ne la
# re-route pas.
_SEGMENTS_ARRACHABLES: int = 3


# Combien de BUTS au plus l A* de raccord accepte. ⚠️ Son heuristique prend
# le minimum sur TOUS les buts, a chaque noeud : passer de un but a la liste
# entiere du plan principal rend `h()` proportionnel au nombre de buts, et
# `_NOEUDS_MAX_CONTOURNEMENT` ne borne QUE le nombre de noeuds, jamais le cout
# de chacun. Sur un grand plan les cibles se comptent par milliers et se
# reaccumulaient une fois par ilot orphelin : la famine que ce plafond devait
# empecher revenait par la porte de derriere (revue du 2026-09-22).
_BUTS_MAX: int = 64


def _buts_bornes(cibles, depart, repli):
    """Les buts de l A*, dedoublonnes et bornes aux plus proches du depart.

    Viser TOUT le plan plutot qu un seul de ses points est ce qui permet de
    contourner un obstacle par l autre cote ; le faire sans borne rend la
    recherche impayable. On garde donc les `_BUTS_MAX` plus proches — un
    raccord de masse qui devrait viser un point plus lointain que les
    soixante-quatre plus proches n en serait pas un.

    Rend toujours au moins un but (`repli`) : une liste vide ferait renoncer
    l A* pour une raison qui n a rien a voir avec la geometrie.
    """
    if not cibles:
        return [repli]
    uniques = list(dict.fromkeys((float(x), float(y)) for x, y in cibles))
    if len(uniques) > _BUTS_MAX:
        uniques.sort(key=lambda c: (c[0] - depart[0]) ** 2
                     + (c[1] - depart[1]) ** 2)
        uniques = uniques[:_BUTS_MAX]
    return uniques or [repli]


def _segments_qui_bloquent(depart, arrivee, obstacles, demi_largeur: float,
                           degagement: float) -> list:
    """Les obstacles qui, A EUX SEULS, ferment ce couloir — et qu on peut bouger.

    Rend les INDICES dans `obstacles`, dans l ordre. Seuls les obstacles de
    forme `("segment", x1, y1, x2, y2, largeur)` sont candidats.

    ⚠️ ON NE DEPLACE QU UN SEGMENT DE PISTE. Une pastille appartient a une
    empreinte dont le placement est deja arbitre ; un via porte une liaison
    verticale et un percage. Les bouger pour faire passer de la masse
    defairait le travail des etapes precedentes — c est la faute « deux
    correctifs qui se combattent », deja payee le 2026-08-27.
    """
    genants = []
    for k, o in enumerate(obstacles):
        if not (o and o[0] == "segment"):
            continue
        if not _couloir_libre(depart, arrivee, [o], demi_largeur, degagement):
            genants.append(k)
    return genants


def _couloir_degageable(depart, arrivee, obstacles, demi_largeur: float,
                        degagement: float,
                        plafond: int = _SEGMENTS_ARRACHABLES):
    """Ce couloir s ouvre-t-il en arrachant quelques segments ? Lesquels ?

    Rend la liste des indices a arracher — **vide** si le couloir est deja
    libre — ou `None` si l on ne sait pas le degager.

    ⚠️ UNE LISTE VIDE ET UN `None` NE DISENT PAS LA MEME CHOSE. « rien a
    arracher » est un succes, « je ne sais pas degager » un echec : les
    confondre ferait exactement ce que ce depot traque partout, un echec qui
    rend la valeur du cas normal.

    Trois raisons de renoncer, toutes mesurables :
      - plus de `plafond` segments bloquent — on ne re-route pas la carte ;
      - un obstacle qui n est PAS un segment bloque aussi (pastille, via) ;
      - les retirer tous ne suffit pas a ouvrir le couloir.
    """
    if _couloir_libre(depart, arrivee, obstacles, demi_largeur, degagement):
        return []
    genants = _segments_qui_bloquent(depart, arrivee, obstacles,
                                     demi_largeur, degagement)
    if not genants or len(genants) > int(plafond):
        return None
    restes = [o for k, o in enumerate(obstacles) if k not in set(genants)]
    if not _couloir_libre(depart, arrivee, restes, demi_largeur, degagement):
        # Ce ne sont pas QUE des segments qui ferment : l arrachage serait paye
        # pour rien, et on aurait casse des liaisons sans rien reparer.
        return None
    return genants


# Plafond de noeuds visites par l A* de raccord. ⚠️ Une portee geometrique ne
# borne PAS le travail : chaque noeud interroge tous les obstacles du board
# (des milliers). `(portee / pas)^2` x obstacles se compte en milliards sur une
# grande carte — un blocage de plusieurs minutes DANS `route_auto` (revue du
# 2026-09-21). Ce depot a deja paye deux fois ce genre de famine.
_NOEUDS_MAX_CONTOURNEMENT: int = 20000


def _chemin_de_contournement(depart, buts, libre, pas: float,
                             portee: float, noeuds_max: int = _NOEUDS_MAX_CONTOURNEMENT):
    """A* sur grille : le plus court chemin de `depart` a l un des `buts`.

    ⚠️ LA LIGNE DROITE EST REFUTEE (mesure du 2026-09-21 : « 5 amas vus, AUCUN
    raccorde »). Un ilot de plan est isole PAR une piste qui le coupe : toute
    droite vers le plan la retraverse. Avis convergents de Codex, GLM et
    OpenCode — « une piste n est un mur que d un cote », il faut contourner son
    BOUT.

    `libre(x, y)` decide de chaque case ; `pas` est la resolution ; `portee`
    borne la recherche (rayon autour du depart). Rend la liste des points, ou
    None — et un None se lit « pas de chemin dans ce budget », jamais « pas
    besoin » : l appelant doit le DIRE.

    Fonction PURE : ni pcbnew, ni geometrie KiCad. 8 directions, cout
    euclidien, heuristique = distance au but le plus proche.
    """
    import heapq

    if not buts:
        return None
    cases = [(round(bx / pas), round(by / pas)) for bx, by in buts]
    arrivees = set(cases)
    depart_case = (round(depart[0] / pas), round(depart[1] / pas))
    if not libre(depart_case[0] * pas, depart_case[1] * pas):
        return None
    limite = max(1, int(portee / pas))

    def h(c):
        return min(math.hypot(c[0] - a[0], c[1] - a[1]) for a in cases) * pas

    ouverts = [(h(depart_case), 0.0, depart_case)]
    venu, cout = {depart_case: None}, {depart_case: 0.0}
    visites = 0
    while ouverts:
        if visites >= noeuds_max:
            return None          # budget de TRAVAIL epuise — on le DIT au retour
        visites += 1
        _f, g, c = heapq.heappop(ouverts)
        if c in arrivees:
            chemin, k = [], c
            while k is not None:
                chemin.append((k[0] * pas, k[1] * pas))
                k = venu[k]
            return list(reversed(chemin))
        if g > cout.get(c, float("inf")):
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                v = (c[0] + dx, c[1] + dy)
                if (abs(v[0] - depart_case[0]) > limite
                        or abs(v[1] - depart_case[1]) > limite):
                    continue
                g2 = g + math.hypot(dx, dy) * pas
                if g2 > portee or g2 >= cout.get(v, float("inf")):
                    continue
                if v not in arrivees and not libre(v[0] * pas, v[1] * pas):
                    continue
                cout[v], venu[v] = g2, c
                heapq.heappush(ouverts, (g2 + h(v), g2, v))
    return None


def _via_gene_par(px: float, py: float, diametre: float,
                  clearance: float, obstacles) -> bool:
    """Le cuivre de ce via approche-t-il un obstacle de trop pres ?

    ⚠️ EXTRAIT pour etre mesurable. Inline dans deux fonctions, cette regle ne
    pouvait etre testee que par leurs effets — et c est ainsi que
    `_poser_via_dans_pastille` a diverge de `_escape_pads` sans que rien ne le
    signale, alors que sa docstring promet d en « reutiliser exactement les
    regles ».
    """
    demi = diametre / 2.0 + clearance
    return any(_distance_a_obstacle(px, py, o) < demi for o in obstacles)


def _couches_cuivre_d_un_item(item) -> set:
    """Les couches CUIVRE que l item occupe reellement.

    ⚠️ Fail-closed : illisible rend l ensemble VIDE, ce qui prive de toute
    dispense au lieu d en accorder une sans preuve.
    """
    try:
        return {int(c) for c in item.GetLayerSet().CuStack()}
    except Exception:
        return set()


def _couches_cuivre_du_board(board) -> set:
    """Les couches cuivre de l empilage — celles que le via traverse."""
    try:
        return {int(c) for c in board.GetEnabledLayers().CuStack()}
    except Exception:
        return set()


def _est_sur_une_couche(item, couches) -> bool:
    """Vrai si l item porte du cuivre sur AU MOINS une des couches visees.

    ⚠️ Fail-closed : un item dont les couches sont illisibles est CONSERVE
    comme obstacle. Mieux vaut refuser une pose licite que percer a l aveugle.
    """
    try:
        return any(item.IsOnLayer(int(c)) for c in couches)
    except Exception:
        return True


def _couches_traversees_hors_pastille(couches_pad, couches_cuivre) -> set:
    """Les couches ou le via pose du cuivre que la pastille NE COUVRE PAS.

    La dispense de degagement du via en pastille est juste — sur la couche de
    la pastille. Une pastille CMS n existe que sur une face ; le via traverse
    tout l empilage et pose ailleurs du cuivre que rien ne vouche.

    ⚠️ Fail-closed : une pastille dont les couches sont illisibles n obtient
    AUCUNE dispense, et tout est verifie.
    """
    return set(couches_cuivre) - set(couches_pad)


def _obstacles_d_un_autre_net(board, net_code, couches=None) -> list:
    """Obstacles d un AUTRE net : les pistes en SEGMENTS, le reste en boites.

    ⚠️ Une piste diagonale n occupe pas son rectangle englobant. La reduire a
    sa boite declarait obstrues des points ou le cuivre passe a plusieurs
    millimetres — et bloquait 100 % des candidats de la couture sur les petits
    ilots.
    """
    obstacles = []
    for item in board.GetTracks():
        try:
            if item.GetNetCode() == net_code:
                continue
            if couches is not None and not _est_sur_une_couche(item, couches):
                continue
            # ⚠️ S ANCRER SUR CE QUI NE VARIE PAS. Une premiere version testait
            # `GetClass() == "PCB_TRACE"` : la classe s appelle en realite
            # `PCB_TRACK`, aucune piste n etait reconnue, et les 167 segments
            # du board restaient traites en boites — le correctif ne
            # s appliquait a RIEN. Dans `GetTracks()`, tout ce qui n est pas un
            # via est un segment ; un arc traite par sa corde reste infiniment
            # plus juste que par son rectangle englobant.
            if item.GetClass() != "PCB_VIA" and hasattr(item, "GetStart"):
                d, f = item.GetStart(), item.GetEnd()
                obstacles.append(("segment", float(d.x), float(d.y),
                                  float(f.x), float(f.y),
                                  float(item.GetWidth())))
                continue
            b = item.GetBoundingBox()
            obstacles.append((b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom()))
        except Exception:
            continue  # un item sans forme ni net ne peut pas etre un obstacle connu
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            try:
                if pad.GetNetCode() == net_code:
                    continue
                if couches is not None and not _est_sur_une_couche(pad, couches):
                    continue
                b = pad.GetBoundingBox()
                obstacles.append((b.GetLeft(), b.GetTop(),
                                  b.GetRight(), b.GetBottom()))
            except Exception:
                continue
    return obstacles

# Ecart minimal entre deux PERCAGES, mesure bord a bord. JLCPCB demande
# 0,5 mm : en deca les deux trous se rejoignent au percage.
_ECART_TROUS_MM = 500_000.0


def _trous_perces(board) -> list[tuple[float, float, float]]:
    """(x, y, rayon de percage) de chaque trou DEJA present sur le board.

    ⚠️ Un trou est un obstacle pour un autre trou QUEL QUE SOIT SON NET.
    `_obstacles_d_un_autre_net` ecarte volontairement le net courant : c est
    juste pour du CUIVRE — deux pistes GND peuvent se toucher sans court-circuit
    — et faux pour un PERCAGE, que deux vias ne peuvent pas partager.

    Mesure du 2026-09-01 (`nucleo-f401`, board `99_final`) : 131 vias pour
    94 positions, 7 positions percees x5 — une par passe de couture — et 116
    avertissements `holes_co_located` absents du board place.
    """
    trous: list[tuple[float, float, float]] = []
    pads = [p for fp in board.GetFootprints() for p in fp.Pads()]
    for item in list(board.GetTracks()) + pads:
        rayon = 0.0
        for nom in ("GetDrillValue", "GetDrillSizeX"):
            try:
                rayon = float(getattr(item, nom)()) / 2.0
            except Exception:
                continue
            if rayon > 0:
                break
        if rayon <= 0:
            continue  # pas de percage : pastille CMS, piste, zone
        try:
            p = item.GetPosition()
            trous.append((float(p.x), float(p.y), rayon))
        except Exception:
            continue  # un objet perce mais sans position ne peut pas gener
    return trous


_TOLERANCE_VIA_EXISTANT_NM = 50_000


def _via_existant_a(vias, x, y, netcode: int, tolerance=_TOLERANCE_VIA_EXISTANT_NM) -> bool:
    """Un via du MEME net est-il deja a cette position (a 50 um pres) ?

    ⚠️ Mesure du 2026-09-11 (carte-08, board trace) : autour de chaque broche
    GND du LQFP, le via reserve etait bien la, a 1,20 mm — le routeur l avait
    conserve — mais AUCUNE piste ne le reliait a la pastille. A la repose,
    `_trou_libre` voyait ce via comme un trou occupe et RENONCAIT : la
    pastille restait orpheline a cause du via qui devait la relier. Un via
    du meme net deja en place n est pas un obstacle, c est le travail a
    moitie fait : il ne manque que le troncon.
    """
    for vx, vy, vnet in vias or ():
        if int(vnet) == int(netcode) and abs(vx - x) <= tolerance and abs(vy - y) <= tolerance:
            return True
    return False


def _troncon_deja_la(segments, x0, y0, x1, y1, netcode: int,
                     tolerance=_TOLERANCE_VIA_EXISTANT_NM) -> bool:
    """Un troncon du meme net joint-il deja ces deux points (dans un sens ou l autre) ?

    ⚠️ Chaque repose des sorties reservees — un palier, un tirage — reposait le
    troncon pastille -> via par-dessus le precedent. Mesure du 2026-09-14,
    carte-10 : jusqu a NEUF troncons identiques de 1,2 mm sur un meme via. Du
    cuivre superpose ne relie rien de plus et alourdit le board.
    `segments` : (x_debut, y_debut, x_fin, y_fin, netcode).
    """
    def proche(ax, ay, bx, by):
        return abs(ax - bx) <= tolerance and abs(ay - by) <= tolerance
    for sx0, sy0, sx1, sy1, n in segments:
        if int(n) != int(netcode):
            continue
        if (proche(sx0, sy0, x0, y0) and proche(sx1, sy1, x1, y1)) or \
           (proche(sx0, sy0, x1, y1) and proche(sx1, sy1, x0, y0)):
            return True
    return False


def _trou_libre(x: float, y: float, rayon: float,
                trous: list[tuple[float, float, float]], ecart: float) -> bool:
    """Vrai si l on peut percer en (x, y) sans toucher un trou existant."""
    return all(
        math.hypot(x - tx, y - ty) >= rayon + tr + ecart for tx, ty, tr in trous
    )


# Percage minimal fabricable. En deca, on dessinerait un trou que personne ne
# peut realiser — JLCPCB descend a 0,20 mm de diametre de via.
_VIA_MIN_MM = 200_000.0


def _bilan_coherent(vises: int, poses: int, renonces: int) -> bool:
    """Toute pastille visee doit etre POSEE ou RENONCEE — jamais oubliee.

    ⚠️ Mesure du 2026-09-01 : « 1 reliee sur 3 visees, 0 renoncee ». Deux
    pastilles n etaient ni l un ni l autre — un `continue` muet les sortait de
    la boucle. Un abandon silencieux est indistinguable d un travail complet,
    et c est la faute que le projet paie le plus souvent.
    """
    return poses + renonces == vises


# Percage minimal que le DRC de KiCad applique PAR DEFAUT. Ce n est pas un
# reglage : c est la contrainte du juge (`board setup constraints min hole`).
# ⚠️ A ne pas confondre avec `_VIA_MIN_MM`, qui borne le DIAMETRE d un via
# chez JLCPCB (0,20 mm). Confondre les deux a produit des vias perces a
# 0,28 mm, refuses par `drill_out_of_range` — mesure du 2026-09-02.
_PERCAGE_MIN_KICAD_MM: float = 300_000.0


def _percage_pour_via(diametre_via: float) -> float:
    """Percage d un via : la moitie de son diametre, jamais sous le minimum.

    Mesure du 2026-09-02 : un via de 0,56 mm donnait 0,28 mm de percage, et le
    DRC le refusait — « min hole 0.3000 mm; actual 0.2800 mm ». Le plancher
    utilise etait `_VIA_MIN_MM / 2`, soit 0,10 mm : une valeur qui n a rien a
    voir avec le percage, puisqu elle borne le DIAMETRE du via.
    """
    if diametre_via <= 0:
        return 0.0
    return max(diametre_via / 2.0, _PERCAGE_MIN_KICAD_MM)


def _via_in_pad_dispense_de_clearance(diametre_via: float,
                                      largeur_pad: float) -> bool:
    """Ce via tient-il DANS la pastille, au point d heriter de son isolement ?

    ⚠️ L argument est deja ecrit dans `_diametre_via_in_pad` — et le site
    d appel faisait le contraire. Un via qui ne DEPASSE PAS la pastille occupe
    du cuivre que la pastille occupe deja : il ne peut violer aucun isolement
    qu elle ne violerait pas elle-meme, et le board est accepte avec elle.
    Redemander un degagement autour de lui, c est exiger deux fois la meme
    chose.

    Mesure du 2026-09-02, les trois pastilles orphelines du banc :

        C5.2  via 0,56 mm  obstacle a 0,395 mm  exige 0,480 mm  ->  REFUSE
        D3.2  via 0,60 mm  obstacle a 0,000 mm  exige 0,500 mm  ->  REFUSE
        C3.2  via 0,56 mm  obstacle a 0,000 mm  exige 0,480 mm  ->  REFUSE

    Les trois sont posees PILE au-dessus du cuivre de masse de B.Cu : un via
    dans la pastille les reliait, et il tenait geometriquement.

    ⚠️ La dispense porte sur le CUIVRE, jamais sur le TROU. Un percage est
    physique : deux trous au meme endroit restent impossibles.
    """
    return 0 < diametre_via <= largeur_pad


def _via_min_fabricable(board) -> float:
    """Plus petit via que les REGLES DU BOARD acceptent (nm) : percage minimal
    + deux anneaux minimaux, et jamais sous la taille minimale de via.

    ⚠️ Mesure du 2026-09-12 (carte-08) : chaque via-in-pad retreci a 0,3-0,5 mm
    recevait un percage plancher de 0,3 mm, donc un anneau nul ou negatif —
    « erreurs ajoutees {'annular_width': 1} » a CHAQUE repose et chaque fanout,
    tous refuses par la garde. Un via qui tient dans la pastille mais pas dans
    les regles n est pas un via.
    """
    try:
        ds = board.GetDesignSettings()
        percage = float(getattr(ds, "m_MinThroughDrill", 0) or 0)
        anneau = float(getattr(ds, "m_ViasMinAnnularWidth", 0) or 0)
        taille = float(getattr(ds, "m_ViasMinSize", 0) or 0)
        return max(_VIA_MIN_MM, taille, percage + 2.0 * anneau)
    except Exception:  # noqa: BLE001
        return _VIA_MIN_MM


def _via_in_pad_possible(largeur_pad: float, via_nominal: float,
                         percage_pad: float, via_min: float = _VIA_MIN_MM) -> float:
    """Diametre du via a poser DANS la pastille. 0 si aucun ne convient.

    ⚠️ UNE PASTILLE DEJA PERCEE LE REFUSE TOUJOURS. Un via dans une pastille
    traversante est un trou dans un trou — meme faute que les vias superposes
    de la couture, corrigee le meme jour. Et il serait de toute facon inutile :
    une pastille traversante relie deja toutes les couches.
    """
    if percage_pad > 0:
        return 0.0
    d = _diametre_via_in_pad(largeur_pad, via_nominal, via_min)
    # ⚠️ Si le PERCAGE minimal ne tient pas dans la pastille, poser le via
    # ferait deborder le trou du cuivre : on renonce plutot que de livrer un
    # board que le DRC refusera. Mesure du 2026-09-02 : une pastille de
    # 0,56 mm accepte tout juste 0,30 mm de percage ; en deca, non.
    if d > 0 and _percage_pour_via(d) > largeur_pad:
        return 0.0
    return d


def _diametre_via_in_pad(largeur_pad: float, via_nominal: float,
                         via_min: float = _VIA_MIN_MM) -> float:
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
    return d if d >= max(_VIA_MIN_MM, via_min) else 0.0

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
    # ⚠️ Les TROUS deja perces, releves une fois puis tenus a jour a chaque
    # pose. `_obstacles_d_un_autre_net` ecarte le net courant : correct pour du
    # cuivre, faux pour un percage. La regle etait posee sur la seule couture,
    # et le board final de `nucleo-f401` sortait avec 150 vias pour
    # 149 positions — un via superpose que cette voie-ci creait.
    ecart_trous = float(args.get("ecart_trous_mm", "0.5")) * 1_000_000
    trous = _trous_perces(board)

    poses = 0
    renonces = 0
    # ⚠️ Positions REPRISES de la reservation d avant-routage. Les compter :
    # un rejeu qui ne se compte pas est indistinguable d un rejeu absent.
    reprises = 0
    # Un via du meme net deja au point de chute : troncon seul (voir `_via_existant_a`).
    vias_existants = [(float(v.GetPosition().x), float(v.GetPosition().y), int(v.GetNetCode()))
                      for v in board.GetTracks() if v.GetClass() == "PCB_VIA"]
    # Les troncons deja poses : on ne superpose jamais un troncon a son jumeau.
    segments_existants = []
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA" or not hasattr(t, "GetStart"):
            continue
        try:
            d, f = t.GetStart(), t.GetEnd()
            segments_existants.append((float(d.x), float(d.y), float(f.x), float(f.y), int(t.GetNetCode())))
        except Exception:
            continue
    troncons_seuls = 0
    for cible in cibles:
        # Deux formes : `[ref, pad]` (fanout post-routage, aucune reservation)
        # et `[ref, pad, via_x, via_y]` (repose d une sortie deja calculee,
        # quand la place existait encore).
        ref, nom_pad = cible[0], cible[1]
        reserve = (int(cible[2]), int(cible[3])) if len(cible) >= 4 else None
        fp = board.FindFootprintByReference(str(ref))
        if fp is None:
            continue
        pad = next((p for p in fp.Pads() if str(p.GetPadName()) == str(nom_pad)), None)
        if pad is None:
            continue

        centre = fp.GetPosition()
        pos = pad.GetPosition()
        dx, dy = _direction_d_echappement(pad, centre)
        # ⚠️ NE PAS SORTIR ICI. Une pastille au centre exact du boitier n a pas
        # de direction laterale evidente — et c est precisement le cas ou le
        # dernier recours, le via DANS la pastille, est la bonne reponse : il
        # n en demande aucune. Le `continue` d origine sautait ce recours ET ne
        # comptait pas l abandon : « 1 reliee sur 3 visees, 0 renoncee ».
        # La convention KiCad place la broche 1 a l origine du footprint, donc
        # toute broche 1 ronde de connecteur passait par la.
        sans_direction = (dx * dx + dy * dy) ** 0.5 < 1.0

        # ⚠️ La PISTE ne vit que sur la couche de la pastille : ses obstacles
        # sont ceux de cette couche. Le VIA traverse : les siens sont ceux de
        # toutes les couches. Une piste de signal sur B.Cu, sous une pastille
        # F.Cu, bloquait le trajet d une sortie qui ne la croise jamais
        # (carte-10, U1.8, 2026-09-14).
        obstacles = _obstacles_d_un_autre_net(board, pad.GetNetCode(),
                                              couches={pad.GetLayer()})
        obstacles_via = _obstacles_d_un_autre_net(board, pad.GetNetCode())
        b = pad.GetBoundingBox()
        propre = (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())
        portee, pas = _portee_d_echappement(fp, via_d)
        # ⚠️ REJOUER AVANT DE RECHERCHER. La position reservee a ete calculee
        # sur le board PLACE, ou le couloir d echappement etait libre ; la
        # recherche, elle, s execute sur le board ROUTE, ou les pistes de
        # signal l ont referme. Chercher a nouveau, c est jeter la seule
        # mesure faite au bon moment.
        # Le cuivre du net sur les AUTRES couches : c est lui que le via doit
        # toucher, et de preference son plan principal, pas un ilot.
        en_face = _cuivre_du_net_sur(board, pad.GetLayer(), pad.GetNetCode())
        prefere = (lambda x, y: _dans_le_plan_principal(
            en_face, x, y, lambda a, b_: pcbnew.VECTOR2I(int(a), int(b_))))
        sortie = None
        if reserve is not None and _sortie_reservee_valide(
                pos.x, pos.y, reserve[0], reserve[1], obstacles, marge,
                propre, marge_piste, obstacles_via=obstacles_via):
            sortie = reserve
            reprises += 1
            # ⚠️ Une position reservee qui ne touche pas le plan principal est
            # rejouee SEULEMENT si aucune sortie degagee ne le touche.
            if not sans_direction and not prefere(reserve[0], reserve[1]):
                mieux = _choisir_sortie(
                    pos.x, pos.y, dx, dy, distance, obstacles, marge, propre,
                    marge_piste, portee, pas, prefere=prefere,
                    obstacles_via=obstacles_via)
                if mieux is not None and prefere(mieux[0], mieux[1]):
                    sortie = mieux
                    reprises -= 1
        if sortie is None and not sans_direction:
            sortie = _choisir_sortie(
                pos.x, pos.y, dx, dy, distance, obstacles, marge, propre,
                marge_piste, portee, pas, prefere=prefere,
                obstacles_via=obstacles_via
            )
        if sortie is None:
            # Dernier recours : le via DANS la pastille. Il n a besoin
            # d aucune piste — pose au centre, il traverse vers le plan de
            # l autre face, et le probleme du chemin lateral disparait.
            larg = min(float(b.GetRight() - b.GetLeft()),
                       float(b.GetBottom() - b.GetTop()))
            try:
                perce = float(pad.GetDrillSizeX())
            except Exception:
                perce = 0.0  # sans percage lisible, on traite en CMS
            d = _via_in_pad_possible(larg, via_d, perce, _via_min_fabricable(board))
            perc = _percage_pour_via(d)
            # ⚠️ Un via qui TIENT dans la pastille herite de SON isolement :
            # exiger un degagement autour de lui reviendrait a demander deux
            # fois la meme chose, et refusait les trois pastilles orphelines
            # du banc alors qu elles surplombaient le plan de B.Cu.
            # Le TROU, lui, reste verifie — un percage est physique.
            gene = (not _via_in_pad_dispense_de_clearance(d, larg)
                    and _via_gene_par(pos.x, pos.y, d, clearance, obstacles_via))
            # ⚠️ LA DISPENSE S ARRETE A LA COUCHE DE LA PASTILLE. Une pastille
            # CMS n existe que sur une face ; le via traverse jusqu a l autre,
            # ou il pose du cuivre que RIEN ne vouche. Mesure du 2026-09-02 sur
            # `stm32-100` : le via herite de l isolement de sa pastille sur
            # F.Cu et se retrouve a 0,0481 mm d une piste GPIO46 sur B.Cu, pour
            # un degagement exige de 0,2 mm. On verifie donc les couches que la
            # pastille NE couvre pas — toujours, dispense ou non.
            nues = _couches_traversees_hors_pastille(
                _couches_cuivre_d_un_item(pad), _couches_cuivre_du_board(board))
            if nues and not gene:
                gene = _via_gene_par(
                    pos.x, pos.y, d, clearance,
                    _obstacles_d_un_autre_net(
                        board, pad.GetNetCode(), couches=nues))
            if (d <= 0 or gene
                    or not _trou_libre(pos.x, pos.y, perc / 2, trous,
                                       ecart_trous)):
                renonces += 1
                continue
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pos)
            via.SetWidth(int(d))
            via.SetDrill(int(perc))
            via.SetNetCode(pad.GetNetCode())
            board.Add(via)
            trous.append((float(pos.x), float(pos.y), perc / 2))
            poses += 1
            continue
        vx, vy = sortie
        # ⚠️ La sortie a ete choisie sur des obstacles de CUIVRE ; un trou
        # existant, lui, n en est pas un pour `_obstacles_d_un_autre_net`
        # quand il porte le meme net. Mesure du 2026-09-02, board final de
        # `nucleo-f401` : 150 vias pour 149 positions — un via superpose que
        # la regle posee sur la seule couture ne pouvait pas voir.
        existant = _via_existant_a(vias_existants, vx, vy, pad.GetNetCode())
        if not existant and not _trou_libre(vx, vy, perc_d / 2, trous, ecart_trous):
            renonces += 1
            continue

        if not _troncon_deja_la(segments_existants, pos.x, pos.y, vx, vy, pad.GetNetCode()):
            piste = pcbnew.PCB_TRACK(board)
            piste.SetStart(pos)
            piste.SetEnd(pcbnew.VECTOR2I(vx, vy))
            piste.SetWidth(largeur)
            piste.SetLayer(pad.GetLayer())
            piste.SetNetCode(pad.GetNetCode())
            board.Add(piste)
            segments_existants.append((float(pos.x), float(pos.y), float(vx), float(vy), int(pad.GetNetCode())))

        if existant:
            troncons_seuls += 1
        else:
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(vx, vy))
            via.SetWidth(via_d)
            via.SetDrill(perc_d)
            via.SetNetCode(pad.GetNetCode())
            board.Add(via)
            trous.append((float(vx), float(vy), perc_d / 2))
        poses += 1
        # ⚠️ AMORCE EN FACE : ESSAYEE LE 2026-09-02, REFUTEE PAR LA MESURE.
        # L idee — poser avec le via une courte piste de masse sur la face
        # opposee, protegee dans le DSN, pour que le plan re-coule rejoigne
        # toujours le via — etait validee par GLM : « sa fin ouverte fusionnera
        # avec le plan puisqu elle porte le meme net, c est un pont force a
        # travers la coupure ». Elle avertissait aussi du bouchon de routage.
        # C est le bouchon qui l a emporte, sur `stm32-100` :
        #
        #                    %   manq  err  seg  segments GND   duree
        #   sans amorce     99     1     0  779       57         901 s
        #   avec amorce     99     1     0  732        6        2798 s
        #
        # Aucun gain sur la connexion manquante, TROIS FOIS plus lent, et les
        # segments GND qui survivent au round-trip Specctra s effondrent de 57
        # a 6 : les amorces protegees genent le routeur au point de faire
        # perdre les dogbones eux-memes. Le remede coutait plus que le mal.
        #
        # ⚠️ C est la CONDITION qui est refutee, pas l analyse : l ilot de
        # `D21` reste cause par un via isole apres coup. Un futur remede devra
        # agir sans ajouter de cuivre protege sur la face du routage.

    pcbnew.SaveBoard(args["output"], board)
    # ⚠️ RENDRE LE NOMBRE DE VISEES, et verifier que le bilan boucle. Sans
    # `vises`, l appelant ne peut pas distinguer « tout traite » de « des
    # pastilles oubliees en route » — c est exactement ce qui a masque le
    # `continue` muet : « 1 reliee sur 3 visees, 0 renoncee ».
    vises = len(cibles)
    if not _bilan_coherent(vises, poses, renonces):
        print("escape_pads: BILAN INCOHERENT — %d visee(s), %d posee(s), "
              "%d renoncee(s) : des pastilles ont disparu de la boucle"
              % (vises, poses, renonces), file=sys.stderr)
    Path(args["result"]).write_text(
        json.dumps({"escaped": poses, "renonces": renonces,
                    "reprises": reprises, "vises": vises,
                    "troncons_seuls": troncons_seuls}), encoding="utf-8"
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
        # Meme regle que `_escape_pads` : la piste sur SA couche, le via sur toutes.
        obstacles = _obstacles_d_un_autre_net(board, pad.GetNetCode(),
                                              couches={pad.GetLayer()})
        obstacles_via = _obstacles_d_un_autre_net(board, pad.GetNetCode())
        b = pad.GetBoundingBox()
        propre = (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())
        portee, pas = _portee_d_echappement(fp, via_d)
        sortie = _choisir_sortie(pos.x, pos.y, dx, dy, distance, obstacles,
                                 marge, propre, marge_piste, portee, pas,
                                 obstacles_via=obstacles_via)
        if sortie is None:
            renonces += 1
            continue
        positions.append({"ref": str(ref), "pad": str(nom_pad),
                          "pad_x": int(pos.x), "pad_y": int(pos.y),
                          "via_x": int(sortie[0]), "via_y": int(sortie[1]),
                          "layer": int(pad.GetLayer()),
                          "layer_nom": board.GetLayerName(pad.GetLayer()),
                          "net": int(pad.GetNetCode())})
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
    # ⚠️ Meme regle que partout ailleurs : un trou est un obstacle pour un
    # autre trou, quel que soit son net.
    ecart_trous = float(args.get("ecart_trous_mm", "0.5")) * 1_000_000
    trous = _trous_perces(board)

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
            if any(_distance_a_obstacle(x, y, o) < marge for o in obstacles):
                continue
            # ⚠️ Un trou deja perce interdit ce point, quel que soit son net.
            if not _trou_libre(x, y, perc_d / 2, trous, ecart_trous):
                continue
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(x, y))
            via.SetWidth(via_d)
            via.SetDrill(perc_d)
            via.SetNetCode(pad.GetNetCode())
            board.Add(via)
            if _est_relie(pcbnew, board, pad, temoin):
                trous.append((float(x), float(y), perc_d / 2))
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


def _via_relie_vraiment(sur_cette_face: bool, sur_la_face_opposee: bool) -> bool:
    """Ce point relie-t-il REELLEMENT deux cuivres du meme net ?

    ⚠️ LA CONDITION QUI FAIT TOUTE LA DIFFERENCE, et qui manquait. Un via pose
    dans un ilot ne relie RIEN si la face opposee n a pas de cuivre du meme net
    a cet endroit : c est un via borgne, du cuivre pour rien. La couture posait
    ses vias sans jamais regarder en face.

    La regle generale demandee par l utilisateur tient en une phrase — « tout
    morceau de cuivre de masse doit posseder au moins un via vers le plan de la
    face opposee » — et elle n a de sens que si le via ATTEINT ce plan.
    """
    return bool(sur_cette_face and sur_la_face_opposee)


def _ilot_est_flottant(vias_dedans: int, vias_reliants: int,
                       pastilles_dedans: int) -> bool:
    """Cet ilot est-il du cuivre FLOTTANT, sans aucune liaison a son net ?

    ⚠️ Mesure du 2026-09-02, `stm32-60` : un ilot de 4,9 mm2 porte UN via, et
    ce via n atteint aucun cuivre de masse sur la face opposee. Du cuivre perce
    pour rien. La suppression native de KiCad ne peut rien : `ALWAYS` retire
    les ilots SANS connexion, et celui-ci en a une — inutile, mais presente.

    Avis de Grok, consulte le 2026-09-02 : « c est du cuivre flottant, pas un
    ilot de reference mal cousu. Plus aucune liaison : ce n est plus une
    reference, c est une plaque. » Le laisser est le pire choix — antenne et
    condensateur de couplage pile sur les signaux qui l ont isole.

    ⚠️ CHIRURGICAL, PAS UN SEUIL. On ne retire pas « les petits ilots » : un
    petit plan encore relie est utile, et le projet a mesure qu une carte
    livree a 100 % en portait six. Une PASTILLE du net sur la meme face suffit
    a garder l ilot, meme sans via.
    """
    if pastilles_dedans > 0:
        return False
    return vias_reliants <= 0


def _ilot_a_relier_par_sa_pastille(vias_reliants: int,
                                   pastilles_dedans: int) -> bool:
    """Cet ilot porte une pastille du net mais n atteint pas le plan ?

    ⚠️ Mesure du 2026-09-02, `stm32-60`. La derniere rupture, annoncee par le
    DRC comme `Zone GND B.Cu <-> Zone GND F.Cu`, vient d un ilot de 4,9 mm2
    qui contient la PASTILLE GND de `C4` : un via dedans, zero reliant.

    Ce n est pas du cuivre flottant — c est le cuivre local d une pastille de
    masse, isolee du reste du plan. Le retirer DECONNECTERAIT C4.

    Et le fanout ne la vise jamais : le DRC ne la declare pas isolee, puisqu
    elle EST reliee — a son petit ilot. C est l ilot qui n atteint pas le plan.

    `C4` est CMS, large de 0,56 mm, et surplombe le cuivre de B.Cu : un via
    dans sa pastille la relie, comme pour `D1`, `D3` et `C5`.

    ⚠️ EXCLUSIF de `_ilot_est_flottant` : un ilot ne peut pas etre a la fois
    retire et relie.
    """
    return pastilles_dedans > 0 and vias_reliants <= 0


def _pas_d_echantillonnage(largeur: float, hauteur: float,
                           via_d: float, fin: bool = False) -> float:
    """Pas de la grille de candidats, DEDUIT de la taille de l ilot.

    ⚠️ Mesure du 2026-09-02 : les petits ilots ne recevaient AUCUN via.

        nucleo-f401   ilot de  8,4 mm2                    0 via
        stm32-30      ilots de 23,9 · 21,2 · 12,4 mm2     0 via
        stm32-60      ilots de  6,6 ·  4,9 mm2            0 via

    Le compte correspond exactement aux ruptures `plan <-> plan` du DRC ; tous
    les ilots plus grands sont relies. La grille avait un pas fixe de
    `via_d * 3`, soit 1,8 mm : sur une languette large de 0,5 mm, aucun point
    ne tombe dedans. L ilot n etait pas REFUSE, il n etait JAMAIS VISITE.

    Deux bornes, toutes deux deduites :
      - assez fin pour que la PLUS PETITE dimension recoive plusieurs points ;
      - jamais plus fin que le via lui-meme — deux points distants de moins
        d un diametre donnent le meme verdict, on paierait des essais sans gain.
    """
    # ⚠️ SECONDE PASSE, sur un ilot qu on s apprete a ABANDONNER (2026-09-21).
    # Le plancher d une passe normale vaut `max(via_d, 1.0)` — juste, puisque
    # deux points a moins d un diametre rendent le meme verdict. Il ne l est
    # plus quand l ilot part a la poubelle : mesure sur le banc, un ilot de
    # 25 mm2 ne recevait que 13 points, dont 8 hors du cuivre (la grille est
    # celle du RECTANGLE ENGLOBANT, et une languette coudee y tient peu de
    # place). On ne renonce pas sans avoir cherche a la resolution du via.
    petite = min(abs(largeur), abs(hauteur))
    if fin:
        # ⚠️ Le PLAFOND doit descendre lui aussi. Premiere version : seul le
        # plancher bougeait, et `petite / 3` le dominait — un ilot de 5 x 5 mm
        # gardait un pas de 1,67 mm, « seconde passe » sans une seule position
        # nouvelle. C est un test qui l a attrape, pas la relecture.
        # ⚠️ Plancher DEDUIT du via, jamais une constante : `0.05` etait lu en
        # millimetres alors que la production passe des nanometres — il ne
        # bornait donc RIEN. Meme famille que « calibrer sur une source voisine
        # de celle que le code lit » (revue du 2026-09-21).
        plancher = max(via_d / 10.0, 1e-9)
        if petite <= 0:
            return max(via_d / 2.0, plancher)
        return max(min(petite / 3.0, via_d / 2.0), plancher)
    plafond = max(via_d, 0.0) * 3.0
    if petite <= 0:
        return max(via_d, 1.0)
    return max(min(plafond, petite / 3.0), max(via_d, 1.0))


def _candidats_par_preference(points, relie):
    """Les points qui RELIENT d abord, les autres ensuite. Aucun n est perdu.

    ⚠️ CE PIEGE A DEJA ETE TENDU ET REFUTE. Le 2026-09-01 j avais ajoute la
    condition « ne percer que si la face opposee porte du cuivre ».
    Empiriquement mauvais :

        couture d origine (sans la condition)   1 connexion manquante
        avec la condition                       4 connexions manquantes

    Parce qu elle REFUSAIT des sites sans en chercher d autres : moins de vias
    poses, donc moins d ilots relies. Le test de l epoque a ete inverse pour
    interdire son retour, et il reste en vigueur.

    La bonne forme n est pas un filtre, c est un ORDRE. On essaie d abord les
    points qui relieront vraiment ; si aucun ne convient, on se rabat sur les
    autres — exactement le comportement d avant. La couture ne peut donc que
    s ameliorer : a pire egal, elle pose les memes vias qu aujourd hui.

    ⚠️ Un predicat qui LEVE ne doit pas eteindre la couture : on retombe sur
    l ordre d origine, jamais sur zero via.
    """
    devant, derriere = [], []
    for p in points or []:
        try:
            (devant if relie(p) else derriere).append(p)
        except Exception:
            return list(points or [])
    return devant + derriere


def _cuivre_du_net_sur(board, couche_exclue, netcode):
    """Polygones remplis de ce NET sur toutes les AUTRES couches.

    ⚠️ PARCOURIR TOUT LE BOARD, pas la seule zone courante. Notre generateur
    ecrit UNE ZONE PAR FACE — deux objets distincts, chacun a une seule couche.
    Une premiere version interrogeait `zone.GetLayerSet()` de la zone COURANTE :
    elle ne trouvait donc jamais rien, repondait toujours « pas de cuivre en
    face », et AUCUN via n etait pose.

    Mesure du 2026-09-01, `nucleo-f401` : F.Cu porte 7 ilots (11023, 2785,
    1956, 136, 115, 79, 13 mm2) et B.Cu 2 (11023, 6). Le grand plan de B.Cu
    couvre la carte entiere — chaque ilot de F.Cu a donc du cuivre en face, et
    un via par ilot suffisait. Un seul a ete pose, et le board est sorti a
    6 connexions manquantes au lieu d une.

    J avais remplace un via aveugle par un via jamais pose.
    """
    autres = []
    try:
        zones = list(board.Zones())
    except Exception:  # noqa: BLE001 — sans zones lisibles, pas de cuivre en face
        return autres
    for z in zones:
        try:
            if z.GetNetCode() != netcode:
                continue
            couches = list(z.GetLayerSet().Seq())
        except Exception:
            continue
        for c in couches:
            if c == couche_exclue:
                continue
            try:
                poly = z.GetFilledPolysList(c)
            except Exception:
                continue
            if poly.OutlineCount() > 0:
                autres.append(poly)
    return autres


def _cuivre_principal_en_face(board, couche_exclue, netcode, relies) -> list:
    """`(poly, index)` du cuivre du PLAN PRINCIPAL sur les AUTRES couches.

    ⚠️ `_cuivre_du_net_sur` rend TOUT le cuivre du net, jumeau d une paire
    orpheline compris : un via pose « au mieux » peut donc ne rejoindre que ce
    jumeau, les deux moities se porter garantes, et l amas rester coupe du
    plan. Mesure du 2026-09-21, carte-07 : l amas orphelin est une paire
    F.Cu 6,48 mm2 + B.Cu 14,97, et il porte la masse de D16. Diagnostic
    convergent de Codex, GLM et OpenCode le meme jour.

    `relies` : les `(nz, couche, index)` du composant principal, tels que
    `_ilots_relies_au_principal_du_net` les rend. Sert a ORDONNER les
    candidats, jamais a les filtrer — exiger du cuivre en face a ete mesure et
    REFUTE le 2026-09-01 (1 -> 4 connexions manquantes).
    """
    out = []
    try:
        zones = list(board.Zones())
    except Exception:  # noqa: BLE001 — sans zones lisibles, aucune preference
        return out
    for nz, z in enumerate(zones):
        try:
            if z.GetNetCode() != netcode:
                continue
            couches = list(z.GetLayerSet().Seq())
        except Exception:
            continue
        for c in couches:
            if c == couche_exclue:
                continue
            try:
                poly = z.GetFilledPolysList(c)
            except Exception:
                continue
            for i in range(poly.OutlineCount()):
                if (nz, c, i) in relies:
                    out.append((poly, i))
    return out


def _faut_coudre(ilots_sur_la_couche: int, couches_du_net: int) -> bool:
    """Faut-il poser un via dans cet ilot ?

    ⚠️ La condition d origine — `if total < 2: continue` — ecartait toute face
    d un seul tenant. Vrai pour une face PRISE SEULE : un ilot unique n a rien
    a recoudre en lui-meme. Faux des que le net vit sur PLUSIEURS couches.

    Mesure du 2026-09-01, board livre de `nucleo-f401` : F.Cu et B.Cu portent
    chacun UN seul ilot de GND, donc chacun etait ecarte, donc aucun via ne les
    reliait. Le rapport `kicad-cli` le disait mot pour mot :

        Zone [GND] on F.Cu, priority 0  <->  Zone [GND] on B.Cu, priority 0

    La couture savait joindre deux ilots d une meme face ; jamais deux faces
    entre elles.
    """
    if ilots_sur_la_couche < 1:
        return False
    return ilots_sur_la_couche >= 2 or couches_du_net >= 2


def _retirer_ilots_flottants(pcbnew, args: dict[str, str]) -> None:
    """Retire les ilots de plan qu AUCUN via ne relie, et leurs vias inutiles.

    ⚠️ A LANCER APRES la couture, jamais avant : un ilot qu on aurait pu
    coudre ne doit pas etre retire. C est le dernier recours, quand toutes les
    tentatives de liaison ont echoue.

    ⚠️ CE N EST PAS LA SUPPRESSION NATIVE DE KiCad. `ISLAND_REMOVAL_MODE_ALWAYS`
    est deja actif et retire les ilots SANS connexion ; celui qu on vise ici
    porte un via — donc KiCad le croit connecte — mais ce via n atteint aucun
    cuivre du net sur la face opposee. Mesure du 2026-09-02, `stm32-60` :
    regler le mode et recouler ne change AUCUNE connexion manquante.

    Le via borgne est retire avec l ilot : sans cela il resterait un percage
    facture qui ne relie rien, et un obstacle de plus pour le routage suivant.
    """
    board = _charger_board(pcbnew, args["pcb"])
    nets = set(json.loads(args.get("nets", "[]")))
    retires = 0
    vias_retires = 0
    relies = 0
    via_d = int(float(args.get("via_mm", "0.6")) * 1_000_000)
    ecart_trous = float(args.get("ecart_trous_mm", "0.5")) * 1_000_000
    # ⚠️ SANS CE DEGAGEMENT, la verification des couches nues serait INERTE :
    # `_poser_via_dans_pastille` la saute quand `clearance` vaut 0. Une regle
    # jamais invoquee est indistinguable d une regle absente.
    clearance = float(args.get("clearance_mm", "0.2")) * 1_000_000
    trous = _trous_perces(board)

    zones = [z for z in board.Zones()
             if not nets or str(z.GetNetname()) in nets]
    autre = {"F.Cu": "B.Cu", "B.Cu": "F.Cu"}

    for zone in zones:
        try:
            netcode = zone.GetNetCode()
        except Exception:
            continue
        vias = [t for t in board.GetTracks()
                if t.GetClass() == "PCB_VIA" and t.GetNetCode() == netcode]
        pads = [p for fp in board.GetFootprints() for p in fp.Pads()
                if p.GetNetCode() == netcode]
        for couche in list(zone.GetLayerSet().Seq()):
            try:
                poly = zone.GetFilledPolysList(couche)
            except Exception:
                continue
            nom = board.GetLayerName(couche)
            # ⚠️ De la FIN vers le DEBUT : supprimer un polygone decale les
            # indices suivants, et parcourir en avant en sauterait.
            for i in range(poly.OutlineCount() - 1, -1, -1):
                dedans = [v for v in vias if poly.Contains(v.GetPosition(), i)]
                pastilles = sum(1 for p in pads
                                if poly.Contains(p.GetPosition(), i))
                # ⚠️ « Relie » garde ici son sens LARGE (un via qui touche du
                # cuivre du net en face), a la difference de la couture. Essaye
                # le 2026-09-19 sur carte-09 avec le critere « composante du
                # plan » : les paires F/B isolees portaient une PASTILLE GND
                # cote F ; le retrait ote le jumeau B et garde l ilot a
                # pastille, isole — 2 -> 3 connexions manquantes. Retire.
                reliants = 0
                for v in dedans:
                    if _touche_le_net_en_face(board, zones, autre.get(nom),
                                              v.GetPosition()):
                        reliants += 1
                # ⚠️ Un ilot qui porte une pastille du net ne se supprime pas —
                # il se RELIE. Le retirer deconnecterait la broche. Mesure du
                # 2026-09-02, `stm32-60` : l ilot de 4,9 mm2 contient la
                # pastille GND de C4, qui surplombe le plan de B.Cu.
                if _ilot_a_relier_par_sa_pastille(reliants, pastilles):
                    for p in pads:
                        if not poly.Contains(p.GetPosition(), i):
                            continue
                        if _poser_via_dans_pastille(pcbnew, board, p, via_d,
                                                    ecart_trous, trous,
                                                    clearance):
                            relies += 1
                            break
                    continue
                if not _ilot_est_flottant(len(dedans), reliants, pastilles):
                    continue
                for v in dedans:
                    board.Remove(v)
                    vias_retires += 1
                poly.DeletePolygon(i)
                retires += 1
            try:
                zone.SetFilledPolysList(couche, poly)
            except Exception:
                pass

    pcbnew.SaveBoard(args["output"], board)
    Path(args["result"]).write_text(
        json.dumps({"retires": retires, "vias_retires": vias_retires,
                    "relies": relies}),
        encoding="utf-8")


def _poser_via_dans_pastille(pcbnew, board, pad, via_d: float,
                             ecart_trous: float, trous: list,
                             clearance: float = 0.0) -> bool:
    """Pose un via DANS la pastille, pour relier son ilot au plan d en face.

    Reutilise exactement les regles du fanout : le via ne depasse jamais la
    pastille — il herite donc de son isolement SUR SA COUCHE — le percage
    respecte le minimum de KiCad, un trou deja perce interdit le point, et le
    degagement est verifie sur les couches que la pastille NE couvre PAS.

    ⚠️ Cette derniere regle manquait. Mesure du 2026-09-02, `stm32-100` a une
    connexion du but : l operation rendait « relies: 1 » et le DRC passait de
    `1 manquante, 0 erreur` a `1 manquante, 1 ERREUR`. Le via reliait bien
    l ilot, mais posait sur la face opposee du cuivre que rien ne vouchait, et
    la garde « ne peut qu ameliorer » de la chaine le rejetait — a raison.

    La phrase « reutilise exactement les regles du fanout » etait vraie quand
    elle a ete ecrite ; le renforcement du fanout, le matin meme, l a rendue
    fausse SANS QUE RIEN NE LE SIGNALE. Une garde compare desormais les deux.
    """
    try:
        b = pad.GetBoundingBox()
        larg = min(float(b.GetRight() - b.GetLeft()),
                   float(b.GetBottom() - b.GetTop()))
        perce = float(pad.GetDrillSizeX())
    except Exception:
        return False
    d = _via_in_pad_possible(larg, via_d, perce, _via_min_fabricable(board))
    if d <= 0:
        return False
    perc = _percage_pour_via(d)
    pos = pad.GetPosition()
    if not _trou_libre(pos.x, pos.y, perc / 2, trous, ecart_trous):
        return False
    # ⚠️ LA DISPENSE S ARRETE A LA COUCHE DE LA PASTILLE — meme regle que le
    # fanout, et pour la meme raison : une pastille CMS n existe que sur une
    # face, le via traverse jusqu a l autre.
    nues = _couches_traversees_hors_pastille(
        _couches_cuivre_d_un_item(pad), _couches_cuivre_du_board(board))
    if nues and clearance > 0 and _via_gene_par(
            pos.x, pos.y, d, clearance,
            _obstacles_d_un_autre_net(board, pad.GetNetCode(), couches=nues)):
        return False
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(pos)
    via.SetWidth(int(d))
    via.SetDrill(int(perc))
    via.SetNetCode(pad.GetNetCode())
    board.Add(via)
    trous.append((float(pos.x), float(pos.y), perc / 2))
    return True


def _touche_le_net_en_face(board, zones, couche_opposee, position) -> bool:
    """Ce point touche-t-il du cuivre du net sur la face opposee ?"""
    if not couche_opposee:
        return False
    for z in zones:
        for c in list(z.GetLayerSet().Seq()):
            try:
                if board.GetLayerName(c) != couche_opposee:
                    continue
                p = z.GetFilledPolysList(c)
                if any(p.Contains(position, k) for k in range(p.OutlineCount())):
                    return True
            except Exception:
                continue
    return False


def _ilots_relies_au_principal(aires: dict, traversants, contient) -> set:
    """Ilots de la MEME composante que le plus grand, reliee par traversants.

    `aires` : {ilot: aire} pour tous les ilots du net, toutes couches ;
    `traversants` : points ou le cuivre passe d une couche a l autre (vias,
    pastilles traversantes) ; `contient(ilot, point)`.

    ⚠️ Mesure du 2026-09-19, relecture a l oeil du banc : chaque carte portait
    une rangee de 9 a 20 vias GND le long du bord haut, 116 au total. La
    couture reposait un via dans chaque ilot a CHAQUE passe, sans regarder
    s il etait deja relie ; la regle anti-doublon decalait le suivant de
    1,8 mm. Un ilot deja relie au plan n appelle aucun via de plus.

    ⚠️ « Relie » veut dire relie au PLAN, pas « un via qui atteint du cuivre
    en face ». Ce premier critere, essaye le jour meme, a laisse carte-09 a
    deux ruptures GND : deux PAIRES de petits ilots (4,8 et 5,6 mm2 ; 3,1 et
    1,7 mm2) cousues entre elles, chacun se croyant relie, aucune n atteignant
    le plan. D ou les composantes, et le plus grand ilot comme reference.

    Un predicat qui leve vaut « pas dedans » : au doute, l ilot reste a coudre.
    """
    if not aires:
        return set()
    parent = {k: k for k in aires}

    def racine(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for p in traversants:
        dedans = []
        for k in aires:
            try:
                if contient(k, p):
                    dedans.append(k)
            except Exception:  # noqa: BLE001 — au doute, on coud
                continue
        for a, b in zip(dedans, dedans[1:]):
            parent[racine(a)] = racine(b)
    principal = racine(max(aires, key=aires.get))
    return {k for k in aires if racine(k) == principal}


def _ilots_relies_au_principal_du_net(pcbnew, board, netcode) -> set:
    """`_ilots_relies_au_principal` lu sur le board : cles (n de zone, couche, i).

    Tous les ilots du net sur TOUTES ses zones — notre generateur ecrit une
    zone par face — et tous ses traversants : vias et pastilles traversantes.
    Le n de zone est son rang dans `board.Zones()`, stable dans un chargement.
    """
    aires, polys = {}, {}
    for nz, z in enumerate(board.Zones()):
        try:
            if z.GetNetCode() != netcode:
                continue
            for c in z.GetLayerSet().Seq():
                poly = z.GetFilledPolysList(c)
                for i in range(poly.OutlineCount()):
                    aires[(nz, c, i)] = abs(float(poly.Outline(i).Area()))
                    polys[(nz, c, i)] = poly
        except Exception:  # noqa: BLE001 — zone illisible : rien de relie par elle
            continue
    traversants = []
    for t in board.GetTracks():
        try:
            if t.GetClass() == "PCB_VIA" and t.GetNetCode() == netcode:
                traversants.append(t.GetPosition())
        except Exception:  # noqa: BLE001
            continue
    for fp in board.GetFootprints():
        for p in fp.Pads():
            try:
                if (p.GetNetCode() == netcode
                        and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH):
                    traversants.append(p.GetPosition())
            except Exception:  # noqa: BLE001
                continue
    return _ilots_relies_au_principal(
        aires, traversants, lambda k, pos: polys[k].Contains(pos, k[2]))


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
    ecart_trous = float(args.get("ecart_trous_mm", "0.5")) * 1_000_000
    # ⚠️ Releve UNE fois, puis tenu a jour a chaque pose. Un via pose ici doit
    # etre un obstacle pour le suivant — de cette passe comme des suivantes,
    # puisque la couture est RE-EXECUTEE tant qu elle trouve des ilots.
    trous = _trous_perces(board)

    poses = 0
    # ⚠️ Les ilots VISITES qu aucun site n a pu coudre. Sans ce compte, « 0 via
    # pose » a deux causes indistinguables — tout est relie, ou rien n a de
    # place — et `_coudre_jusqu_au_bout` s arrete en croyant avoir fini
    # (mesure du 2026-09-21 : carte-07, 10 a une manquante GND, carte-09 une
    # erreur, pendant que le journal annoncait « 1 via pose » sur 17 ilots).
    perdus: list = []
    for nz, zone in enumerate(board.Zones()):
        try:
            nom = str(zone.GetNetname())
        except Exception:
            continue
        if nets and nom not in nets:
            continue
        obstacles = _obstacles_d_un_autre_net(board, zone.GetNetCode())
        # ⚠️ Compter les COUCHES du net avant de decider : une face d un seul
        # tenant n a rien a recoudre en elle-meme, mais deux faces d un seul
        # tenant ont tout a se dire.
        couches_du_net = 0
        for _c in zone.GetLayerSet().Seq():
            try:
                if zone.GetFilledPolysList(_c).OutlineCount() > 0:
                    couches_du_net += 1
            except Exception:
                continue
        for couche in zone.GetLayerSet().Seq():
            try:
                poly = zone.GetFilledPolysList(couche)
                total = poly.OutlineCount()
            except Exception:
                continue
            # ⚠️ Le cuivre d en face, calcule UNE fois par couche : c est lui
            # qui decide si un point relie ou pas — ET si la couture a lieu.
            # ⚠️ ORDRE : il doit etre calcule AVANT `_faut_coudre`, qui s en
            # sert. Une premiere version l utilisait une ligne trop tot et
            # levait `UnboundLocalError` a CHAQUE appel — avalee par le
            # `except` de l appelant, elle rendait « couture impossible » et
            # ne cousait rien du tout. Mesure du 2026-09-01 : trois tirages de
            # `nucleo-f401`, trois plantages, zero via pose.
            # ⚠️ `relies` d ABORD : il sert a viser le PLAN PRINCIPAL en face.
            relies = _ilots_relies_au_principal_du_net(
                pcbnew, board, zone.GetNetCode())
            # ⚠️ On prefere le cuivre du PLAN PRINCIPAL, pas n importe quel
            # cuivre du net : sinon le jumeau d une paire orpheline suffit a
            # faire croire au via qu il relie (mesure du 2026-09-21, carte-07).
            # Le cuivre du net entier reste le repli — on ORDONNE, on ne filtre
            # pas (« exiger » a ete mesure et refute le 2026-09-01).
            principal_en_face = _cuivre_principal_en_face(
                board, couche, zone.GetNetCode(), relies)
            en_face = _cuivre_du_net_sur(board, couche, zone.GetNetCode())
            # Le net vit sur autant de couches que de ZONES qui le portent :
            # une par face chez nous. Compter sur la zone courante seule
            # rendait toujours 1, et ecartait le cas « deux faces ».
            couches_du_net = max(couches_du_net, 1 + (1 if en_face else 0))
            if not _faut_coudre(total, couches_du_net):
                continue  # une seule face, d un seul tenant : rien a relier
            # (`relies` est releve plus haut : les vias poses sur une couche
            # precedente de cette passe relient deja leurs ilots.)
            for i in range(total):
                b = poly.Outline(i).BBox()
                pose = False
                # ⚠️ Un ilot deja relie au PLAN n appelle aucun via : voir
                # `_ilots_relies_au_principal` (116 vias en rangee sur le banc).
                if (nz, couche, i) in relies:
                    continue
                # ⚠️ PREFERER les points qui relient VRAIMENT — sans jamais
                # les exiger. Mesure du 2026-09-02, `nucleo-f401` : deux ilots
                # (238 et 128 mm2) recoivent un via qui traverse vers du VIDE,
                # parce que la face opposee n a pas de cuivre a cet endroit.
                # Exiger ce cuivre a deja ete essaye et REFUTE (1 -> 4
                # manquantes) : la condition refusait des sites sans en
                # chercher d autres. On ORDONNE, on ne filtre pas.
                def _relie(p, _poly=poly, _i=i):
                    q = pcbnew.VECTOR2I(int(p[0]), int(p[1]))
                    cible = (principal_en_face
                             and any(pf.Contains(q, k) for pf, k in principal_en_face))
                    if not cible and not principal_en_face:
                        # Aucun principal identifie (net d un seul tenant) :
                        # on retombe sur le cuivre du net, comme avant.
                        cible = any(pf.Contains(q, k) for pf in en_face
                                    for k in range(pf.OutlineCount()))
                    return _via_relie_vraiment(_poly.Contains(q, _i), bool(cible))

                # ⚠️ Le pas se DEDUIT de l ilot. Fixe a 1,8 mm, il sautait
                # entierement les languettes de quelques mm2 — elles n etaient
                # pas refusees, elles n etaient jamais visitees.
                def _essayer(fin=False, _b=b, _relie=_relie):
                    pas_ech = _pas_d_echantillonnage(
                        _b.GetRight() - _b.GetLeft(),
                        _b.GetBottom() - _b.GetTop(), via_d, fin=fin)
                    return _candidats_par_preference(
                        list(_points_dans_boite(_b.GetLeft(), _b.GetTop(),
                                                _b.GetRight(), _b.GetBottom(),
                                                pas_ech)),
                        _relie)

                candidats = _essayer()
                # Pourquoi chaque candidat a ete refuse : sans la raison, le
                # remede se devine — et ce depot a deja paye deux fois le fait
                # de deviner sur cette couture.
                refus = {"hors_polygone": 0, "obstacle": 0, "trou_trop_pres": 0}

                def _tenter(cands, _poly=poly, _i=i, _refus=refus):
                    """Pose un via au premier site valable. UNE seule copie de
                    la regle : la passe normale et la passe fine la partagent —
                    dupliquee, elle a deja exige une edition synchrone."""
                    for x, y in cands:
                        pt = pcbnew.VECTOR2I(int(x), int(y))
                        try:
                            if not _poly.Contains(pt, _i):
                                _refus["hors_polygone"] += 1
                                continue
                        except Exception:
                            _refus["hors_polygone"] += 1
                            continue
                        if any(_distance_a_obstacle(x, y, o) < via_d / 2 + clearance
                               for o in obstacles):
                            _refus["obstacle"] += 1
                            continue
                        if not _trou_libre(x, y, perc_d / 2, trous, ecart_trous):
                            _refus["trou_trop_pres"] += 1
                            continue
                        v = pcbnew.PCB_VIA(board)
                        v.SetPosition(pt)
                        v.SetWidth(via_d)
                        v.SetDrill(perc_d)
                        v.SetNetCode(zone.GetNetCode())
                        board.Add(v)
                        trous.append((float(x), float(y), perc_d / 2))
                        return True
                    return False

                pose = _tenter(candidats)
                if not pose:
                    # SECONDE PASSE a la resolution du via avant d abandonner.
                    pose = _tenter(_essayer(fin=True))
                if pose:
                    poses += 1
                if not pose:
                    # Aucun site, meme a la resolution du via : obstacle d un
                    # autre net, ecart entre trous, ou ilot trop etroit.
                    perdus.append({
                        "net": nom,
                        "couche": int(couche),
                        "ilot": i,
                        "mm2": round(abs(float(b.GetWidth()) * float(b.GetHeight()))
                                     / 1e12, 3),
                        # ⚠️ Les points reellement EXAMINES, deux passes
                        # comprises — annoncer ceux de la premiere seule se
                        # lisait « 10 candidats, 180 refus ».
                        "candidats": sum(refus.values()),
                        "refus": refus,
                    })
                    continue

    pcbnew.SaveBoard(args["output"], board)
    Path(args["result"]).write_text(
        json.dumps({"stitched": poses, "perdus": perdus}), encoding="utf-8")

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


def _hors_du_plus_grand_amas(amas: list) -> list:
    """Pure : les pastilles qui ne sont PAS dans le plus grand amas."""
    if not amas:
        return []
    principal = max(amas, key=len)
    orphelines = []
    for a in amas:
        if a is principal:
            continue
        orphelines.extend(sorted(a))
    return orphelines


def _poser_piste(pcbnew, board, a, b, largeur: int, couche, netcode: int):
    """Un segment de cuivre, et on rend l objet pour pouvoir le DEFAIRE."""
    piste = pcbnew.PCB_TRACK(board)
    piste.SetStart(pcbnew.VECTOR2I(int(a[0]), int(a[1])))
    piste.SetEnd(pcbnew.VECTOR2I(int(b[0]), int(b[1])))
    piste.SetWidth(int(largeur))
    piste.SetLayer(couche)
    piste.SetNetCode(int(netcode))
    board.Add(piste)
    return piste


def _rerouter_un_segment(pcbnew, board, releve,
                         clearance: float) -> str:
    """Repose un segment ARRACHE, en contournant ce qui occupe desormais sa place.

    `releve` est le releve GEOMETRIQUE pris avant l arrachage
    `(x1, y1, x2, y2, largeur, couche, netcode)` — surtout pas l objet
    `pcbnew` : une fois `Remove` appele, plus rien ne garantit qu il vit.

    Rend `("ok", pistes_posees)`, ou `(raison, [])` sans rien poser — l appelant remet
    alors TOUT en place. Un reroutage a moitie fait serait pire que le defaut
    qu il repare : il echangerait une masse manquante contre une alimentation
    manquante (avertissement de GLM, 2026-09-22).

    ⚠️ Les raisons sont distinctes A DESSEIN. « impossible » a trois causes qui
    appellent trois remedes differents, et les confondre coute un diagnostic
    entier — ce depot l a deja paye avec `_recuperer_jobs_abandonnes`.

    ⚠️ LES DEUX EXTREMITES SONT EXEMPTEES du test de place libre. Elles sont
    la ou le segment ARRIVAIT deja : leur legalite est heritee du board, pas a
    redemontrer. Et l A* arrondit son depart a la grille — un point legal se
    retrouve alors a quelques centiemes de sa vraie place, souvent du mauvais
    cote d une marge que le routeur avait serree au plus juste. Sans cette
    exemption, `_chemin_de_contournement` renonce a son PREMIER point et le
    reroutage echoue toujours, quelle que soit la place disponible ailleurs.
    """
    x1, y1, x2, y2, larg, couche, net = releve
    obstacles = _obstacles_d_un_autre_net(board, int(net), couches=[couche])
    marge = float(larg) / 2.0 + clearance
    pas = max(float(larg) / 2.0, 1.0)
    bouts = {(round(x1 / pas), round(y1 / pas)),
             (round(x2 / pas), round(y2 / pas))}

    def _libre(x, y, _obs=obstacles, _m=marge, _bouts=bouts, _p=pas):
        if (round(x / _p), round(y / _p)) in _bouts:
            return True
        return all(_distance_a_obstacle(x, y, o) >= _m for o in _obs)

    directe = math.hypot(x2 - x1, y2 - y1)
    portee = min(max(directe * 4.0, float(larg) * 20.0), float(larg) * 120.0)
    chemin = _chemin_de_contournement((x1, y1), [(x2, y2)], _libre, pas, portee)
    if not chemin or len(chemin) < 2:
        # Meme face impossible : on CHANGE DE FACE plutot que de renoncer.
        detour = _detour_par_l_autre_face(pcbnew, board, releve, clearance)
        if detour:
            return "ok", detour
        return "sans_chemin", []
    # Les bonds qui TOUCHENT une extremite heritent de sa legalite : le cuivre
    # y etait deja. On verifie exactement tous les autres.
    for a, b in zip(chemin, chemin[1:]):
        touche_un_bout = ((round(a[0] / pas), round(a[1] / pas)) in bouts
                          or (round(b[0] / pas), round(b[1] / pas)) in bouts)
        if touche_un_bout:
            continue
        if not _couloir_libre(a, b, obstacles, float(larg) / 2.0, clearance):
            detour = _detour_par_l_autre_face(pcbnew, board, releve, clearance)
            if detour:
                return "ok", detour
            return "couloir_refuse", []
    # ⚠️ ON REND LES OBJETS POSES, on ne les rededuit pas. Une premiere
    # version les retrouvait par la DIFFERENCE de longueur de
    # `board.GetTracks()` avant/apres — c est supposer que pcbnew ajoute
    # toujours en fin de liste, ce qu aucun autre appelant de ce fichier ne
    # suppose. Si l hypothese cede, la remise en etat retire des pistes
    # preexistantes ou en laisse de neuves : un « tout ou rien » qui devient
    # silencieusement partiel (revue du 2026-09-22).
    posees = [_poser_piste(pcbnew, board, a, b, larg, couche, net)
              for a, b in zip(chemin, chemin[1:])]
    return "ok", posees


def _site_de_via(board, autour, netcode: int, via_d: float, perc_d: float,
                 clearance: float, trous, pas: float, rayon: float):
    """Le point legal le PLUS PROCHE de `autour` ou un via de ce net tient.

    ⚠️ Le via TRAVERSE : ses obstacles se prennent sur TOUTES les couches, pas
    sur celle de la piste. C est la faute inscrite le 2026-09-03 (« une dispense
    ne vaut pas au-dela de ce qu elle a mesure »), prise a l envers.

    Recherche par ANNEAUX croissants, donc bornee et interrompue au premier
    site : un balayage plein coute `(rayon/pas)^2` fois le nombre d obstacles,
    et ce depot a deja paye deux famines de ce genre.

    Rend `None` — jamais un point de repli — quand aucun site ne tient.
    """
    obstacles = _obstacles_d_un_autre_net(board, int(netcode))
    besoin = float(via_d) / 2.0 + clearance
    anneaux = max(1, int(rayon / pas))
    for k in range(anneaux + 1):
        r = k * pas
        n = max(1, int(2 * math.pi * r / pas)) if k else 1
        for i in range(n):
            a = 2 * math.pi * i / n
            x = autour[0] + r * math.cos(a)
            y = autour[1] + r * math.sin(a)
            if not all(_distance_a_obstacle(x, y, o) >= besoin
                       for o in obstacles):
                continue
            # ⚠️ L ECART ENTRE PERCAGES EST UNE REGLE DE FABRICATION, PAS LE
            # DIAMETRE DU TROU. Cette ligne passait `float(perc_d)` — 0,30 mm —
            # la ou les six autres poses de via du fichier passent
            # `_ECART_TROUS_MM` (0,50 mm, regle JLCPCB). Un via de detour etait
            # donc accepte a 0,30 mm bord-a-bord d un trou voisin.
            #
            # Et le defaut etait INVISIBLE : `hole_to_hole` sort en WARNING,
            # `_aggrave_le_board` ne compte que les `error`, donc le board
            # partait « 0 erreur » et se faisait refuser au percage. C est la
            # faute que ce depot traque — un echec qui rend la valeur du cas
            # normal — relevee par la revue avant fusion, jamais par un test.
            if not _trou_libre(x, y, _percage_pour_via(via_d) / 2.0, trous,
                               _ECART_TROUS_MM):
                continue
            return (x, y)
    return None


def _poser_via(pcbnew, board, point, via_d: float, perc_d: float,
               netcode: int):
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(pcbnew.VECTOR2I(int(point[0]), int(point[1])))
    via.SetWidth(int(via_d))
    via.SetDrill(int(perc_d))
    via.SetNetCode(int(netcode))
    board.Add(via)
    return via


def _chemin_sur_couche(board, depart, arrivee, netcode: int, couche,
                       larg: float, clearance: float, exempts, extra_obstacles=()):
    """Le trajet de `depart` a `arrivee` sur UNE couche, ou None.

    `exempts` : les cases de grille dont la legalite est HERITEE du board (les
    extremites d un segment arrache, le point d un via qu on vient de juger).
    Sans elles, l arrondi de grille de l A* fait renoncer des le premier point.
    """
    obstacles = _obstacles_d_un_autre_net(board, int(netcode), couches=[couche])
    # Des obstacles que le board ne porte pas encore — les vias RESERVES, qui ne
    # vivent que dans le DSN (routage prioritaire, 2026-09-25).
    obstacles = obstacles + list(extra_obstacles)
    marge = float(larg) / 2.0 + clearance
    pas = max(float(larg) / 2.0, 1.0)
    cases = {(round(x / pas), round(y / pas)) for x, y in exempts}

    def _libre(x, y, _o=obstacles, _m=marge, _c=cases, _p=pas):
        if (round(x / _p), round(y / _p)) in _c:
            return True
        return all(_distance_a_obstacle(x, y, o) >= _m for o in _o)

    directe = math.hypot(arrivee[0] - depart[0], arrivee[1] - depart[1])
    portee = min(max(directe * 4.0, float(larg) * 20.0), float(larg) * 120.0)
    chemin = _chemin_de_contournement(depart, [arrivee], _libre, pas, portee)
    if not chemin or len(chemin) < 2:
        return None
    for a, b in zip(chemin, chemin[1:]):
        if (round(a[0] / pas), round(a[1] / pas)) in cases:
            continue
        if (round(b[0] / pas), round(b[1] / pas)) in cases:
            continue
        if not _couloir_libre(a, b, obstacles, float(larg) / 2.0, clearance):
            return None
    return chemin


def _detour_par_l_autre_face(pcbnew, board, releve, clearance: float):
    """Repose un segment arrache en PASSANT PAR L AUTRE FACE, deux vias.

    ⚠️ C est le seul recours quand le raccord de masse barre le couloir sur
    TOUTE sa largeur, et c est arithmetique : mesure du 2026-09-22 sur
    `carte-10`, le couloir fait 0,862 mm, le raccord en occupe 0,65 (cuivre
    plus degagement des deux cotes) et un signal en reclame 0,65 a son tour.
    Il faudrait 1,30 mm. Aucune finesse ne rattrape les 0,44 manquants : sur la
    meme face, il n y a pas de solution, quelle que soit la recherche.

    ⚠️ Le trajet de l autre face traverse le PLAN coule. Les zones sont
    recoulees apres la reparation, et la coulee decoupe le cuivre autour de la
    piste neuve — mais cela peut creer un ilot a son tour : l appelant ne garde
    le board que s il ne l aggrave pas.

    Rend la liste des objets poses, ou None sans rien laisser derriere.
    """
    x1, y1, x2, y2, larg, couche, net = releve
    ds = board.GetDesignSettings()
    try:
        via_d = float(ds.GetCurrentViaSize())
        perc_d = float(ds.GetCurrentViaDrill())
    except Exception:
        return None
    if via_d <= 0 or perc_d <= 0:
        return None
    trous = _trous_perces(board)
    pas = max(float(larg) / 2.0, 1.0)
    directe = math.hypot(x2 - x1, y2 - y1)
    rayon = min(max(directe, float(larg) * 20.0), float(larg) * 60.0)

    autres = sorted({t.GetLayer() for t in board.GetTracks()
                     if t.GetClass() != "PCB_VIA"} - {couche})
    for couche2 in autres:
        p1 = _site_de_via(board, (x1, y1), net, via_d, perc_d, clearance,
                          trous, pas, rayon)
        p2 = _site_de_via(board, (x2, y2), net, via_d, perc_d, clearance,
                          trous, pas, rayon)
        if p1 is None or p2 is None:
            continue
        # ⚠️ MEME REGLE ENTRE LES DEUX VIAS DE LA PAIRE. `perc_d * 2.0` vaut
        # 0,60 mm entre CENTRES, soit 0,30 bord-a-bord : la moitie de ce que la
        # fabrication exige. On mesure bord-a-bord, avec la meme constante.
        rayon_perce = _percage_pour_via(via_d) / 2.0
        if (math.hypot(p1[0] - p2[0], p1[1] - p2[1])
                < 2.0 * rayon_perce + _ECART_TROUS_MM):
            continue          # deux vias trop proches : trou contre trou
        amont = _chemin_sur_couche(board, (x1, y1), p1, net, couche, larg,
                                   clearance, [(x1, y1), p1])
        aval = _chemin_sur_couche(board, p2, (x2, y2), net, couche, larg,
                                  clearance, [p2, (x2, y2)])
        travers = _chemin_sur_couche(board, p1, p2, net, couche2, larg,
                                     clearance, [p1, p2])
        if amont is None or aval is None or travers is None:
            continue
        posees = [_poser_via(pcbnew, board, p1, via_d, perc_d, net),
                  _poser_via(pcbnew, board, p2, via_d, perc_d, net)]
        for chemin, c in ((amont, couche), (travers, couche2), (aval, couche)):
            for a, b in zip(chemin, chemin[1:]):
                posees.append(_poser_piste(pcbnew, board, a, b, larg, c, net))
        return posees
    return None


def _degager_le_couloir(pcbnew, board, depart, arrivee, couche, netcode: int,
                        largeur: int, clearance: float, echecs: dict) -> bool:
    """Arrache le peu qui enferme un amas de masse, relie, puis repose le reste.

    ⚠️ Mesure du 2026-09-22, `carte-10`, sur le board qui porte VRAIMENT la
    connexion manquante : l amas orphelin est une PAIRE de 1,30 et 0,99 mm2,
    aucun de ses points n a le plan principal en vis-a-vis, la couture refuse
    la TOTALITE de ses 23 et 18 sites (un via ne tient pas dans un millimetre
    carre) et l A* rend `sans_chemin`. Mais le plan principal n est qu a
    0,862 mm, et **UN SEUL segment** coupe le couloir de chaque face.

    On renverse donc le probleme : plutot que de chercher un passage A TRAVERS
    l obstacle, on DEPLACE l obstacle. Proposition de Codex, bornee par
    `_couloir_degageable` — jamais une recherche ouverte.

    Tout ou rien : si un seul des segments arraches ne peut pas etre repose,
    on remet l etat initial et on rend False.
    """
    obstacles = _obstacles_d_un_autre_net(board, netcode, couches=[couche])
    a_arracher = _couloir_degageable(depart, arrivee, obstacles,
                                     float(largeur) / 2.0, clearance)
    if a_arracher is None:
        echecs["sans_degagement"] = echecs.get("sans_degagement", 0) + 1
        return False

    # Retrouver les PISTES derriere les obstacles designes. On compare la
    # GEOMETRIE : `_obstacles_d_un_autre_net` ne rend pas l identite des items.
    vises = {obstacles[k] for k in a_arracher}
    releves, objets = [], []
    for t in list(board.GetTracks()):
        try:
            if int(t.GetNetCode()) == int(netcode) or t.GetClass() == "PCB_VIA":
                continue
            if t.GetLayer() != couche:
                continue
            d, f = t.GetStart(), t.GetEnd()
            forme = ("segment", float(d.x), float(d.y), float(f.x), float(f.y),
                     float(t.GetWidth()))
            if forme in vises:
                releves.append((float(d.x), float(d.y), float(f.x), float(f.y),
                                int(t.GetWidth()), t.GetLayer(),
                                int(t.GetNetCode())))
                objets.append(t)
        except Exception:
            continue
    if len(releves) != len(a_arracher):
        # On n a pas su remonter des formes aux pistes : ne rien casser.
        echecs["sans_degagement"] = echecs.get("sans_degagement", 0) + 1
        return False

    for t in objets:
        board.Remove(t)

    posees = []
    try:
        restant = _obstacles_d_un_autre_net(board, netcode, couches=[couche])
        if not _couloir_libre(depart, arrivee, restant,
                              float(largeur) / 2.0, clearance):
            raise RuntimeError("couloir toujours ferme apres arrachage")
        posees.append(_poser_piste(pcbnew, board, depart, arrivee,
                                   largeur, couche, netcode))
        for releve in releves:
            raison, neuves = _rerouter_un_segment(pcbnew, board, releve,
                                                  clearance)
            if raison != "ok":
                raise RuntimeError("reroutage : %s" % raison)
            # Les pistes ajoutees par le reroutage doivent pouvoir etre
            # defaites aussi : elles sont RENDUES, jamais rededuites.
            posees.extend(neuves)
    except Exception as exc:
        for p in posees:
            try:
                board.Remove(p)
            except Exception:
                pass
        for x1, y1, x2, y2, larg, c, net in releves:
            _poser_piste(pcbnew, board, (x1, y1), (x2, y2), larg, c, net)
        echecs["reroutage_impossible"] = echecs.get("reroutage_impossible", 0) + 1
        # La RAISON, pas seulement le compte : trois causes appellent trois
        # remedes, et « impossible » seul n en designe aucun.
        motifs = echecs.setdefault("motifs_reroutage", {})
        motifs[str(exc)] = motifs.get(str(exc), 0) + 1
        return False
    return True


def _relier_les_amas_orphelins(pcbnew, args: dict[str, str]) -> None:
    """Raccorde par une COURTE PISTE tout amas de plan orphelin PORTANT une pastille.

    ⚠️ LES JUMEAUX SE PORTENT GARANTS L UN DE L AUTRE — diagnostic convergent de
    Codex, GLM et OpenCode le 2026-09-21, verifie sur carte-07 : l amas orphelin
    est une PAIRE (F.Cu 6,48 mm2 + B.Cu 14,97), cousue par un via qui ne relie
    que les deux moities. `_stitch_zones` compte ce via comme un succes (un site
    a ete trouve) et `_retirer_ilots_flottants` voit ce meme via « toucher du
    cuivre du net en face » — donc ni couture supplementaire, ni retrait.

    ⚠️ RETIRER EST INTERDIT quand l amas porte une pastille, et c est DEJA
    MESURE : le 2026-09-19, juger par composante a fait passer carte-09 de 2 a
    3 connexions manquantes. Ici l amas porte la masse de D16 ; l oter
    deconnecterait la LED. On RELIE.

    ⚠️ Ce n est PAS l « amorce sur la face opposee » refutee le 2026-09-02 :
    celle-ci se posait AVANT le routage et etait protegee dans le DSN, ce qui
    bouchait le routeur (2798 s contre 901). On repare ici un board FINI, et
    rien n est protege.

    La piste part de la PASTILLE de l amas, vise le plan principal sur la MEME
    couche, et n est posee que si le couloir est libre du cuivre des autres
    nets (`_couloir_libre`, degagement exact).

    ⚠️ « Aucun retrait, aucun via » — ce que cette docstring promettait jusqu au
    2026-09-22 — N EST PLUS VRAI. Quand l A* echoue, l amas est ENCERCLE, et
    `_degager_le_couloir` arrache alors le peu de segments qui le ferment,
    pose le raccord, puis les repose ailleurs. Une docstring qui promet de ne
    rien toucher est exactement le genre de phrase que ce depot a deja paye
    (voir `_poser_via_dans_pastille`, 2026-09-03).
    """
    board = _charger_board(pcbnew, args["pcb"])
    nets = set(json.loads(args.get("nets", "[]")))
    largeur = int(float(args.get("largeur_mm", "0.25")) * 1_000_000)
    clearance = float(args.get("clearance_mm", "0.2")) * 1_000_000
    relies, examines = 0, 0
    # Pourquoi un amas n est pas raccorde : « aucun raccorde » ne doit pas
    # avoir trois causes indistinguables.
    echecs = {"sans_pastille": 0, "sans_depart": 0, "sans_cible": 0,
              "sans_chemin": 0, "sans_degagement": 0,
              "reroutage_impossible": 0}
    # Combien d amas n ont ete relies qu en DEPLACANT ce qui les enfermait : un
    # arrachage n est pas un raccord ordinaire, il doit se voir dans le rapport.
    degages = 0

    # ⚠️ ON JUGE SUR TOUT LE NET, PAS ZONE PAR ZONE. Notre generateur ecrit UNE
    # ZONE PAR FACE : juger une zone seule fait passer pour orphelin tout ilot
    # de F.Cu qui rejoint le plan par B.Cu. Mesure du 2026-09-22, carte-10 :
    # 21 « amas orphelins » annonces zone par zone, **UN SEUL** en verite — et
    # les vingt autres recevaient du cuivre pour rien. `_stitch_zones` jugeait
    # deja sur le net entier (`_ilots_relies_au_principal_du_net`) ; les deux
    # jumelles ne disaient pas la meme chose, et c est la plus permissive qui
    # posait le cuivre.
    codes_de_plan = {}
    for zone in board.Zones():
        try:
            netcode, nom = zone.GetNetCode(), str(zone.GetNetname())
        except Exception:
            continue
        if nets and nom not in nets:
            continue
        codes_de_plan.setdefault(netcode, []).append(zone)

    for netcode, zones_du_net in codes_de_plan.items():
        ilots = []                       # (couche, poly, index)
        for zone in zones_du_net:
            for c in list(zone.GetLayerSet().Seq()):
                try:
                    poly = zone.GetFilledPolysList(c)
                except Exception:
                    continue
                ilots.extend((c, poly, i) for i in range(poly.OutlineCount()))
        if len(ilots) < 2:
            continue
        aires, contient = {}, {}
        for k, (c, poly, i) in enumerate(ilots):
            b = poly.Outline(i).BBox()
            aires[k] = abs(float(b.GetWidth())) * abs(float(b.GetHeight()))
            contient[k] = (poly, i)
        traversants = [t.GetPosition() for t in board.GetTracks()
                       if t.GetClass() == "PCB_VIA" and t.GetNetCode() == netcode]
        pads = [p for fp in board.GetFootprints() for p in fp.Pads()
                if p.GetNetCode() == netcode]
        traversants += [p.GetPosition() for p in pads
                        if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]

        def _dedans(k, pt):
            poly, i = contient[k]
            try:
                return poly.Contains(pt, i)
            except Exception:
                return False

        relies_au_principal = _ilots_relies_au_principal(aires, traversants, _dedans)
        orphelins = [k for k in aires if k not in relies_au_principal]
        if not orphelins:
            continue
        # Les orphelins se regroupent par amas : un seul raccord par amas suffit.
        parent = {k: k for k in orphelins}

        def _racine(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for pt in traversants:
            touches = [k for k in orphelins if _dedans(k, pt)]
            for k in touches[1:]:
                parent[_racine(k)] = _racine(touches[0])
        amas = {}
        for k in orphelins:
            amas.setdefault(_racine(k), []).append(k)

        for membres in amas.values():
            examines += 1
            if not any(_dedans(k, p.GetPosition()) for k in membres for p in pads):
                echecs["sans_pastille"] += 1
                continue          # sans pastille : ce n est pas a nous de trancher
            # Obstacles TOUTES COUCHES pour l echantillonnage des ancres et
            # des cibles, qui precede le choix de la couche. Le TRAJET, lui,
            # est juge sur sa seule couche — voir `obstacles_couche` plus bas.
            obstacles = _obstacles_d_un_autre_net(board, netcode)
            marge = largeur / 2.0 + clearance
            pas = max(largeur / 2.0, 1.0)

            def _libre(x, y, _obs=obstacles, _m=marge):
                return all(_distance_a_obstacle(x, y, o) >= _m for o in _obs)

            # ⚠️ ON PART DE LA PASTILLE, PAS DU BORD DE L ILOT. Mesure du
            # 2026-09-21 : un bord d ilot est EXACTEMENT a la distance de
            # degagement de la piste qui l a coupe — il n y a donc jamais la
            # place d y poser une piste, et l A* renoncait a son premier point
            # (« 5 amas vus, AUCUN raccorde »). Avis de GLM, le plus juste des
            # trois : le sujet est la CONNECTIVITE DE LA PASTILLE, pas le
            # cuivre de l ilot.
            meilleur = None       # (distance, couche, depart, arrivee)
            n_ancres = n_cibles = 0
            # ⚠️ TOUTES les cibles de la couche, pas seulement la plus proche.
            # `_chemin_de_contournement` accepte une LISTE de buts depuis
            # toujours et on ne lui en donnait qu UN — le point du plan le plus
            # proche. Mesure du 2026-09-22, carte-10 : ce point-la est de
            # l autre cote de la bande que le raccord occupe, et le contournement
            # renoncait alors que d autres points du MEME plan etaient
            # atteignables en passant de l autre cote de l ilot. Viser le plan,
            # pas un point du plan.
            cibles_par_couche: dict = {}
            for k in membres:
                couche, poly, i = ilots[k]
                ancres = [(float(p.GetPosition().x), float(p.GetPosition().y))
                          for p in pads if _dedans(k, p.GetPosition())]
                b = poly.Outline(i).BBox()
                if not ancres:
                    ancres = [(x, y) for x, y in _points_dans_boite(
                        b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom(), pas)
                        if poly.Contains(pcbnew.VECTOR2I(int(x), int(y)), i)
                        and _libre(x, y)]
                n_ancres += len(ancres)
                for j in relies_au_principal:
                    c2, poly2, i2 = ilots[j]
                    if c2 != couche:
                        continue
                    b2 = poly2.Outline(i2).BBox()
                    cibles = [(x, y) for x, y in _points_dans_boite(
                        b2.GetLeft(), b2.GetTop(), b2.GetRight(), b2.GetBottom(), pas * 4)
                        if poly2.Contains(pcbnew.VECTOR2I(int(x), int(y)), i2)
                        and _libre(x, y)]
                    n_cibles += len(cibles)
                    cibles_par_couche.setdefault(couche, []).extend(cibles)
                    for a in ancres:
                        for c in cibles:
                            d = math.hypot(a[0] - c[0], a[1] - c[1])
                            if meilleur is None or d < meilleur[0]:
                                meilleur = (d, couche, a, c)
            if meilleur is None:
                echecs["sans_depart" if not n_ancres else "sans_cible"] += 1
                continue
            _d, couche, depart, arrivee = meilleur
            buts = _buts_bornes(cibles_par_couche.get(couche), depart, arrivee)
            # ⚠️ LE TRAJET NE VIT QUE SUR SA COUCHE. L A* prenait ses obstacles
            # sur TOUTES les couches alors que l arrachage, lui, ne regarde que
            # celle du raccord : du cuivre de la face OPPOSEE faisait donc
            # echouer l A* et ouvrait le chemin DESTRUCTIF sur une face qui
            # etait libre. Le raccord ne pose aucun via — seul un via traverse.
            # Lecon du 2026-09-14 (« NEVER prendre les obstacles d un TRAJET
            # sur toutes les couches »), que la revue a retrouvee ici.
            obstacles_couche = _obstacles_d_un_autre_net(board, netcode,
                                                         couches=[couche])

            def _libre_couche(x, y, _obs=obstacles_couche, _m=marge):
                return all(_distance_a_obstacle(x, y, o) >= _m for o in _obs)

            # ⚠️ PAS DE LIGNE DROITE — mesuree et REFUTEE le 2026-09-21 : un
            # ilot est isole PAR une piste, toute droite la retraverse
            # (« 5 amas vus, AUCUN raccorde »). On contourne son BOUT.
            # Portee bornee : trois fois la distance directe, jamais la carte
            # entiere — un raccord qui traverse le board n en est pas un.
            # Budget DEDUIT : quatre fois la distance directe, avec un
            # plancher de vingt largeurs de piste. Mesure du 2026-09-21 : un
            # budget quatre fois plus large ne change RIEN sur carte-07 — ses
            # ilots sont encercles, pas mal cherches. On ne paie donc pas une
            # recherche qui ne rapporte rien.
            # ⚠️ Plafond ABSOLU en plus du proportionnel : `_d` n est borne
            # par rien, et un amas lointain ferait exploser la recherche.
            portee = min(max(_d * 4.0, largeur * 20.0), largeur * 120.0)
            chemin = _chemin_de_contournement(depart, buts, _libre_couche,
                                              pas, portee)
            # ⚠️ LE PREMIER BOND HERITE DE LA PASTILLE. L A* arrondit son
            # depart a la grille : un point legal — le centre de la pastille —
            # se retrouve a quelques centiemes de sa vraie place, souvent du
            # mauvais cote d une marge que le routeur avait serree au plus
            # juste. Le cuivre EST deja la, sa legalite est heritee du board.
            # La meme regle vit dans `_rerouter_un_segment` ; les deux endroits
            # qui en ont structurellement besoin l appliquent (revue du
            # 2026-09-22 : elle n etait ecrite que dans un seul).
            depart_case = (round(depart[0] / pas), round(depart[1] / pas))

            def _bond_verifiable(a, b, _c=depart_case, _p=pas):
                return (round(a[0] / _p), round(a[1] / _p)) != _c

            if chemin and len(chemin) >= 2 and all(
                    _couloir_libre(a, b, obstacles_couche, largeur / 2.0,
                                   clearance)
                    for a, b in zip(chemin, chemin[1:])
                    if _bond_verifiable(a, b)):
                # L A* juge des POINTS de grille ; le segment entre deux points
                # peut fraiser un obstacle. Verification exacte avant la pose.
                for a, b in zip(chemin, chemin[1:]):
                    _poser_piste(pcbnew, board, a, b, largeur, couche, netcode)
                relies += 1
                continue
            # ⚠️ L A* a echoue : l amas est ENCERCLE, pas mal cherche (mesure du
            # 2026-09-21, budget quadruple sans effet). On ne cherche donc plus
            # un passage A TRAVERS l obstacle — on DEPLACE l obstacle, quand il
            # ne tient qu a quelques segments.
            # ⚠️ L ECHEC N EST COMPTE QU APRES le degagement. Une premiere
            # version incrementait `sans_chemin` avant de le tenter : un amas
            # relie par arrachage figurait alors a la fois dans `relies` et
            # dans les echecs, et `examines` ne retombait plus sur ses pattes.
            # Un rapport qui se contredit ne vaut pas mieux qu un rapport muet.
            if _degager_le_couloir(pcbnew, board, depart, arrivee, couche,
                                   netcode, largeur, clearance, echecs):
                relies += 1
                degages += 1
                continue
            # ⚠️ NE PAS COMPTER DEUX FOIS. `_degager_le_couloir` a DEJA
            # incremente `sans_degagement` ou `reroutage_impossible` sur son
            # propre echec ; y ajouter `sans_chemin` faisait compter chaque
            # amas perdu deux fois, et `examines` ne retombait plus sur ses
            # pattes. Un rapport qui se contredit ne vaut pas mieux qu un
            # rapport muet — releve par la revue avant fusion.
            if not any(echecs.get(cle) for cle in
                       ("sans_degagement", "reroutage_impossible")):
                echecs["sans_chemin"] += 1

    pcbnew.SaveBoard(args["output"], board)
    Path(args["result"]).write_text(
        json.dumps({"relies": relies, "amas_orphelins": examines,
                    "degages": degages, "echecs": echecs}), encoding="utf-8")


def _pads_hors_cluster_principal(pcbnew, args: dict[str, str]) -> None:
    """Les pastilles d un net de plan qui ne sont pas reliees a son amas principal.

    ⚠️ Le DRC decrit une coupure par ses deux items les plus PROCHES — deux
    zones, deux troncons — et ne nomme la pastille que par hasard. Mesure du
    2026-09-14, carte-10 : « Zone [GND] on F.Cu <-> Zone [GND] on B.Cu » pour
    U1.8, dont le via tombait dans un ilot de B.Cu de quelques mm2 coupe du
    plan. Ici c est la CONNECTIVITE reelle qui designe l orpheline : on coule
    les zones, on demande a pcbnew les pastilles reliees a chaque pastille du
    net, et tout amas qui n est pas le plus grand est orphelin.
    """
    board = _charger_board(pcbnew, args["pcb"])
    nets = [n for n in json.loads(args.get("nets", "[]")) if n]
    try:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    except Exception:
        pass  # sans coulee, la connectivite ignore les plans : on mesure quand meme
    if not board.BuildConnectivity():
        raise RuntimeError("pcbnew failed to build board connectivity")
    connectivity = board.GetConnectivity()
    connectivity.RecalculateRatsnest()
    resultat: list = []
    for nom in nets:
        code = board.GetNetcodeFromNetname(nom)
        if code <= 0:
            continue
        # ⚠️ La reference vient de l EMPREINTE parcourue : `pad.GetParent()`
        # rend un `BOARD_ITEM_CONTAINER` sans `GetReference` (mesure KiCad 10).
        pads = []
        cle = {}
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if int(p.GetNetCode()) != code:
                    continue
                pads.append(p)
                cle[str(p.m_Uuid.AsString())] = (str(fp.GetReference()), str(p.GetPadName()))
        vus: set = set()
        amas: list = []
        for p in pads:
            u = str(p.m_Uuid.AsString())
            if u in vus:
                continue
            relies = {str(q.m_Uuid.AsString()) for q in _connected_pads(connectivity, p, pcbnew)
                      if int(q.GetNetCode()) == code}
            relies.add(u)
            vus |= relies
            amas.append({cle[v] for v in relies if v in cle})
        resultat.extend(_hors_du_plus_grand_amas(amas))
    Path(args["result"]).write_text(
        json.dumps({"pads": [[r, p] for r, p in resultat]}), encoding="utf-8")


def _pastille_par_nom(board, ref, nom):
    fp = board.FindFootprintByReference(str(ref))
    if fp is None:
        return None
    return next((p for p in fp.Pads() if str(p.GetPadName()) == str(nom)), None)


def _relier_liaisons(pcbnew, args: dict[str, str]) -> None:
    """ROUTAGE PRIORITAIRE (D-2026-09-25-a) : relie les liaisons critiques par
    des pistes courtes, sur UNE face, sans via, AVANT le routage general.

    `liaisons` : [{"a": [ref, pad], "b": [ref, pad], "largeur_mm": ..}], dans
    l ordre de pose (quartz, charges, decouplages) : chaque piste posee devient
    un obstacle pour les suivantes.

    ⚠️ Jamais un court-circuit : les deux pastilles doivent porter le MEME net,
    sinon la liaison est renoncee. ⚠️ Jamais forcee : sans chemin degage, on
    renonce — le routeur general la reliera. ⚠️ Les vias RESERVES, qui ne vivent
    que dans le DSN, sont des obstacles, sauf ceux des deux pastilles reliees.
    """
    board = _charger_board(pcbnew, args["pcb"])
    liaisons = json.loads(args["liaisons"])
    clearance = float(args.get("clearance_mm", "0.2")) * 1_000_000
    via_r = float(args.get("via_mm", "0.6")) * 1_000_000 / 2.0
    reserves = json.loads(args.get("vias_reserves", "[]"))
    poses, renonces, reliees, raisons = 0, 0, [], {}

    def _renoncer(raison):
        raisons[raison] = raisons.get(raison, 0) + 1

    for liaison in liaisons:
        pa = _pastille_par_nom(board, *liaison["a"])
        pb = _pastille_par_nom(board, *liaison["b"])
        if pa is None or pb is None:
            renonces += 1
            _renoncer("pastille_introuvable")
            continue
        netcode = int(pa.GetNetCode())
        if netcode <= 0 or netcode != int(pb.GetNetCode()):
            renonces += 1
            _renoncer("nets_differents")
            continue
        couche = next((c for c in (pcbnew.F_Cu, pcbnew.B_Cu)
                       if pa.IsOnLayer(c) and pb.IsOnLayer(c)), None)
        if couche is None:
            renonces += 1
            _renoncer("pas_de_face_commune")
            continue
        extremites = {tuple(liaison["a"]), tuple(liaison["b"])}
        extra = [(float(v["x"]) - via_r, float(v["y"]) - via_r,
                  float(v["x"]) + via_r, float(v["y"]) + via_r)
                 for v in reserves if (str(v.get("ref")), str(v.get("pad"))) not in
                 {(str(r), str(n)) for r, n in extremites}]
        a = (float(pa.GetPosition().x), float(pa.GetPosition().y))
        b = (float(pb.GetPosition().x), float(pb.GetPosition().y))
        larg = float(liaison.get("largeur_mm", 0.25)) * 1_000_000
        chemin = _chemin_sur_couche(board, a, b, netcode, couche, larg, clearance,
                                    exempts=[a, b], extra_obstacles=extra)
        if not chemin:
            renonces += 1
            _renoncer("aucun_chemin_degage")
            continue
        for p1, p2 in zip(chemin, chemin[1:]):
            _poser_piste(pcbnew, board, p1, p2, int(larg), couche, netcode)
        poses += 1
        reliees.append([list(liaison["a"]), list(liaison["b"])])

    pcbnew.SaveBoard(args["output"], board)
    Path(args["result"]).write_text(json.dumps(
        {"poses": poses, "renonces": renonces, "reliees": reliees, "raisons": raisons}),
        encoding="utf-8")


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
    elif operation == "retirer_ilots_flottants":
        _retirer_ilots_flottants(pcbnew, args)
    elif operation == "relier_amas":
        _relier_les_amas_orphelins(pcbnew, args)
    elif operation == "plan_escape":
        _plan_escape(pcbnew, args)
    elif operation == "fill_zones":
        _fill_zones(pcbnew, args)
    elif operation == "escape_pads":
        _escape_pads(pcbnew, args)
    elif operation == "measure_connectivity":
        _measure_connectivity(pcbnew, args)
    elif operation == "pads_hors_cluster_principal":
        _pads_hors_cluster_principal(pcbnew, args)
    elif operation == "relier_liaisons":
        _relier_liaisons(pcbnew, args)
    else:
        raise ValueError(f"unsupported operation: {operation!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

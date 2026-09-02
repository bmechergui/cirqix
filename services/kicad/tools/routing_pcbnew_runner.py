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
                            marge_piste=None) -> bool:
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
    return not any(_distance_a_obstacle(x1, y1, o) < marge for o in obstacles)


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
                if any(_distance_a_obstacle(x1, y1, o) < marge for o in obstacles):
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


def _via_in_pad_possible(largeur_pad: float, via_nominal: float,
                         percage_pad: float) -> float:
    """Diametre du via a poser DANS la pastille. 0 si aucun ne convient.

    ⚠️ UNE PASTILLE DEJA PERCEE LE REFUSE TOUJOURS. Un via dans une pastille
    traversante est un trou dans un trou — meme faute que les vias superposes
    de la couture, corrigee le meme jour. Et il serait de toute facon inutile :
    une pastille traversante relie deja toutes les couches.
    """
    if percage_pad > 0:
        return 0.0
    d = _diametre_via_in_pad(largeur_pad, via_nominal)
    # ⚠️ Si le PERCAGE minimal ne tient pas dans la pastille, poser le via
    # ferait deborder le trou du cuivre : on renonce plutot que de livrer un
    # board que le DRC refusera. Mesure du 2026-09-02 : une pastille de
    # 0,56 mm accepte tout juste 0,30 mm de percage ; en deca, non.
    if d > 0 and _percage_pour_via(d) > largeur_pad:
        return 0.0
    return d


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

        obstacles = _obstacles_d_un_autre_net(board, pad.GetNetCode())
        b = pad.GetBoundingBox()
        propre = (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())
        portee, pas = _portee_d_echappement(fp, via_d)
        # ⚠️ REJOUER AVANT DE RECHERCHER. La position reservee a ete calculee
        # sur le board PLACE, ou le couloir d echappement etait libre ; la
        # recherche, elle, s execute sur le board ROUTE, ou les pistes de
        # signal l ont referme. Chercher a nouveau, c est jeter la seule
        # mesure faite au bon moment.
        sortie = None
        if reserve is not None and _sortie_reservee_valide(
                pos.x, pos.y, reserve[0], reserve[1], obstacles, marge,
                propre, marge_piste):
            sortie = reserve
            reprises += 1
        if sortie is None and not sans_direction:
            sortie = _choisir_sortie(
                pos.x, pos.y, dx, dy, distance, obstacles, marge, propre,
                marge_piste, portee, pas
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
            d = _via_in_pad_possible(larg, via_d, perce)
            perc = _percage_pour_via(d)
            # ⚠️ Un via qui TIENT dans la pastille herite de SON isolement :
            # exiger un degagement autour de lui reviendrait a demander deux
            # fois la meme chose, et refusait les trois pastilles orphelines
            # du banc alors qu elles surplombaient le plan de B.Cu.
            # Le TROU, lui, reste verifie — un percage est physique.
            gene = (not _via_in_pad_dispense_de_clearance(d, larg)
                    and _via_gene_par(pos.x, pos.y, d, clearance, obstacles))
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
        if not _trou_libre(vx, vy, perc_d / 2, trous, ecart_trous):
            renonces += 1
            continue

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
        trous.append((float(vx), float(vy), perc_d / 2))
        poses += 1

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
                    "reprises": reprises, "vises": vises}), encoding="utf-8"
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
                           via_d: float) -> float:
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
    petite = min(abs(largeur), abs(hauteur))
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
    for z in board.Zones():
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
    d = _via_in_pad_possible(larg, via_d, perce)
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
    for zone in board.Zones():
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
            en_face = _cuivre_du_net_sur(board, couche, zone.GetNetCode())
            # Le net vit sur autant de couches que de ZONES qui le portent :
            # une par face chez nous. Compter sur la zone courante seule
            # rendait toujours 1, et ecartait le cas « deux faces ».
            couches_du_net = max(couches_du_net, 1 + (1 if en_face else 0))
            if not _faut_coudre(total, couches_du_net):
                continue  # une seule face, d un seul tenant : rien a relier
            for i in range(total):
                b = poly.Outline(i).BBox()
                pose = False
                # ⚠️ PREFERER les points qui relient VRAIMENT — sans jamais
                # les exiger. Mesure du 2026-09-02, `nucleo-f401` : deux ilots
                # (238 et 128 mm2) recoivent un via qui traverse vers du VIDE,
                # parce que la face opposee n a pas de cuivre a cet endroit.
                # Exiger ce cuivre a deja ete essaye et REFUTE (1 -> 4
                # manquantes) : la condition refusait des sites sans en
                # chercher d autres. On ORDONNE, on ne filtre pas.
                def _relie(p, _poly=poly, _i=i):
                    q = pcbnew.VECTOR2I(int(p[0]), int(p[1]))
                    return _via_relie_vraiment(
                        _poly.Contains(q, _i),
                        any(pf.Contains(q, k) for pf in en_face
                            for k in range(pf.OutlineCount())))

                # ⚠️ Le pas se DEDUIT de l ilot. Fixe a 1,8 mm, il sautait
                # entierement les languettes de quelques mm2 — elles n etaient
                # pas refusees, elles n etaient jamais visitees.
                pas_ech = _pas_d_echantillonnage(
                    b.GetRight() - b.GetLeft(), b.GetBottom() - b.GetTop(),
                    via_d)
                candidats = _candidats_par_preference(
                    list(_points_dans_boite(b.GetLeft(), b.GetTop(),
                                            b.GetRight(), b.GetBottom(),
                                            pas_ech)),
                    _relie)
                for x, y in candidats:
                    pt = pcbnew.VECTOR2I(int(x), int(y))
                    try:
                        if not poly.Contains(pt, i):
                            continue
                    except Exception:
                        continue
                    if any(_distance_a_obstacle(x, y, o) < via_d / 2 + clearance
                           for o in obstacles):
                        continue
                    # ⚠️ Le CUIVRE du meme net ne gene pas ; le TROU, si. Sans
                    # ce refus, chaque passe retrouvait le meme ilot, le meme
                    # meilleur point, et repercait au meme endroit — x5 vias
                    # empiles, 116 `holes_co_located` sur `nucleo-f401`.
                    if not _trou_libre(x, y, perc_d / 2, trous, ecart_trous):
                        continue
                    # ⚠️ CONDITION RETIREE LE 2026-09-01, PAR LA MESURE. J avais
                    # ajoute « ne percer que si la face opposee porte du cuivre
                    # a cet endroit » — logiquement seduisant, un via vers du
                    # vide ne reliant rien. Empiriquement MAUVAIS :
                    #
                    #   couture d origine (sans la condition)  1 manquante
                    #   avec la condition                      4 manquantes
                    #
                    # Elle refuse des sites que la couture d origine acceptait,
                    # et le board livre est moins bon. Un via traversant relie
                    # AUSSI les couches internes ; juger sa valeur sur la seule
                    # face opposee etait une vue de l esprit.
                    #
                    # `_via_relie_vraiment` et `_cuivre_du_net_sur` restent
                    # disponibles et testes : c est la CONDITION qui est
                    # refutee, pas le moyen de la reposer un jour avec une
                    # mesure a l appui.
                    via = pcbnew.PCB_VIA(board)
                    via.SetPosition(pt)
                    via.SetWidth(via_d)
                    via.SetDrill(perc_d)
                    via.SetNetCode(zone.GetNetCode())
                    board.Add(via)
                    trous.append((float(x), float(y), perc_d / 2))
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
    elif operation == "retirer_ilots_flottants":
        _retirer_ilots_flottants(pcbnew, args)
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

"""Occupation de la surface — D-2026-09-13-c (validée, option C).

## Le reproche

Carte v2 du projet « Thermometre I2C TMP102 (driver) », 9 composants,
40 × 35 mm : les composants occupent y = 5 à 22,5 mm — **la moitié basse est
vide**. Sérigraphie propre, 100 % routé, 0 erreur : rien de faux, mais c'est
la première chose qu'un relecteur voit.

## La cause

Le générateur pose les empreintes sur une grille depuis le coin (5, 5) et le
connecteur J1 est le premier de la liste : il finit dans le coin haut-gauche,
ancré (`fixed_refs`), et le génétique groupe tout le reste autour de lui.
Rien ne vise la surface demandée.

## Les deux leviers, dans l'ordre

- **B — `ancrer_connecteurs_au_bord`**, AVANT les tirages : chaque
  connecteur (J*, P*) va au BORD LE PLUS PROCHE de sa position, corps à
  `marge` du bord, et ceux qui partagent un bord y sont répartis
  régulièrement, centrés. Le génétique s'équilibre autour d'eux.

  ⚠️ La première version envoyait TOUT au bord gauche (puis droit) : mesuré le
  2026-09-13 sur le banc, le centrage s'améliorait mais le découplage se
  dégradait sur les cartes denses (carte-08 2,6 → 4,1 mm, carte-09 3,2 → 5,0,
  carte-10 4,1 → 5,4) — carte-10 avait cinq connecteurs bien répartis en bas
  qu'on empilait en colonne à droite. On corrige le CAS (le coin de la
  grille), on ne défait pas ce qui était bon.
- **A — `ajuster_contour_au_placement`**, APRÈS le placement retenu : le
  contour `Edge.Cuts` est resserré sur la boîte des courtyards + marge —
  SEULEMENT quand la taille n'était pas imposée par la description (drapeau
  `auto_size_board`, posé par le client). Une carte demandée « 40 × 30 » garde
  ses 40 × 30.

⚠️ Repères : `fp.position` est relatif à `board_origin`, `Edge.Cuts` est en
coordonnées de feuille. Confondre les deux a déjà envoyé des contours à l'autre
bout de la page dans ce dépôt (voir `_redimensionner_contour`).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Marge entre le corps d'un connecteur et le bord, et entre les courtyards et
# le nouveau contour. 3 mm : assez pour le masque, la sérigraphie et le
# fraisage ; JLCPCB demande 0,3 mm au minimum.
MARGE_BORD_MM = 3.0


def _connecteurs(pcb: Any) -> list[Any]:
    return [fp for fp in pcb.footprints
            if fp.reference and fp.reference[0] in ("J", "P")]


def _contour_repere_board(pcb: Any) -> Optional[tuple[float, float, float, float]]:
    """(x0, y0, x1, y1) du contour Edge.Cuts, ramené au repère des positions."""
    ox, oy = pcb.board_origin
    xs: list[float] = []
    ys: list[float] = []
    for attr in ("graphic_items", "graphics", "lines"):
        for item in getattr(pcb, attr, None) or []:
            if getattr(item, "layer", None) != "Edge.Cuts":
                continue
            for point_attr in ("start", "end"):
                pt = getattr(item, point_attr, None)
                if pt is not None:
                    xs.append(pt[0] - ox)
                    ys.append(pt[1] - oy)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _boite_locale(fp: Any) -> tuple[float, float, float, float]:
    from tools.placement import _boite_locale_fp  # import paresseux : placement importe ce module
    return _boite_locale_fp(fp)


def _bord_le_plus_proche(fp: Any, contour: tuple[float, float, float, float]) -> str:
    """'gauche' | 'droite' | 'haut' | 'bas' — le bord dont le CORPS est le plus près.
    Egalite (le coin de la grille, 5 mm de chaque cote) : le bord vertical, ou
    un en-tete vertical sort naturellement ses fils."""
    x0, y0, x1, y1 = contour
    bx0, by0, bx1, by1 = _boite_locale(fp)
    px, py = fp.position
    d = {
        "gauche": (px + bx0) - x0,
        "droite": x1 - (px + bx1),
        "haut": (py + by0) - y0,
        "bas": y1 - (py + by1),
    }
    mini = min(d.values())
    for bord in ("gauche", "droite", "haut", "bas"):  # priorite aux verticaux a egalite
        if d[bord] <= mini + 1e-6:
            return bord
    return "gauche"


def ancrer_connecteurs_au_bord(pcb: Any, marge_mm: float = MARGE_BORD_MM) -> list[str]:
    """Chaque connecteur au milieu de son bord le plus proche, repartis par bord.

    Rend les references deplacees. Ne touche a rien d autre : le genetique
    place le reste, et `fixed_refs` gardera ces positions.
    """
    contour = _contour_repere_board(pcb)
    conns = _connecteurs(pcb)
    if contour is None or not conns:
        return []
    x0, y0, x1, y1 = contour
    largeur, hauteur = x1 - x0, y1 - y0
    par_bord: dict[str, list[Any]] = {"gauche": [], "droite": [], "haut": [], "bas": []}
    for fp in conns:
        par_bord[_bord_le_plus_proche(fp, contour)].append(fp)
    deplaces: list[str] = []
    for bord, groupe in par_bord.items():
        n = len(groupe)
        # Repartis dans l ordre de leur position le long du bord : on garde
        # l ordre que le generateur (ou l utilisateur) leur avait donne.
        le_long = (lambda f: f.position[1]) if bord in ("gauche", "droite") else (lambda f: f.position[0])
        for i, fp in enumerate(sorted(groupe, key=le_long)):
            bx0, by0, bx1, by1 = _boite_locale(fp)
            if bord in ("gauche", "droite"):
                cy = y0 + hauteur * (i + 1) / (n + 1) - (by0 + by1) / 2.0
                cx = (x0 + marge_mm - bx0) if bord == "gauche" else (x1 - marge_mm - bx1)
            else:
                cx = x0 + largeur * (i + 1) / (n + 1) - (bx0 + bx1) / 2.0
                cy = (y0 + marge_mm - by0) if bord == "haut" else (y1 - marge_mm - by1)
            fp.position = (cx, cy)
            deplaces.append(fp.reference)
    logger.info("bords: %d connecteur(s) ancre(s) au milieu de leur bord — %s",
                len(deplaces), ", ".join(deplaces))
    return deplaces


def ancrer_connecteurs_au_bord_b64(kicad_pcb_b64: str) -> str:
    """La même règle, sur un board base64 (le format des routes)."""
    import base64
    import tempfile
    from kicad_tools.schema.pcb import PCB
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "b.kicad_pcb"
        f.write_bytes(base64.b64decode(kicad_pcb_b64))
        pcb = PCB.load(str(f))
        if not ancrer_connecteurs_au_bord(pcb):
            return kicad_pcb_b64
        pcb.save(str(f))
        return base64.b64encode(f.read_bytes()).decode()


def boite_des_courtyards(pcb: Any) -> Optional[tuple[float, float, float, float]]:
    """Boîte absolue (repère feuille) de tous les courtyards du board."""
    ox, oy = pcb.board_origin
    xs: list[float] = []
    ys: list[float] = []
    for fp in pcb.footprints:
        bx0, by0, bx1, by1 = _boite_locale(fp)
        px, py = fp.position
        xs += [px + bx0 + ox, px + bx1 + ox]
        ys += [py + by0 + oy, py + by1 + oy]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def ajuster_contour_au_placement(chemin: Path, marge_mm: float = MARGE_BORD_MM) -> Optional[tuple[float, float]]:
    """Resserre `Edge.Cuts` sur les courtyards + marge. Rend (largeur, hauteur).

    ⚠️ ON NE FAIT QUE RESSERRER, jamais agrandir : un contour plus grand que
    la boîte est un choix (taille imposée, zone de fixation) qu'on ne défait
    pas ici. Et on ne réécrit rien si le gain est nul.
    """
    from kicad_tools.schema.pcb import PCB
    from tools.placement import _blocs_edge_cuts  # import paresseux

    pcb = PCB.load(str(chemin))
    boite = boite_des_courtyards(pcb)
    if boite is None:
        return None
    ox, oy = pcb.board_origin
    contour = _contour_repere_board(pcb)
    nx0, ny0 = boite[0] - marge_mm, boite[1] - marge_mm
    nx1, ny1 = boite[2] + marge_mm, boite[3] + marge_mm
    if contour is not None:
        cx0, cy0, cx1, cy1 = (contour[0] + ox, contour[1] + oy, contour[2] + ox, contour[3] + oy)
        # Jamais au-delà du contour existant.
        nx0, ny0 = max(nx0, cx0), max(ny0, cy0)
        nx1, ny1 = min(nx1, cx1), min(ny1, cy1)
        if (nx0, ny0, nx1, ny1) == (cx0, cy0, cx1, cy1):
            return (cx1 - cx0, cy1 - cy0)
    largeur, hauteur = nx1 - nx0, ny1 - ny0

    texte = chemin.read_text(encoding="utf-8", errors="replace")
    blocs = _blocs_edge_cuts(texte)
    if not blocs:
        logger.error("contour: aucun Edge.Cuts — carte inchangee")
        return None
    for a, b in reversed(blocs):
        texte = texte[:a] + texte[b:]
    rect = (
        "\t(gr_rect\n"
        f"\t\t(start {nx0:.3f} {ny0:.3f})\n"
        f"\t\t(end {nx1:.3f} {ny1:.3f})\n"
        "\t\t(stroke\n\t\t\t(width 0.1)\n\t\t\t(type default)\n\t\t)\n"
        "\t\t(fill no)\n"
        '\t\t(layer "Edge.Cuts")\n'
        "\t)\n"
    )
    i = texte.rfind(")")
    if i < 0:
        return None
    chemin.write_text(texte[:i] + rect + texte[i:], encoding="utf-8")
    logger.info("contour: resserre a %.1fx%.1f mm (marge %.1f) — D-2026-09-13-c",
                largeur, hauteur, marge_mm)
    return (largeur, hauteur)


_COORD_RE = re.compile(r"\((?:start|end)\s+(-?[\d.]+)\s+(-?[\d.]+)\)")


def taille_contour_texte(texte: str) -> Optional[tuple[float, float]]:
    """(largeur, hauteur) lues dans les blocs Edge.Cuts d'un board texte."""
    from tools.placement import _blocs_edge_cuts
    xs, ys = [], []
    for a, b in _blocs_edge_cuts(texte):
        for x, y in _COORD_RE.findall(texte[a:b]):
            xs.append(float(x))
            ys.append(float(y))
    if not xs:
        return None
    return (max(xs) - min(xs), max(ys) - min(ys))

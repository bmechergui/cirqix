"""Les liaisons CRITIQUES d'un board placé, à router en priorité.

Décision D-2026-09-25-a (validée par l'utilisateur : « propose toi et fais tout
selon votre recommandation ») : avant le routage général, on relie
d'abord, par des pistes courtes sur une seule face et sans via :

1. chaque broche d'un QUARTZ à la broche du circuit qu'elle cadence ;
2. chaque condensateur de CHARGE du quartz à la broche du quartz ;
3. chaque condensateur de DÉCOUPLAGE à la broche d'alimentation du circuit.

Les paires différentielles sont DÉTECTÉES et signalées, jamais routées :
Freerouting 2.1.0 ne route pas en couplé.

Fonction PURE : elle lit le texte du board, sans pcbnew. Les positions servent
à choisir la cible et à écarter les liaisons longues ; le runner pcbnew
re-mesure avec la géométrie exacte avant de poser quoi que ce soit.

⚠️ Détection par la TOPOLOGIE, jamais par le seul nom. Un condensateur de
découplage est un condensateur entre un net et un net de PLAN : `LED_PWR` ou
`PWR_FLAG` ne sont pas des rails parce qu'ils s'appellent ainsi. Un quartz est
reconnu par sa référence ET son nombre de pastilles, jamais par un nom de net
(`SWCLK` n'est pas une horloge de quartz).

⚠️ Une liaison plus longue que `LIAISON_MAX_MM` n'est PAS posée : un
condensateur à 10 mm de sa broche est un défaut de PLACEMENT, qu'une piste
prioritaire figerait au lieu de le révéler.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

# Décision D-2026-09-25-a : 3 mm, le plafond natif du cluster POWER de
# `detect_functional_clusters` (placement_bypass.py). Mesuré comme lui : écart
# LIBRE entre les corps des deux composants, pas centre à centre.
LIAISON_MAX_MM: float = 3.0
# Longueur maximale d'une piste pré-routée, centre à centre. Une piste
# PROTÉGÉE revient à chaque tirage et à chaque palier : longue, elle devient un
# obstacle que rien ne rattrape (risque relevé par les deux critiques du
# 2026-09-25 ; précédent : l'amorce GND, trois fois plus lente). Mesure :
# le quartz de `stm32-validation` touche presque le corps de U2 mais ses
# broches OSC sont à 9 et 13 mm — ce n'est pas une liaison courte.
LONGUEUR_MAX_MM: float = 6.0

# Largeur d'une liaison d'alimentation (découplage). Les liaisons de quartz
# gardent la largeur standard.
LARGEUR_ALIM_MM: float = 0.4
LARGEUR_SIGNAL_MM: float = 0.25

# Références des composants PASSIFS ou de connexion : jamais une cible « circuit ».
_PREFIXES_NON_CIRCUIT = ("R", "C", "L", "FB", "D", "LED", "J", "P", "SW", "TP",
                         "Y", "X", "F", "BT", "H", "MH", "Q", "K")
_PREFIXE_QUARTZ_RE = re.compile(r"^(Y|X|XTAL)\d")
_NET_NUMEROTE_RE = re.compile(r'\(net\s+\d+\s+"([^"]*)"\)')
_NET_NU_RE = re.compile(r'\(net\s+"([^"]*)"\)')
_AT_RE = re.compile(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?\)")
_REF_RE = re.compile(r'\(property\s+"Reference"\s+"([^"]+)"')
_REF_ANCIEN_RE = re.compile(r'\(fp_text\s+reference\s+"?([^"\s)]+)')
_COUCHES_RE = re.compile(r'\(layers\s+([^)]*)\)')
_TAILLE_RE = re.compile(r"\(size\s+([\d.]+)\s+([\d.]+)\)")


@dataclass(frozen=True)
class Pastille:
    ref: str
    nom: str
    net: str
    x: float
    y: float
    cms: bool
    couche: str          # "F.Cu" ou "B.Cu" pour une CMS, "*" pour une traversante
    demi_taille: float = 0.0   # demi-diagonale de la pastille, pour le corps


@dataclass(frozen=True)
class Liaison:
    type: str            # "quartz", "charge-quartz", "decouplage"
    net: str
    a: tuple             # (ref, pastille) — le passif
    b: tuple             # (ref, pastille) — la cible
    distance_mm: float
    largeur_mm: float

    def en_dict(self) -> dict:
        return {"type": self.type, "net": self.net, "a": list(self.a), "b": list(self.b),
                "distance_mm": round(self.distance_mm, 3), "largeur_mm": self.largeur_mm}


def _blocs(texte: str, tete: str) -> list:
    """Les blocs parenthésés qui commencent par `tete`, en comptant les
    parenthèses — jamais par une expression régulière qui s'arrêterait au
    premier `)` (piège inscrit le 2026-09-09)."""
    blocs, i = [], 0
    while True:
        i = texte.find(tete, i)
        if i < 0:
            return blocs
        profondeur, j = 0, i
        while j < len(texte):
            c = texte[j]
            if c == "(":
                profondeur += 1
            elif c == ")":
                profondeur -= 1
                if profondeur == 0:
                    break
            elif c == '"':
                j = texte.find('"', j + 1)
                if j < 0:
                    return blocs
            j += 1
        blocs.append(texte[i:j + 1])
        i = j + 1


def _net_de(bloc: str) -> str:
    m = _NET_NUMEROTE_RE.search(bloc) or _NET_NU_RE.search(bloc)
    return m.group(1) if m else ""


def pastilles_du_board(texte: str) -> list:
    """Toutes les pastilles du board, en coordonnées FEUILLE.

    Rotation dans le sens de KiCad (l'axe y descend) :
    (x, y) -> (x cos a + y sin a, -x sin a + y cos a) — le sens opposé est
    invisible sur un boîtier centré et faux dès qu'il ne l'est pas (leçon du
    2026-09-21).
    """
    pastilles = []
    for fp in _blocs(texte, "(footprint "):
        ref_m = _REF_RE.search(fp) or _REF_ANCIEN_RE.search(fp)
        pads = _blocs(fp, "(pad ")
        if not ref_m or not pads:
            continue
        entete = fp[:fp.find("(pad ")]
        at = _AT_RE.search(entete)
        if not at:
            continue
        fx, fy = float(at.group(1)), float(at.group(2))
        a = math.radians(float(at.group(3) or 0.0))
        ca, sa = math.cos(a), math.sin(a)
        for pad in pads:
            nom_m = re.match(r'\(pad\s+"([^"]*)"\s+(\S+)', pad)
            pat = _AT_RE.search(pad)
            if not nom_m or not pat:
                continue
            dx, dy = float(pat.group(1)), float(pat.group(2))
            couches = _COUCHES_RE.search(pad)
            texte_couches = couches.group(1) if couches else ""
            cms = nom_m.group(2) == "smd"
            if not cms:
                couche = "*"
            elif "B.Cu" in texte_couches:
                couche = "B.Cu"
            else:
                couche = "F.Cu"
            taille = _TAILLE_RE.search(pad)
            demi = (math.hypot(float(taille.group(1)), float(taille.group(2))) / 2.0
                    if taille else 0.0)
            pastilles.append(Pastille(
                ref=ref_m.group(1), nom=nom_m.group(1), net=_net_de(pad),
                x=fx + dx * ca + dy * sa, y=fy - dx * sa + dy * ca,
                cms=cms, couche=couche, demi_taille=demi))
    return pastilles


def _prefixe(ref: str) -> str:
    return re.match(r"^[A-Za-z]+", ref).group(0).upper() if re.match(r"^[A-Za-z]+", ref) else ""


def _est_circuit(ref: str, nb_pastilles: int) -> bool:
    """Un circuit intégré ou un module : `U`/`IC`, ou 5 pastilles et plus hors
    passifs et connecteurs."""
    p = _prefixe(ref)
    if p in ("U", "IC", "M", "MOD"):
        return True
    return nb_pastilles >= 5 and not p.startswith(_PREFIXES_NON_CIRCUIT)


def _corps(pastilles) -> tuple:
    """Boîte (x1, y1, x2, y2) d'un composant, d'après ses pastilles."""
    return (min(p.x - p.demi_taille for p in pastilles), min(p.y - p.demi_taille for p in pastilles),
            max(p.x + p.demi_taille for p in pastilles), max(p.y + p.demi_taille for p in pastilles))


def ecart_entre_corps(a: tuple, b: tuple) -> float:
    """Écart LIBRE entre deux boîtes, 0 si elles se touchent.

    ⚠️ Jamais depuis les ORIGINES des empreintes (leçon du 2026-08-29) : c'est
    l'écart entre CORPS que mesure le cluster natif — et donc le 3 mm validé.
    Centre à centre, un 0603 collé à un LQFP est à 4-5 mm de sa broche.
    """
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return math.hypot(dx, dy)


def _distance(p: Pastille, q: Pastille) -> float:
    return math.hypot(p.x - q.x, p.y - q.y)


def _meme_face(p: Pastille, q: Pastille) -> bool:
    """Une liaison prioritaire reste sur UNE face, sans via.

    ⚠️ Une pastille TRAVERSANTE existe sur toutes les faces : elle rejoint une
    CMS sur la face de celle-ci, sans via. Le quartz HC-49 de
    `stm32-validation` est traversant ; l'exiger CMS l'écartait à tort.
    """
    return p.couche == q.couche or "*" in (p.couche, q.couche)


def face_de_la_liaison(p: Pastille, q: Pastille) -> str:
    """La face sur laquelle poser la piste : celle de la CMS, F.Cu sinon."""
    for x in (p, q):
        if x.couche != "*":
            return x.couche
    return "F.Cu"


def liaisons_critiques(texte: str, nets_plan=("GND",),
                       liaison_max_mm: float = LIAISON_MAX_MM) -> list:
    """Les liaisons à router en priorité, dans l'ordre où les poser.

    Rend une liste de `Liaison` : quartz d'abord (le plus contraint), puis
    charges du quartz, puis découplages. Chaque pastille n'apparaît qu'UNE fois
    comme source : une pastille, un propriétaire.
    """
    plan = set(nets_plan or ())
    pastilles = pastilles_du_board(texte)
    par_ref: dict = {}
    for p in pastilles:
        par_ref.setdefault(p.ref, []).append(p)
    circuits = {r for r, ps in par_ref.items() if _est_circuit(r, len(ps))}
    quartz = {r for r, ps in par_ref.items()
              if _PREFIXE_QUARTZ_RE.match(r) and 2 <= len(ps) <= 4}
    condensateurs = {r for r, ps in par_ref.items()
                     if _prefixe(r) == "C" and len(ps) == 2}

    liaisons: list = []
    sources_prises: set = set()

    def _plus_proche(source: Pastille, candidates) -> tuple:
        meilleures = sorted(((_distance(source, c), c) for c in candidates
                             if _meme_face(source, c)), key=lambda t: t[0])
        return meilleures[0] if meilleures else (None, None)

    corps = {r: _corps(ps) for r, ps in par_ref.items()}

    def _ajouter(type_, source, cible, d, largeur):
        cle = (source.ref, source.nom)
        if cle in sources_prises or d is None:
            return
        if ecart_entre_corps(corps[source.ref], corps[cible.ref]) > liaison_max_mm:
            return
        if d > LONGUEUR_MAX_MM:
            return
        sources_prises.add(cle)
        liaisons.append(Liaison(type_, source.net, (source.ref, source.nom),
                                (cible.ref, cible.nom), d, largeur))

    # 1. Quartz -> broche du circuit sur le même net.
    for q in sorted(quartz):
        for pq in par_ref[q]:
            if not pq.net or pq.net in plan:
                continue
            cibles = [p for r in circuits for p in par_ref[r] if p.net == pq.net]
            d, cible = _plus_proche(pq, cibles)
            if cible is not None:
                _ajouter("quartz", pq, cible, d, LARGEUR_SIGNAL_MM)

    # 2. Condensateur de charge -> broche du quartz.
    nets_quartz = {pq.net: pq for q in quartz for pq in par_ref[q]
                   if pq.net and pq.net not in plan}
    for c in sorted(condensateurs):
        a, b = par_ref[c]
        for pc, autre in ((a, b), (b, a)):
            if pc.net in nets_quartz and autre.net in plan:
                d, cible = _plus_proche(pc, [nets_quartz[pc.net]])
                if cible is not None:
                    _ajouter("charge-quartz", pc, cible, d, LARGEUR_SIGNAL_MM)

    # 3. Découplage : condensateur entre un net et un net de PLAN, vers la
    #    broche du circuit la plus proche sur ce net.
    for c in sorted(condensateurs):
        a, b = par_ref[c]
        for pc, autre in ((a, b), (b, a)):
            if not pc.net or pc.net in plan or autre.net not in plan:
                continue
            if pc.net in nets_quartz:
                continue   # c'est une charge de quartz, déjà traitée
            cibles = [p for r in circuits for p in par_ref[r] if p.net == pc.net]
            d, cible = _plus_proche(pc, cibles)
            if cible is not None:
                _ajouter("decouplage", pc, cible, d, LARGEUR_ALIM_MM)
    return liaisons


def paires_differentielles(texte: str) -> list:
    """Paires de nets `X_P`/`X_N`, `X+`/`X-` ou `XP`/`XN` qui touchent les
    MÊMES boîtiers. Détectées pour être SIGNALÉES, jamais routées en couplé."""
    par_net: dict = {}
    for p in pastilles_du_board(texte):
        if p.net:
            par_net.setdefault(p.net, set()).add(p.ref)
    paires, vus = [], set()
    suffixes = (("_P", "_N"), ("+", "-"), ("P", "N"), ("_DP", "_DM"), ("D+", "D-"))
    for net in sorted(par_net):
        for sp, sn in suffixes:
            if net.endswith(sp):
                jumeau = net[: -len(sp)] + sn
                if jumeau in par_net and (net, jumeau) not in vus:
                    if par_net[net] == par_net[jumeau] and len(par_net[net]) >= 2:
                        paires.append((net, jumeau))
                        vus.add((net, jumeau))
    return paires

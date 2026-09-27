"""Phase C de D-2026-09-26-a : les paires LED + R rangées en matrice.

Mesure du 2026-09-26 sur cinq boards placés de la campagne (carte-06 à 10),
cellules qui réservent la place des repères : carte-06, 08, 10 rangées —
croisements 228->111, 298->222, 721->577, et 0 avertissement de sérigraphie
après la phase B ; carte-07 et 09 sans place pour la matrice, laissées en
l'état. Aucune erreur DRC ajoutée, 0,5 s au plus.

⚠️ `ranger_les_paires` (contre le bord le plus libre) ne se déclenchait plus
depuis la phase A : chaque bord porte un connecteur.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "kicad-tools" / "src"))

from kicad_tools.schema.pcb import PCB  # noqa: E402

from tools import placement as P  # noqa: E402
from tools import placement_zones as Z  # noqa: E402
from tools.placement_contraintes import paires_du_board  # noqa: E402
from tools.placement_familles import _familles, ranger_les_familles  # noqa: E402

CARTE_07 = RACINE / "examples" / "carte-07-multi-io" / "expected" / "placement.kicad_pcb"
CARTE_10 = RACINE / "examples" / "carte-10-maximale" / "expected" / "placement.kicad_pcb"


def test_les_reperes_ont_leur_place_dans_la_matrice(tmp_path):
    """Au pas « corps + 0,5 mm », carte-08 passait de 6 à 45 avertissements :
    chaque repère doit tenir dans sa cellule, sans toucher un autre repère."""
    from tools import serigraphie as S
    pcb = _charger(tmp_path)
    deplaces = set(ranger_les_familles(pcb, P._connector_refs(pcb)))
    boites = S.boites_des_references(pcb)
    for a in deplaces:
        for b in deplaces:
            if a < b:
                assert not S._chevauche(boites[a], boites[b], 0.0), (a, b)


def _charger(tmp_path, source=CARTE_10):
    copie = tmp_path / "b.kicad_pcb"
    copie.write_bytes(source.read_bytes())
    return PCB.load(str(copie))


def test_les_paires_sont_rangees_en_matrice_alignee(tmp_path):
    pcb = _charger(tmp_path)
    conn = P._connector_refs(pcb)
    paires = [p for g in _familles(pcb, paires_du_board(pcb)) for p in g]
    deplaces = ranger_les_familles(pcb, conn)
    assert len(deplaces) == 2 * len(paires) >= 6
    fps = {f.reference: f for f in pcb.footprints}
    haut_des_led = sorted({round(Z.boite_absolue(fps[d])[1], 3) for _, d, _ in paires})
    assert len(haut_des_led) <= 4                       # au plus quatre rangées
    for _, d, r in paires:
        bd, br = Z.boite_absolue(fps[d]), Z.boite_absolue(fps[r])
        assert fps[d].rotation == 0 and fps[r].rotation == 0
        assert br[1] > bd[3]                            # la résistance sous sa LED
        assert abs((bd[0] + bd[2]) - (br[0] + br[2])) < 1e-6   # même colonne, centrés


def test_rien_ne_se_recouvre_ni_ne_touche_une_zone(tmp_path):
    pcb = _charger(tmp_path)
    conn = P._connector_refs(pcb)
    deplaces = set(ranger_les_familles(pcb, conn))
    boites = {f.reference: Z.boite_absolue(f) for f in pcb.footprints}
    for a in deplaces:
        for b, bb in boites.items():
            if b != a:
                assert not P._boites_se_recouvrent(boites[a], bb, 0.0), (a, b)
    assert not [v for v in Z.violations_de_zones(pcb, conn) if v[0] in deplaces]


def test_les_pastilles_tournent_avec_le_boitier(tmp_path):
    pcb = _charger(tmp_path)
    avant = {f.reference: (f.rotation, [p.rotation for p in f.pads]) for f in pcb.footprints}
    for ref in ranger_les_familles(pcb, P._connector_refs(pcb)):
        f = next(x for x in pcb.footprints if x.reference == ref)
        rot0, pads0 = avant[ref]
        delta = (f.rotation - rot0) % 360
        assert [p.rotation % 360 for p in f.pads] == [(a + delta) % 360 for a in pads0]


def test_une_famille_trop_petite_ou_figee_ne_bouge_pas(tmp_path):
    pcb = _charger(tmp_path)
    tous = [x for _, d, r in paires_du_board(pcb) for x in (d, r)]
    assert ranger_les_familles(pcb, P._connector_refs(pcb) + tous) == []


def test_le_garde_fou():
    assert P._rangement_degrade(0, 1, 100.0, 50.0)          # une erreur de plus
    assert P._rangement_degrade(0, 0, 100.0, 101.0)         # plus de croisements
    assert P._rangement_degrade(0, 0, 100.0, None)          # jugement impossible
    assert not P._rangement_degrade(0, 0, 100.0, 80.0)
    assert not P._rangement_degrade(1, 1, None, None)


def test_le_placement_range_les_familles_avant_la_grille():
    src = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")
    corps = src[src.index("def _auto_place_une_fois("):]
    fam = corps.index("from tools.placement_familles import ranger_les_familles")
    assert "if not centres_etoile:" in corps[fam - 400:fam]
    assert "_rangement_degrade(" in corps[fam:fam + 1500]
    assert fam < corps.index("aligner_sur_grille(out, _pas, figes=conn)")


def test_sans_place_pour_la_matrice_rien_ne_bouge(tmp_path, monkeypatch):
    """Aucune place libre (recherche vide) : rien n est déplacé, et les
    rotations tournées pour mesurer sont rendues."""
    import tools.placement_familles as PF
    monkeypatch.setattr(PF, "_anneaux", lambda rayon: iter(()))
    pcb = _charger(tmp_path, CARTE_07)
    avant = {f.reference: (f.position, f.rotation, [p.rotation for p in f.pads])
             for f in pcb.footprints}
    assert ranger_les_familles(pcb, P._connector_refs(pcb)) == []
    apres = {f.reference: (f.position, f.rotation % 360, [p.rotation % 360 for p in f.pads])
             for f in pcb.footprints}
    assert apres == {r: (v[0], v[1] % 360, [a % 360 for a in v[2]]) for r, v in avant.items()}


def test_un_composant_n_appartient_qu_a_une_famille_et_une_paire(tmp_path):
    pcb = _charger(tmp_path)
    vus = [x for g in _familles(pcb, paires_du_board(pcb)) for _, d, r in g for x in (d, r)]
    assert len(vus) == len(set(vus))


def test_deux_groupes_eloignes_font_deux_familles(tmp_path):
    """Revue du 2026-09-26 : une matrice unique pour tout le board rassemblait au
    centre global deux groupes posés loin l un de l autre."""
    pcb = _charger(tmp_path)
    fps = {f.reference: f for f in pcb.footprints}
    paires = [p for g in _familles(pcb, paires_du_board(pcb)) for p in g][:6]
    for k, (_, d, r) in enumerate(paires):
        x = 10.0 if k < 3 else 200.0          # deux groupes à 190 mm l un de l autre
        fps[d].position = (x + 4 * k, 10.0)
        fps[r].position = (x + 4 * k, 14.0)
    groupes = _familles(pcb, paires)
    assert sorted(len(g) for g in groupes) == [3, 3]


def test_la_recherche_va_du_plus_proche_au_plus_loin():
    from tools.placement_familles import _anneaux
    import math
    d = [math.hypot(*x) for x in _anneaux(10.0)]
    assert d == sorted(d) and d[0] == 0.0


def test_un_reglage_de_banc_desarme_l_etape(tmp_path, monkeypatch):
    """Témoin d'A/B : `familles_rangees` à faux, rien ne bouge. Défaut : armé."""
    monkeypatch.setattr("tools.reglages_banc.reglage",
                        lambda nom, defaut: False if nom == "familles_rangees" else defaut)
    pcb = _charger(tmp_path)
    assert ranger_les_familles(pcb, P._connector_refs(pcb)) == []


def test_la_matrice_vise_les_broches_cibles(tmp_path, monkeypatch):
    """D-2026-09-27-b : visé sur les broches qui pilotent les résistances, le
    bloc finit plus près d elles qu avec l ancienne visée (centre des paires)."""
    import math
    import tools.placement_familles as PF
    from tools.placement_familles import _cible, _familles

    def distance_du_bloc(pcb):
        famille = max(_familles(pcb, paires_du_board(pcb)), key=len)
        cibles = [c for c in (_cible(pcb, d, r, net) for net, d, r in famille) if c is not None]
        tx = sum(x for x, _ in cibles) / len(cibles)
        ty = sum(y for _, y in cibles) / len(cibles)
        fps = {f.reference: f for f in pcb.footprints}
        bs = [Z.boite_absolue(fps[x]) for _, d, r in famille for x in (d, r)]
        cx = sum((b[0] + b[2]) / 2 for b in bs) / len(bs)
        cy = sum((b[1] + b[3]) / 2 for b in bs) / len(bs)
        return math.dist((cx, cy), (tx, ty)), famille

    nouveau = _charger(tmp_path)
    avant, _ = distance_du_bloc(nouveau)
    assert ranger_les_familles(nouveau, P._connector_refs(nouveau))
    d_nouveau, _ = distance_du_bloc(nouveau)

    ancien = _charger(tmp_path / "a" if (tmp_path / "a").mkdir() is None else tmp_path)
    vrai_cible = PF._cible
    monkeypatch.setattr(PF, "_cible", lambda *a, **k: None)       # ancienne visée
    assert ranger_les_familles(ancien, P._connector_refs(ancien))
    monkeypatch.setattr(PF, "_cible", vrai_cible)
    d_ancien, _ = distance_du_bloc(ancien)
    assert d_nouveau <= d_ancien + 1e-6, (d_nouveau, d_ancien)

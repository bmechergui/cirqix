"""Placement « pro » — D-2026-09-26-a (validée par l'utilisateur, 2026-09-26).

Règles de l'utilisateur, sur l'image de nucleo-f401 : « il ne faut pas dans
les cartes arduino, nucleo… faire des composants en dessous ou dans le bord ».
Précisées par lui :

1. un connecteur est COUCHÉ le long de son bord (grand axe parallèle), collé à
   2 mm (1 mm se heurte au filet hors carte) — mesuré le 2026-09-26 : 35
   connecteurs sur 48 étaient debout,
   plongeant de 6 à 11 mm dans la carte ;
2. RIEN sous ni autour d'un connecteur (bande de 1,5 mm) ;
3. RIEN contre le bord pour les autres composants (corps à 1,5 mm au moins).

Gardes sur de VRAIS boards du banc, pas seulement sur des fixtures.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from kicad_tools.schema.pcb import PCB  # noqa: E402

from tools import placement as P  # noqa: E402
from tools import placement_zones as Z  # noqa: E402

CARTE_07 = RACINE / "examples" / "carte-07-multi-io" / "expected" / "placement.kicad_pcb"


def _charger(tmp_path: Path, source: Path = CARTE_07):
    copie = tmp_path / "board.kicad_pcb"
    shutil.copyfile(source, copie)
    return copie, PCB.load(str(copie))


class TestCoucherLesConnecteurs:
    def test_un_connecteur_debout_contre_un_bord_est_couche_le_long(self, tmp_path):
        _, pcb = _charger(tmp_path)
        conn = P._connector_refs(pcb)
        debout = [r for r in conn if not Z.parallele_a_son_bord(pcb, r)]
        assert debout, "le board de référence doit porter au moins un connecteur debout"
        Z.coucher_les_connecteurs(pcb, conn)
        assert all(Z.parallele_a_son_bord(pcb, r) for r in conn), \
            [r for r in conn if not Z.parallele_a_son_bord(pcb, r)]

    def test_les_pastilles_tournent_avec_le_boitier(self, tmp_path):
        """L'angle ABSOLU de chaque pastille avance du même pas que le boîtier,
        sinon l'écriture laisse des pastilles couchées sur un boîtier debout
        (le défaut du 2026-09-20 : 205 erreurs sur un board sans piste)."""
        _, pcb = _charger(tmp_path)
        conn = P._connector_refs(pcb)
        avant = {fp.reference: (fp.rotation, [p.rotation for p in fp.pads])
                 for fp in pcb.footprints if fp.reference in conn}
        tournes = Z.coucher_les_connecteurs(pcb, conn)
        assert tournes
        for fp in pcb.footprints:
            if fp.reference in tournes:
                rot0, pads0 = avant[fp.reference]
                delta = (fp.rotation - rot0) % 360
                assert delta in (90.0, 270.0)
                assert [p.rotation % 360 for p in fp.pads] == \
                    [(a + delta) % 360 for a in pads0]

    def test_un_couche_qui_recouvre_un_autre_connecteur_est_redresse(self, tmp_path):
        """Revue du 2026-09-26 : deux connecteurs figés qui se recouvrent ne
        seraient séparés par personne (optimiseur et réparation DRC les ignorent)."""
        _, pcb = _charger(tmp_path)
        conn = P._connector_refs(pcb)
        tournes = Z.coucher_les_connecteurs(pcb, conn)
        ref = next(iter(tournes))
        fp = next(f for f in pcb.footprints if f.reference == ref)
        autre = next(f for f in pcb.footprints if f.reference in conn and f.reference != ref)
        autre.position = fp.position          # posé en plein sur le couché
        rot = fp.rotation
        assert ref in Z.redresser_les_conflits(pcb, tournes)
        assert fp.rotation == (rot - tournes[ref]) % 360

    def test_sans_recouvrement_rien_n_est_redresse(self, tmp_path):
        _, pcb = _charger(tmp_path)
        conn = P._connector_refs(pcb)
        tournes = Z.coucher_les_connecteurs(pcb, conn)
        for fp in pcb.footprints:              # écartés loin les uns des autres
            if fp.reference in tournes:
                fp.position = (fp.position[0] + 500 * list(tournes).index(fp.reference), fp.position[1])
        assert Z.redresser_les_conflits(pcb, tournes) == []

    def test_un_exempte_ne_bouge_pas(self, tmp_path):
        _, pcb = _charger(tmp_path)
        conn = P._connector_refs(pcb)
        rot = {fp.reference: fp.rotation for fp in pcb.footprints}
        Z.coucher_les_connecteurs(pcb, conn, exempts=conn)
        assert all(fp.rotation == rot[fp.reference] for fp in pcb.footprints)


class TestZones:
    def test_un_composant_sous_un_connecteur_ou_contre_le_bord_est_ecarte(self, tmp_path):
        chemin, pcb = _charger(tmp_path)
        conn = P._connector_refs(pcb)
        mobiles = [fp for fp in pcb.footprints if fp.reference not in conn]
        j = next(fp for fp in pcb.footprints if fp.reference in conn)
        bornes = P._outline_bounds(pcb)
        # un passif SOUS le connecteur, un autre collé au bord gauche
        mobiles[0].position = j.position
        mobiles[1].position = (bornes[0] + 0.2, (bornes[2] + bornes[3]) / 2)
        pcb.save(str(chemin))
        assert len(Z.violations_de_zones(PCB.load(str(chemin)), conn)) >= 2
        deplaces = Z.respecter_les_zones(chemin, conn)
        assert {mobiles[0].reference, mobiles[1].reference} <= set(deplaces)
        assert Z.violations_de_zones(PCB.load(str(chemin)), conn) == []

    def test_aucun_chevauchement_cree(self, tmp_path):
        chemin, pcb = _charger(tmp_path)
        conn = P._connector_refs(pcb)
        deplaces = set(Z.respecter_les_zones(chemin, conn))
        final = PCB.load(str(chemin))
        boites = [(fp.reference, Z.boite_absolue(fp)) for fp in final.footprints]
        for i, (ra, a) in enumerate(boites):
            for rb, b in boites[i + 1:]:
                if ra in deplaces or rb in deplaces:
                    assert not P._boites_se_recouvrent(a, b), (ra, rb)

    def test_les_marges_sont_celles_validees(self):
        assert Z.MARGE_BORD_MM == 1.5
        assert Z.BANDE_CONNECTEUR_MM == 1.5
        assert Z.MARGE_CONNECTEUR_BORD_MM == 2.0   # 1 mm : repoussé par le filet hors carte


class TestCablage:
    SOURCE = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_couche_avant_de_coller_puis_optimise(self):
        couche = self.SOURCE.index("couches = coucher_les_connecteurs(pcb, conn, exempts=dominants)")
        colle = self.SOURCE.index("_coller_les_ancrages_au_bord(pcb, conn, exempts=dominants")
        optim = self.SOURCE.index("OptimizationWorkflow(", colle)
        assert couche < colle < optim

    def test_redresse_apres_le_collage_puis_recolle(self):
        colle = self.SOURCE.index("_coller_les_ancrages_au_bord(pcb, conn, exempts=dominants")
        redresse = self.SOURCE.index("if redresser_les_conflits(pcb, couches):", colle)
        recolle = self.SOURCE.index("_coller_les_ancrages_au_bord(pcb, conn, exempts=dominants", redresse)
        assert colle < redresse < recolle < self.SOURCE.index("OptimizationWorkflow(", recolle)

    def test_colle_a_la_marge_validee(self):
        assert ("_coller_les_ancrages_au_bord(pcb, conn, exempts=dominants,\n"
                "                                    margin_mm=MARGE_CONNECTEUR_BORD_MM)") in self.SOURCE

    def test_zones_apres_le_dernier_deplacement_avant_la_reparation_drc(self):
        grille = self.SOURCE.index("aligner_sur_grille(out, _pas, figes=conn)")
        garde = self.SOURCE.index("_garder_dans_le_contour(out, conn, fixes_snap)", grille)
        zones = self.SOURCE.index("respecter_les_zones(out, conn)", garde)
        drc = self.SOURCE.index("_reparer_chevauchements_du_drc(out, conn)", zones)
        assert grille < garde < zones < drc


class TestTirages:
    """carte-02, tirage 2 du 2026-09-26 : « U2 touche connecteur J2, aucune place
    libre à 40 mm » — le tirage était pourtant retenu, car la boucle s'arrêtait
    au premier tirage sans conflit. Une violation de zone départage désormais
    les tirages, et un tirage qui en porte ne clôt pas la boucle."""

    def test_moins_de_violations_de_zone_l_emporte_avant_le_fil(self):
        propre = {"conflits_restants": 0, "violations_zones": 0, "croisements": 9, "fil_mm": 900}
        viole = {"conflits_restants": 0, "violations_zones": 1, "croisements": 1, "fil_mm": 100}
        assert P._placement_meilleur(propre, viole)
        assert not P._placement_meilleur(viole, propre)

    def test_les_conflits_passent_avant_les_zones(self):
        conflit = {"conflits_restants": 1, "violations_zones": 0}
        zone = {"conflits_restants": 0, "violations_zones": 3}
        assert P._placement_meilleur(zone, conflit)

    def test_un_tirage_mesure_bat_un_tirage_sans_mesure_de_zone(self):
        mesure = {"conflits_restants": 0, "violations_zones": 2}
        inconnu = {"conflits_restants": 0}
        assert P._placement_meilleur(mesure, inconnu)
        assert not P._placement_meilleur(inconnu, mesure)

    def test_la_boucle_ne_s_arrete_que_sur_un_tirage_sans_violation(self):
        src = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")
        assert '"violations_zones": len(violations_de_zones(' in src
        assert "if n_conflits == 0 and n_zones == 0 and essai + 1 >= _TIRAGES_MINIMUM:" in src

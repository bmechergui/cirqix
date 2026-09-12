"""Une empreinte déclarée doit EXISTER — et si elle n'existe pas, on le dit.

⚠️ MESURE DU 2026-09-09 sur `carte-05-capteur-i2c`. Le schéma déclarait
`Package_LGA:LGA-8_2.5x2.5mm_P0.65mm`. Ce nom **n'existe pas** : KiCad livre
l'empreinte du BME280 sous
`Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering` — préfixe fabricant et
suffixe de numérotation horaire, ce capteur ne suivant pas la convention LGA.

`add_component` rendait `None`, le capteur disparaissait, et la carte sortait
**« 100 % routée, 0 erreur » SANS LUI**.

⚠️ **CORRIGER LE NOM DANS CE SCHÉMA-LÀ NE CORRIGE RIEN.** Le nom vient d'un
modèle de langage : il sera plausible et faux aussi souvent qu'on lui demandera.
D'où une vérification GÉNÉRALE, posée avant la cascade de génération — demande
de l'utilisateur : « je veux toujours une solution générale pour marcher avec
tous les types de cartes ».

⚠️ **ET ON NE DEVINE PAS.** Poser une empreinte au mauvais pas ou au mauvais
nombre de pastilles est PIRE que de perdre le composant : le board part en
fabrication avec un boîtier qui ne se soude pas, et rien ne le signale. On ne
remplace que sur un candidat unique et contenant.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import empreintes_reelles as E  # noqa: E402


@pytest.fixture()
def bibliotheque(tmp_path, monkeypatch):
    """Une bibliothèque `.pretty` factice, avec le cas réel du BME280."""
    racine = tmp_path / "footprints"
    lib = racine / "Package_LGA.pretty"
    lib.mkdir(parents=True)
    for nom in ("Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering",
                "Bosch_LGA-8_3x3mm_P0.8mm_ClockwisePinNumbering",
                "LGA-8_3x5mm_P1.25mm"):
        (lib / (nom + ".kicad_mod")).write_text("(footprint)", encoding="utf-8")

    autre = racine / "Ambigu.pretty"
    autre.mkdir()
    for nom in ("Pre_MOTIF_A", "Pre_MOTIF_B"):
        (autre / (nom + ".kicad_mod")).write_text("(footprint)", encoding="utf-8")

    monkeypatch.setattr(E, "_dossier_de_bibliotheque",
                        lambda b: racine / (b + ".pretty")
                        if (racine / (b + ".pretty")).is_dir() else None)
    monkeypatch.setattr(E, "existe",
                        lambda r: bool(":" in r and E._dossier_de_bibliotheque(
                            r.split(":", 1)[0])
                            and (E._dossier_de_bibliotheque(r.split(":", 1)[0])
                                 / (r.split(":", 1)[1] + ".kicad_mod")).is_file()))
    return racine


class TestExistence:
    def test_une_empreinte_reelle_est_reconnue(self, bibliotheque):
        assert E.existe("Package_LGA:LGA-8_3x5mm_P1.25mm")

    def test_une_empreinte_inventee_ne_l_est_pas(self, bibliotheque):
        assert not E.existe("Package_LGA:LGA-8_2.5x2.5mm_P0.65mm")

    def test_une_reference_sans_bibliotheque_est_refusee(self, bibliotheque):
        assert not E.existe("PasDeDeuxPoints")


class TestRetrouver:
    def test_LE_CAS_REEL_du_BME280(self, bibliotheque):
        """Le nom demandé est CONTENU dans le nom réel — cas sans ambiguïté."""
        assert E.trouver_la_vraie("Package_LGA:LGA-8_2.5x2.5mm_P0.65mm") == \
            "Package_LGA:Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering"

    def test_PLUSIEURS_candidats_ne_tranchent_RIEN(self, bibliotheque):
        """⚠️ Choisir au hasard entre deux boîtiers voisins est le genre
        d'erreur qui ne se voit qu'à la refusion."""
        assert E.trouver_la_vraie("Ambigu:MOTIF") is None

    def test_une_bibliotheque_inconnue_ne_rend_rien(self, bibliotheque):
        assert E.trouver_la_vraie("BibliothequeQuiNExistePas:Truc") is None

    def test_un_nom_sans_rapport_ne_rend_rien(self, bibliotheque):
        """On avoue l'ignorance plutôt que de poser un boîtier approchant."""
        assert E.trouver_la_vraie("Package_LGA:QSOP-24_ABSOLUMENT_AUTRE") is None


class TestCorrection:
    def test_le_composant_fautif_est_corrige_sur_place(self, bibliotheque):
        comps = [{"ref": "U3",
                  "footprint": "Package_LGA:LGA-8_2.5x2.5mm_P0.65mm"}]
        corrigees, introuvables = E.verifier_et_corriger(comps)
        assert corrigees == 1 and introuvables == []
        assert comps[0]["footprint"].startswith("Package_LGA:Bosch_")

    def test_une_empreinte_VALIDE_n_est_pas_touchee(self, bibliotheque):
        """Un correctif qui « améliore » ce qui va déjà bien est une régression
        déguisée."""
        comps = [{"ref": "D1", "footprint": "Package_LGA:LGA-8_3x5mm_P1.25mm"}]
        assert E.verifier_et_corriger(comps) == (0, [])
        assert comps[0]["footprint"] == "Package_LGA:LGA-8_3x5mm_P1.25mm"

    def test_une_empreinte_INTROUVABLE_est_NOMMEE(self, bibliotheque, caplog):
        """⚠️ Avant, le composant disparaissait du board sans un mot, et la
        carte sortait « 100 % routée » sans lui."""
        comps = [{"ref": "X9", "footprint": "Package_LGA:RIEN_DE_TEL_ICI"}]
        with caplog.at_level("ERROR"):
            corrigees, introuvables = E.verifier_et_corriger(comps)
        assert corrigees == 0
        assert introuvables and "X9" in introuvables[0]
        assert any("PERDU" in m for m in caplog.messages)

    def test_un_objet_sans_empreinte_est_ignore_sans_bruit(self, bibliotheque):
        """L'agent Footprint traite ce cas-là ; ce n'est pas le nôtre."""
        assert E.verifier_et_corriger([{"ref": "J1", "footprint": None}]) == (0, [])


class TestCablage:
    """⚠️ Une règle correcte jamais appelée est indistinguable d'une absente."""

    def test_la_generation_verifie_AVANT_la_cascade(self):
        from tools import pcb as P
        src = inspect.getsource(P.generate_pcb)
        code = "\n".join(l.split("#")[0] for l in src.splitlines())
        assert "verifier_et_corriger" in code, (
            "les empreintes ne sont pas verifiees avant la generation")
        # ⚠️ Avant le PREMIER NIVEAU de la cascade, sinon il a deja perdu le
        # composant. On s ancre sur l APPEL du niveau 1, pas sur un nom qui
        # apparait aussi dans la signature — premiere version de cette garde,
        # qui comparait a `kicad_sch_content` et le trouvait en position 135,
        # dans la liste des parametres. Ancrer sur ce qui ne bouge pas.
        assert code.index("verifier_et_corriger") < code.index(
            "_generate_with_kicad_tools"), (
            "la verification passe APRES le premier niveau de la cascade")

    def test_une_verification_indisponible_est_DITE(self):
        from tools import pcb as P
        src = inspect.getsource(P.generate_pcb)
        i = src.index("verifier_et_corriger")
        assert "logger.error" in src[i:i + 1600], (
            "une verification silencieusement absente laisserait croire les "
            "empreintes valides")

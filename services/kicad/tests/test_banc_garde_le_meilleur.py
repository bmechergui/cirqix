"""Un tirage rate ne doit pas JETER les tirages reussis qui le precedent.

⚠️ Mesure du 2026-08-31, `stm32-100`, banc a trois tirages :

    tirage 1  ->  99 %, 1 connexion manquante, 0 erreur DRC
    tirage 2  ->  99 %, 1 connexion manquante, 0 erreur DRC
    tirage 3  ->  ECHEC (tous les tirages de routage ont stagne)

    resultat annonce :  ECHEC

Deux boards livrables mesures, et le banc rend « ECHEC ». La cause tient en
deux lignes de `_passer` :

    r = _un_tirage(circuit, sortie)
    if "erreur" in r:
        return r            # <- rend l erreur, jette le meilleur deja acquis

Sa propre docstring dit pourtant « garde le MEILLEUR board ». Le board a 99 %
etait sur le disque, intact : 2 couches, 0 erreur DRC, 647 segments, 141 vias.

⚠️ C est la meme faute que celles corrigees toute la nuit — un bon resultat
mesure puis jete — et elle est ici dans l INSTRUMENT de mesure, ce qui la rend
pire : elle fait conclure a l echec d une chaine qui a reussi.

Un echec ne doit primer que s il n y a RIEN d autre. Et il doit rester dit :
taire les tirages rates ferait croire a une chaine plus stable qu elle n est.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT / "scripts"))

import banc_exemples as B  # noqa: E402


def _ok(erreurs: int, manquantes: int) -> dict:
    return {"erreurs": erreurs, "manquantes": manquantes, "routed_percent": 99}


def _ko(motif: str = "tous les tirages ont stagne") -> dict:
    return {"etape": "routage", "erreur": motif}


def _rejouer(suite, tmp_path, tirages=3):
    """Fait tourner `_passer` avec une suite de resultats imposee."""
    reste = list(suite)
    B._un_tirage = lambda circuit, sortie: reste.pop(0)
    return B._passer({}, tmp_path, tirages)


class TestEchecTardif:
    def test_un_echec_final_ne_jette_pas_un_bon_tirage(self, tmp_path, monkeypatch):
        # LE CAS MESURE.
        monkeypatch.setattr(B, "_un_tirage", None, raising=False)
        r = _rejouer([_ok(0, 1), _ok(0, 1), _ko()], tmp_path)
        assert "erreur" not in r, "le banc a jete deux boards livrables"
        assert (r["erreurs"], r["manquantes"]) == (0, 1)

    def test_un_echec_au_MILIEU_ne_bloque_pas_la_suite(self, tmp_path, monkeypatch):
        # Sortir au premier echec privait aussi des tirages suivants, qui
        # peuvent etre les meilleurs — le placement est stochastique.
        monkeypatch.setattr(B, "_un_tirage", None, raising=False)
        r = _rejouer([_ko(), _ok(0, 0), _ko()], tmp_path)
        assert (r["erreurs"], r["manquantes"]) == (0, 0)

    def test_un_echec_PREMIER_ne_condamne_pas_le_cas(self, tmp_path, monkeypatch):
        monkeypatch.setattr(B, "_un_tirage", None, raising=False)
        r = _rejouer([_ko(), _ok(1, 3)], tmp_path, tirages=2)
        assert (r["erreurs"], r["manquantes"]) == (1, 3)


class TestEchecTotal:
    def test_si_TOUT_echoue_l_echec_est_rendu(self, tmp_path, monkeypatch):
        # Ne jamais fabriquer un succes : c est l autre moitie de la regle.
        monkeypatch.setattr(B, "_un_tirage", None, raising=False)
        r = _rejouer([_ko("a"), _ko("b"), _ko("c")], tmp_path)
        assert "erreur" in r

    def test_l_echec_rendu_est_le_PREMIER_rencontre(self, tmp_path, monkeypatch):
        # Le premier porte la cause d origine ; les suivants en decoulent
        # souvent (JVM degradee, budget entame).
        monkeypatch.setattr(B, "_un_tirage", None, raising=False)
        r = _rejouer([_ko("cause racine"), _ko("consequence")], tmp_path, tirages=2)
        assert r["erreur"] == "cause racine"


class TestComptage:
    def test_les_tirages_rates_restent_DITS(self, tmp_path, monkeypatch):
        """⚠️ Taire les echecs ferait croire a une chaine plus stable qu elle
        n est. On garde le meilleur ET on compte les rates."""
        monkeypatch.setattr(B, "_un_tirage", None, raising=False)
        r = _rejouer([_ok(0, 1), _ko(), _ko()], tmp_path)
        assert r.get("tirages_rates") == 2

    def test_aucun_rate_compte_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(B, "_un_tirage", None, raising=False)
        r = _rejouer([_ok(0, 0)], tmp_path, tirages=1)
        assert r.get("tirages_rates") == 0


class TestArretAnticipe:
    def test_un_board_parfait_arrete_la_serie(self, tmp_path, monkeypatch):
        # (0 erreur, 0 manquante) : rien de mieux a esperer, on ne paie pas
        # les tirages restants.
        monkeypatch.setattr(B, "_un_tirage", None, raising=False)
        appels = []

        def _suite(circuit, sortie):
            appels.append(1)
            return _ok(0, 0)

        B._un_tirage = _suite
        B._passer({}, tmp_path, 3)
        assert len(appels) == 1

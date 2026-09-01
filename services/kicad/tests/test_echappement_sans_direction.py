"""Une pastille sans direction de sortie ne doit pas disparaitre en silence.

⚠️ Mesure du 2026-09-01, `nucleo-f401`, journal du banc :

    liaison GND avant routage : 1 broche(s) reliee(s) au plan sur 3 visee(s),
                                0 renoncee(s)

Une reliee, zero renoncee, trois visees : DEUX pastilles ne sont ni l un ni
l autre. Elles sortaient par ce chemin, dans `_escape_pads` :

    dx, dy = _direction_d_echappement(pad, centre)
    if (dx * dx + dy * dy) ** 0.5 < 1.0:
        continue          # <- muet, et AVANT le dernier recours

`_direction_d_echappement` rend un vecteur UNITAIRE pour une pastille allongee,
le decalage brut en nanometres pour une pastille carree, et `(0, 0)` quand la
pastille est exactement au centre du boitier. Or la convention KiCad place la
broche 1 a l origine du footprint : `J10.1`, pastille traversante ronde d un
connecteur, tombe pile dans ce cas.

TROIS DEFAUTS EN UN :

  ① la pastille est abandonnee AVANT le dernier recours — le via DANS la
     pastille, qui ne demande justement AUCUNE direction laterale. C est le
     seul cas ou ce recours est la bonne reponse, et c est celui qu on saute.
  ② `renonces` n est pas incremente : le bilan ne boucle pas, et un abandon
     muet est indistinguable d un travail complet.
  ③ rien n interdit de percer un via DANS une pastille DEJA percee. Un via
     dans une pastille traversante, c est un trou dans un trou — meme faute
     que les vias superposes de la couture, corriges le meme jour.

⚠️ Mesure qui cadre le remede, board `18_cousu` :

    D1.2   F.Cu hors cuivre (0,5 mm)  ·  B.Cu DANS le cuivre
    D3.2   F.Cu hors cuivre (1,0 mm)  ·  B.Cu DANS le cuivre
    J10.1  F.Cu hors cuivre (2,0 mm)  ·  B.Cu hors cuivre (0,5 mm)

`D1.2` et `D3.2` sont des pastilles CMS posees juste AU-DESSUS du plan de
B.Cu : un via dans la pastille les relie, et il herite de l isolement de la
pastille, donc sans court-circuit. `J10.1`, elle, est traversante et hors
cuivre des DEUX cotes : aucun via ne la sauvera — elle doit etre COMPTEE
comme renoncee, pas oubliee.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import routing_pcbnew_runner as RUN  # noqa: E402

MM = 1_000_000


class TestBilanQuiBoucle:
    def test_le_bilan_du_journal_mesure_est_INCOHERENT(self):
        # 3 visees, 1 posee, 0 renoncee : deux pastilles disparues.
        assert RUN._bilan_coherent(vises=3, poses=1, renonces=0) is False

    def test_un_bilan_complet_boucle(self):
        assert RUN._bilan_coherent(vises=3, poses=1, renonces=2) is True

    def test_tout_pose_boucle(self):
        assert RUN._bilan_coherent(vises=2, poses=2, renonces=0) is True

    def test_tout_renonce_boucle(self):
        assert RUN._bilan_coherent(vises=2, poses=0, renonces=2) is True

    def test_aucune_cible_boucle(self):
        assert RUN._bilan_coherent(vises=0, poses=0, renonces=0) is True

    def test_un_surplus_est_AUSSI_incoherent(self):
        # Compter deux fois la meme pastille est un defaut symetrique.
        assert RUN._bilan_coherent(vises=1, poses=1, renonces=1) is False


class TestViaDansPastille:
    """Le dernier recours, et sa seule interdiction absolue."""

    def test_une_pastille_CMS_assez_large_accepte_un_via(self):
        assert RUN._via_in_pad_possible(
            largeur_pad=0.9 * MM, via_nominal=0.6 * MM, percage_pad=0.0) > 0

    def test_une_pastille_DEJA_PERCEE_le_refuse(self):
        # ⚠️ Un via dans une pastille traversante est un trou dans un trou.
        assert RUN._via_in_pad_possible(
            largeur_pad=1.5 * MM, via_nominal=0.6 * MM, percage_pad=0.8 * MM) == 0

    def test_une_pastille_trop_etroite_le_refuse(self):
        # Le via ne doit JAMAIS depasser la pastille : plus large, il herite
        # d une clearance que le voisinage n a pas prevue.
        assert RUN._via_in_pad_possible(
            largeur_pad=0.15 * MM, via_nominal=0.6 * MM, percage_pad=0.0) == 0

    def test_il_ne_depasse_jamais_la_pastille(self):
        d = RUN._via_in_pad_possible(
            largeur_pad=0.4 * MM, via_nominal=0.6 * MM, percage_pad=0.0)
        assert 0 < d <= 0.4 * MM


class TestExecutionReelle:
    """⚠️ EXERCER la fonction, pas seulement lire son source.

    Le 2026-09-01, la premiere version de ce correctif ecrivait
    `vises = len(pads)` alors que la liste s appelle `cibles` :

        NameError: name 'pads' is not defined. Did you mean: 'pad'?

    Les quatorze tests passaient — aucun n APPELAIT `_escape_pads`. Le defaut
    n est apparu qu au banc, avale par le `except` de l appelant, qui a
    journalise « liaison GND avant routage impossible » et conserve le board.
    La lecon etait deja inscrite dans CLAUDE.md ; ce test la rend executoire.
    """

    def _board(self, *, percee: bool, au_centre: bool):
        class _P:
            def __init__(s, x, y):
                s.x, s.y = x, y

        class _Boite:
            GetLeft = staticmethod(lambda: -0.45 * MM)
            GetTop = staticmethod(lambda: -0.45 * MM)
            GetRight = staticmethod(lambda: 0.45 * MM)
            GetBottom = staticmethod(lambda: 0.45 * MM)

        class _Pad:
            def __init__(s):
                s._xy = (10 * MM, 10 * MM)

            GetPadName = staticmethod(lambda: "2")
            GetNetCode = staticmethod(lambda: 1)
            GetNetname = staticmethod(lambda: "GND")
            GetLayer = staticmethod(lambda: 0)
            GetBoundingBox = staticmethod(lambda: _Boite())
            GetDrillSizeX = staticmethod(lambda: (0.8 * MM) if percee else 0)

            def GetPosition(s):
                return _P(*s._xy)

        class _Fp:
            GetReference = staticmethod(lambda: "D3")
            Pads = staticmethod(lambda: [_Pad()])
            GetBoundingBox = staticmethod(lambda: _Boite())

            @staticmethod
            def GetPosition():
                # au centre exact -> direction (0, 0) -> le cas du defaut
                return _P(10 * MM, 10 * MM) if au_centre else _P(0, 0)

        class _Board:
            def __init__(s):
                s.ajoutes = []
            GetFootprints = staticmethod(lambda: [_Fp()])
            Footprints = staticmethod(lambda: [_Fp()])
            GetTracks = staticmethod(lambda: [])
            FindFootprintByReference = staticmethod(lambda r: _Fp())

            def Add(s, item):
                s.ajoutes.append(item)
        return _Board()

    def _lancer(self, board, tmp_path, monkeypatch):
        import json as _json

        class _Via:
            def __init__(s, b):
                pass
            SetPosition = SetWidth = SetDrill = SetNetCode = (
                lambda s, *a: None)

        class _Track:
            def __init__(s, b):
                pass
            SetStart = SetEnd = SetWidth = SetLayer = SetNetCode = (
                lambda s, *a: None)

        class _Faux:
            PCB_VIA = _Via
            PCB_TRACK = _Track
            VECTOR2I = staticmethod(lambda x, y: (x, y))
            SaveBoard = staticmethod(
                lambda c, b: Path(c).write_text("(pcb)", encoding="utf-8"))

        monkeypatch.setattr(RUN, "_charger_board", lambda p, c: board)
        monkeypatch.setattr(RUN, "_obstacles_d_un_autre_net", lambda b, n: [])
        res = tmp_path / "r.json"
        RUN._escape_pads(_Faux, {
            "pcb": str(tmp_path / "in.kicad_pcb"),
            "output": str(tmp_path / "out.kicad_pcb"),
            "result": str(res),
            "pads": _json.dumps([["D3", "2"]]),
        })
        return _json.loads(res.read_text(encoding="utf-8"))

    def test_elle_s_execute_sans_lever(self, tmp_path, monkeypatch):
        bilan = self._lancer(self._board(percee=False, au_centre=True),
                             tmp_path, monkeypatch)
        assert "vises" in bilan

    def test_le_bilan_BOUCLE_toujours(self, tmp_path, monkeypatch):
        for percee in (False, True):
            bilan = self._lancer(self._board(percee=percee, au_centre=True),
                                 tmp_path, monkeypatch)
            assert RUN._bilan_coherent(
                bilan["vises"], bilan["escaped"], bilan["renonces"]), bilan

    def test_une_pastille_CMS_au_centre_est_RELIEE_par_un_via(self, tmp_path,
                                                             monkeypatch):
        # Le cas que le `continue` muet sautait.
        bilan = self._lancer(self._board(percee=False, au_centre=True),
                             tmp_path, monkeypatch)
        assert bilan["escaped"] == 1 and bilan["renonces"] == 0

    def test_une_pastille_PERCEE_au_centre_est_RENONCEE_pas_oubliee(
            self, tmp_path, monkeypatch):
        # J10.1 : un via dans un trou n a aucun sens — mais elle doit compter.
        bilan = self._lancer(self._board(percee=True, au_centre=True),
                             tmp_path, monkeypatch)
        assert bilan["escaped"] == 0 and bilan["renonces"] == 1


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "routing_pcbnew_runner.py").read_text(
        encoding="utf-8")

    def _corps(self) -> str:
        i = self.SOURCE.index("def _escape_pads(")
        return self.SOURCE[i:self.SOURCE.index(chr(10) + "def ", i + 1)]

    def test_plus_aucun_abandon_MUET_sur_l_absence_de_direction(self):
        # ⚠️ La garde qui manquait. Un `continue` sans comptage rendait
        # « 0 renoncee » sur deux pastilles abandonnees.
        # ⚠️ Sur le CODE seul. Une premiere version de cette garde cherchait le
        # mot dans la fenetre brute et tombait sur le commentaire qui explique
        # le defaut — elle mesurait la prose. Deuxieme fois dans la journee.
        corps = self._corps()
        i = corps.index("_direction_d_echappement(")
        code = [l for l in corps[i:i + 900].split(chr(10))
                if not l.strip().startswith("#")]
        assert not any(l.strip() == "continue" for l in code), (
            "l absence de direction fait encore sortir la pastille en silence")

    def test_le_bilan_est_verifie_avant_d_etre_rendu(self):
        assert "_bilan_coherent(" in self._corps()

    def test_le_nombre_de_VISEES_est_rendu(self):
        # Sans lui, l appelant ne peut pas verifier que le bilan boucle.
        assert '"vises"' in self._corps()

    def test_le_dernier_recours_passe_par_la_regle(self):
        assert "_via_in_pad_possible(" in self._corps()

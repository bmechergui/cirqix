"""Ne pas confier au round-trip Specctra des pistes qu il detruit aussitot.

⚠️ REGRESSION DU 2026-09-01, `esp32-baseline` : le processus enfant pcbnew
meurt en `exit -11` (SIGSEGV) a l import de session. Zero occurrence dans le
temoin des 8 cartes.

La chaine causale, etablie par LECTURE du code :

    `_specctra_roundtrip` commence par `for track in list(board.GetTracks()):
    board.Remove(track)` — il DETRUIT toutes les pistes avant d importer la
    session. Or dans le temoin, tout board remis au round-trip etait un board
    PLACE, qui ne porte aucune piste : la boucle ne s executait jamais et
    `board.Remove()` n avait JAMAIS ete appele une seule fois.

    L etape ③ (`_relier_gnd_avant_routage`) pose une piste et un via avant le
    routage. Elle a rendu cette liste non vide pour la premiere fois — et le
    plantage est apparu la meme fois.

⚠️ CE QUI N EST PAS PROUVE : que `board.Remove()` soit la ligne fautive. La
mesure exige le conteneur, indisponible. Ce qui EST etabli : l operation n
avait jamais tourne avant la carte qui plante, et les pistes qu on lui confie
sont detruites a la ligne suivante — donc les envoyer ne sert a RIEN.

⚠️ L assertion `m_choices.GetCount() > 0 ... No enum choices defined` qui
accompagne le plantage est un DEFAUT CONNU DE KICAD (issue #13699) : elle est
emise a l IMPORT du module pcbnew en environnement headless, dans tous les
enfants. Elle n est visible que quand un enfant echoue, parce que nous n
affichons sa sortie d erreur que dans ce cas. Ce n est pas un diagnostic, c est
du bruit — et je l avais d abord lue comme la cause.

On retire donc les pistes AVANT d entrer dans pcbnew, textuellement. Le
resultat est identique par construction.

⚠️ VALIDE PAR KICAD LUI-MEME, sur deux boards REELS du depot, avec
`kicad-cli pcb drc --format json` (KiCad 10.99). Le controle qui compte est
d abord que le board CHARGE : un board refuse rend `rc=0` et un rapport vide,
que ce projet a deja lu « 0 erreur » une fois.

    board                        violations   erreurs   non connecte
    stm32 (KiCad 10, keepout)      30 -> 25     0 -> 0      0 -> 26
    led-blinker                    20 -> 16    10 -> 6      7 -> 14

    types de violation en hausse : AUCUN, sur les deux boards

Les violations BAISSENT — le cuivre retire emporte ses propres defauts — et
les liaisons non connectees MONTENT, ce qui est exactement l effet attendu du
retrait d un routage. Aucun type nouveau n apparait : la chirurgie fait ce qu
elle annonce et rien d autre.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402

LF = chr(10).encode()

SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

_AVEC_PISTES = b"""(kicad_pcb
  (net 0 "")
  (net 1 "GND")
  (footprint "R_0402"
    (pad "1" smd rect (at 0 0) (net 1 "GND"))
  )
  (segment
    (start 10.0 20.0)
    (end 30.0 40.0)
    (width 0.2)
    (layer "F.Cu")
    (uuid "0534a101-8ddc-4719-81f3-8dd4fd034ada")
    (net 1)
  )
  (via
    (at 30.0 40.0)
    (size 0.6)
    (drill 0.3)
    (layers "F.Cu" "B.Cu")
    (net 1)
  )
  (zone (net 1) (net_name "GND") (layer "F.Cu"))
)"""


class TestRetraitDesPistes:
    def test_les_segments_et_vias_partent(self):
        sortie = R._sans_pistes(_AVEC_PISTES)
        assert b"(segment" not in sortie
        assert b"(via" not in sortie

    def test_le_reste_du_board_est_INTACT(self):
        # ⚠️ Un retrait qui emporte les footprints, les nets ou les zones
        # serait bien pire que le plantage qu il evite.
        sortie = R._sans_pistes(_AVEC_PISTES)
        assert b'(footprint "R_0402"' in sortie
        assert b'(net 1 "GND")' in sortie
        assert b'(zone (net 1)' in sortie
        assert b'(pad "1" smd rect' in sortie

    def test_un_board_sans_piste_est_rendu_INCHANGE(self):
        # Cas le plus frequent : un board place. Ne rien reecrire inutilement.
        nu = b'(kicad_pcb (net 1 "GND"))'
        assert R._sans_pistes(nu) == nu

    def test_les_nets_survivent(self):
        assert R._nets_du_board(R._sans_pistes(_AVEC_PISTES)) == {"", "GND"}


class TestPiegeDeForme:
    """⚠️ `(vias allowed)` d un keepout COMMENCE par `(via`.

    Un retrait ancre sur le simple prefixe emporterait ce jeton et corromprait
    la zone d exclusion — un degat bien pire que le plantage evite. Le projet a
    deja paye onze pieges de forme de cette famille ; celui-ci a ete vu avant
    d etre livre, pas apres.
    """

    KEEPOUT = (
        b'(kicad_pcb' + LF
        + b'  (zone (net 0) (net_name "") (layer "F.Cu")' + LF
        + b'    (keepout (tracks allowed) (vias allowed) (pads allowed)' + LF
        + b'      (copperpour not_allowed) (footprints allowed))' + LF
        + b'  )' + LF
        + b')')

    def test_un_keepout_survit_intact(self):
        assert R._sans_pistes(self.KEEPOUT) == self.KEEPOUT

    def test_le_jeton_vias_allowed_n_est_pas_emporte(self):
        assert b'(vias allowed)' in R._sans_pistes(self.KEEPOUT)

    def test_un_vrai_via_part_quand_meme(self):
        melange = (self.KEEPOUT[:-1]
                   + b'  (via (at 1 2) (size 0.6) (drill 0.3) (net 1))' + LF
                   + b')')
        sortie = R._sans_pistes(melange)
        assert b'(vias allowed)' in sortie
        assert b'(via (at' not in sortie


class TestCablage:
    def test_le_roundtrip_ne_recoit_plus_de_pistes(self):
        # ⚠️ Garde de CABLAGE : un retrait correct que personne n appelle est
        # indistinguable d un retrait absent.
        i = SOURCE.index("def _specctra_roundtrip(")
        appels = [b for b in SOURCE.split("_specctra_roundtrip(")[1:]]
        # On ignore la definition elle-meme (son entete commence par pcb_bytes)
        vrais = [a for a in appels if not a.lstrip().startswith("pcb_bytes: bytes")]
        assert vrais, "aucun appel trouve"
        for a in vrais:
            assert a.lstrip().startswith("_sans_pistes("), (
                "un appel confie encore ses pistes au round-trip : %r" % a[:60])

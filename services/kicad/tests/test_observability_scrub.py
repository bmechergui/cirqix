"""Ce qui ne doit JAMAIS partir chez un tiers.

Sentry recoit ce qu'on lui donne. Ce service manipule des schemas, des boards
et des Gerbers — la propriete intellectuelle du client, en base64 dans les corps
de requete. Une erreur de routage ne doit pas l'exfiltrer.

Le risque particulier de cette classe de defaut : elle ne casse rien. Tout
continue de fonctionner pendant que les circuits partent. Rien ne le
signalerait — d'ou ces tests.
"""

from __future__ import annotations

import pytest

from observability import (
    MAX_STRING_LENGTH,
    REDACTED,
    init_sentry,
    scrub,
    scrub_event,
)


@pytest.mark.parametrize(
    "key",
    ["kicad_pcb_b64", "kicad_sch_b64", "gerber_zip_b64", "bom_csv", "netlist", "schema"],
)
def test_expurge_les_charges_utiles_kicad(key: str) -> None:
    assert scrub({key: "contenu confidentiel"})[key] == REDACTED


@pytest.mark.parametrize("key", ["authorization", "cookie", "kicad_service_token"])
def test_expurge_les_secrets(key: str) -> None:
    assert scrub({key: "valeur"})[key] == REDACTED


def test_insensible_a_la_casse() -> None:
    assert scrub({"Authorization": "Bearer x"})["Authorization"] == REDACTED


def test_atteint_les_champs_imbriques() -> None:
    out = scrub({"contexts": {"req": {"route": "/route/auto", "kicad_pcb_b64": "AAAA"}}})

    assert out["contexts"]["req"]["kicad_pcb_b64"] == REDACTED
    assert out["contexts"]["req"]["route"] == "/route/auto"


def test_traverse_les_listes() -> None:
    out = scrub([{"kicad_sch_b64": "x"}, {"step": "drc"}])

    assert out[0]["kicad_sch_b64"] == REDACTED
    assert out[1]["step"] == "drc"


def test_tronque_une_chaine_longue_au_nom_inconnu() -> None:
    """LA barriere qui compte sur la duree.

    La liste de noms est aveugle a ce qui n'existe pas encore : un champ ajoute
    dans six mois passerait. Sa taille, non.
    """
    blob = "A" * 50_000

    out = scrub({"champ_invente_plus_tard": blob})

    assert len(out["champ_invente_plus_tard"]) < 700
    assert "tronque" in out["champ_invente_plus_tard"]
    assert "50000" in out["champ_invente_plus_tard"]


def test_laisse_intact_un_message_d_erreur_normal() -> None:
    msg = "OSError [Errno 9] Bad file descriptor dans _write_routed_pcb"

    assert scrub({"message": msg})["message"] == msg


def test_ne_tronque_pas_juste_sous_le_seuil() -> None:
    juste = "B" * MAX_STRING_LENGTH

    assert scrub({"m": juste})["m"] == juste


def test_ne_modifie_pas_la_source() -> None:
    source = {"kicad_pcb_b64": "AAAA", "step": "routing"}

    scrub(source)

    assert source["kicad_pcb_b64"] == "AAAA"


def test_resiste_a_une_structure_profonde() -> None:
    deep: dict = {"kicad_pcb_b64": "secret"}
    for _ in range(50):
        deep = {"nested": deep}

    scrub(deep)  # ne doit pas exploser


def test_scrub_event_supprime_en_bloc_entetes_cookies_et_corps() -> None:
    event = {
        "request": {
            "url": "http://kicad:8000/route/auto",
            "headers": {"authorization": "Bearer secret"},
            "cookies": "session=…",
            "data": {"kicad_pcb_b64": "AAAA"},
        }
    }

    out = scrub_event(event)

    assert "headers" not in out["request"]
    assert "cookies" not in out["request"]
    assert "data" not in out["request"]
    assert out["request"]["url"] == "http://kicad:8000/route/auto"


def test_scrub_event_conserve_ce_qui_rend_une_alerte_exploitable() -> None:
    out = scrub_event({"extra": {"route": "/drc/auto", "status": 500, "kicad_pcb_b64": "AAAA"}})

    assert out["extra"]["route"] == "/drc/auto"
    assert out["extra"]["status"] == 500
    assert out["extra"]["kicad_pcb_b64"] == REDACTED


def test_scrub_event_abandonne_plutot_que_d_envoyer_non_filtre() -> None:
    """Perdre une alerte est moins grave qu'exfiltrer un schema client."""

    class Explosif(dict):
        def items(self):  # noqa: ANN201
            raise RuntimeError("boom")

    assert scrub_event(Explosif()) is None


def test_desactive_sans_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sans SENTRY_DSN : aucun reseau, aucune donnee qui sort."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    assert init_sentry() is False


def test_expurge_les_binaires() -> None:
    """Les ``bytes`` ne partent jamais, meme tronques.

    Ils tombaient jusqu'au ``return value`` final : ni la barriere par nom (la
    valeur n'est pas un dict) ni celle par taille (``len`` n'etait teste que
    pour ``str``) ne s'appliquait. C'est par la que ``pcb_bytes`` sortait.
    """
    out = scrub({"payload": b"(kicad_pcb SECRET)" * 1000})

    assert "SECRET" not in str(out["payload"])
    assert "octets binaires" in out["payload"]


@pytest.mark.parametrize(
    "key", ["pcb_bytes", "zip_bytes", "pcb_content", "updated_b64", "sch_data_b64"]
)
def test_expurge_les_noms_de_VARIABLES_du_code_pas_seulement_ceux_de_l_API(key: str) -> None:
    """L'egalite exacte listait les champs d'API ; le code, lui, nomme
    autrement. Aucun de ces noms n'etait couvert, et le board partait."""
    assert scrub({key: "(kicad_pcb SECRET)"})[key] == REDACTED


def test_le_sdk_reel_ne_laisse_pas_fuir_un_board_par_les_variables_locales() -> None:
    """LA garde de ce module — et la seule qui exerce le SDK reel.

    Le SDK Python capture PAR DEFAUT les variables locales de chaque frame
    (``include_local_variables=True``). Mesure du 2026-08-12 avec la
    configuration d'alors : ``SECRET_NET present dans l evenement : True``,
    ``frame export_gerbers -> vars: ['pcb_bytes', 'zip_bytes']``.

    Le filtre par nom ne pouvait rien : ces variables ne portent pas les noms
    des champs d'API. Aucun test ne l'aurait vu — tous exercaient ``scrub`` sur
    des objets construits a la main, jamais le pipeline reel du SDK.

    Ce test leve une vraie exception dans une fonction tenant un board en
    variable locale, et verifie ce qui SORT.
    """
    sentry_sdk = pytest.importorskip("sentry_sdk")

    captured: list[dict] = []
    sentry_sdk.init(
        dsn="https://x@example.invalid/1",
        transport=captured.append,
        traces_sample_rate=0.0,
        send_default_pii=False,
        before_send=scrub_event,
        max_request_body_size="never",
        include_local_variables=False,
        server_name=None,
    )

    # Marqueur genere A L'EXECUTION, jamais ecrit dans ce fichier.
    #
    # Un marqueur litteral rendait ce test faussement rouge : Sentry envoie les
    # LIGNES DE CODE SOURCE des frames (``context_line``, ``pre_context``), donc
    # il retrouvait le marqueur dans la source du test lui-meme, pas dans les
    # donnees. Constat au passage : une valeur sensible ecrite en dur dans un
    # fichier source PARTIRAIT chez Sentry — argument de plus contre les
    # secrets en dur.
    import uuid

    marker = uuid.uuid4().hex
    board = f'(kicad_pcb (net 1 "{marker}") ' + "X" * 40_000 + ")"

    def export_gerbers() -> None:
        pcb_bytes = board.encode()  # noqa: F841 — nom reel de export.py
        zip_bytes = b"PK\x03\x04" + board.encode()  # noqa: F841 — reel de export.py
        raise RuntimeError("echec de zip")

    try:
        export_gerbers()
    except RuntimeError:
        sentry_sdk.capture_exception()
    sentry_sdk.flush()

    import json

    blob = json.dumps(captured, default=str)
    assert marker not in blob, "le board a fuite dans l evenement Sentry"

    # Ce qui rend l'alerte exploitable doit survivre au filtre : sans cela on
    # aurait un module qui protege parfaitement en n'envoyant plus rien d'utile.
    assert "echec de zip" in blob
    assert "export_gerbers" in blob

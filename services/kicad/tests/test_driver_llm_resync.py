"""Le driver manuel doit RESYNCHRONISER avant d'annoncer un pourcentage.

⚠️ MESURE DU 2026-09-05, sur `examples/stm32-baseline/output/2_placement.kicad_pcb`.
Dix-sept commandes jouees par le driver — deux plans de masse, quinze signaux —
et le resume final annoncait :

    === PROGRESS: routed 0/16 | violations 0 (init 0) ===

Le board ecrit portait pourtant **62 segments de cuivre et 10 vias**, contre
zero au depart. Les commandes avaient reussi une par une (« Routed VIN: 1
connections, 28.1mm »), et le compteur global disait le contraire.

Cause : l'interpreteur ecrit les pistes dans l'editeur mais ne remet PAS a jour
`PCBState.nets[*].traces` ; `NetState.is_routed` reste donc False en session.

⚠️ **LE SERVICE CORRIGE CE DEFAUT DEPUIS LE COMMIT `34be8ae`** (juin 2026,
`tools/reasoning.py::_refresh_agent`), precisement parce qu'un LLM pilote par ce
compteur boucle jusqu'a `max_steps` en croyant n'avoir rien fait. Le driver
MANUEL, lui, n'avait jamais recu le correctif : il rendait le meme chiffre faux
a l'humain qui joue le role du LLM — et c'est ce driver que `CLAUDE.md` designe
pour la validation manuelle du reasoner.

Apres correction, memes commandes, meme board : **8/16 routes**.

⚠️ NEVER croire un compteur de progression sans regarder le board. Ce depot l'a
deja paye avec le rapport DRC vide lu « 0 erreur », et avec les nets Kicad 10
comptes a zero par une regex trop stricte.
"""
from __future__ import annotations

import ast
from pathlib import Path

_DRIVER = Path(__file__).resolve().parents[1] / "scripts" / "driver_llm.py"


def _source() -> str:
    return _DRIVER.read_text(encoding="utf-8")


def _fonction(nom: str) -> ast.FunctionDef:
    arbre = ast.parse(_source())
    for noeud in arbre.body:
        if isinstance(noeud, ast.FunctionDef) and noeud.name == nom:
            return noeud
    raise AssertionError("fonction %s absente de driver_llm.py" % nom)


def test_le_driver_expose_une_resynchronisation() -> None:
    """Sans elle, le pourcentage rendu est structurellement sous-evalue."""
    _fonction("_resync")


def test_la_resynchronisation_recharge_depuis_le_board() -> None:
    """Recharger est le seul moyen de re-deriver `is_routed` depuis le cuivre."""
    corps = ast.get_source_segment(_source(), _fonction("_resync")) or ""
    assert "PCBReasoningAgent.from_pcb" in corps, (
        "la resynchronisation ne relit pas le board — elle ne corrige rien")
    assert "agent.save" in corps, (
        "le board doit etre ECRIT avant d etre relu, sinon on recharge l ancien")


def test_la_resynchronisation_preserve_le_journal() -> None:
    """⚠️ `history` porte le journal d actions que le LLM relit au tour suivant.

    Le perdre ferait recommencer au LLM ce qu il vient de faire — un
    rafraichissement qui efface la memoire coute plus qu il ne rapporte.
    """
    corps = ast.get_source_segment(_source(), _fonction("_resync")) or ""
    for champ in ("history", "step_count", "initial_unrouted", "initial_violations"):
        assert champ in corps, "la resynchronisation perd `%s`" % champ


def test_la_mesure_vient_APRES_la_resynchronisation() -> None:
    """Le cablage : resynchroniser sans mesurer ensuite ne sert a rien.

    ⚠️ Une regle correcte mais appelee au mauvais moment est indistinguable
    d une regle absente — la lecon du snap, qui devait passer APRES le Geometre.
    """
    corps = ast.get_source_segment(_source(), _fonction("main")) or ""
    i_resync = corps.find("_resync(")
    i_mesure = corps.find("get_progress()")
    assert i_resync != -1, "`main` ne resynchronise pas"
    assert i_mesure != -1, "`main` ne mesure pas la progression"
    assert i_resync < i_mesure, (
        "la progression est lue AVANT la resynchronisation : le chiffre reste faux")

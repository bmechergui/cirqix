"""
Layrix — Reasoning LLM (sauvetage de routage agentique)

Quand le routeur classique (`kct route`) laisse des nets bloqués, on confie la
carte au reasoner LLM officiel de kicad-tools (`PCBReasoningAgent`) piloté par
Claude Haiku : boucle get_prompt → Claude décide une commande JSON → execute.

Les algos classiques (A*) font ~90% du travail ; le LLM ne traite que les ~10%
de corner cases (pin enterré, canal bloqué par un composant). Borné par
max_steps + budget tokens pour respecter le coût cible.

Nécessite `anthropic` + ANTHROPIC_API_KEY. `available()` indique si utilisable.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Haiku 4.5 — agent spécialisé, coût optimisé (cf. CLAUDE.md)
_MODEL = "claude-haiku-4-5-20251001"
_MAX_STEPS = 15

_SYSTEM_PROMPT = """\
Tu es un ingénieur routage PCB. À chaque tour tu reçois l'état d'une carte KiCad \
et tu réponds par UNE commande JSON pour progresser vers : tous les nets routés, \
0 violation DRC.

Commandes disponibles (réponds UNIQUEMENT par l'objet JSON, rien d'autre) :
- {"type":"route_net","net":"NOM"[,"avoid_regions":[],"prefer_layer":"F.Cu"]}
- {"type":"place_component","ref":"R1","near":"U1","offset":[2,0]}  ou  {"ref":"R1","at":[x,y]}
- {"type":"add_via","net":"NOM","position":[x,y]}
- {"type":"delete_trace","net":"NOM"}
- {"type":"define_zone","net":"GND","layer":"F.Cu"}

Stratégie : route d'abord les nets simples ; si un net est bloqué par un \
composant, déplace ce composant de quelques mm (place_component) pour libérer un \
canal, puis route. Réponds par le JSON de la commande la plus utile maintenant."""


def available() -> bool:
    """True si le reasoner LLM peut tourner (SDK anthropic + clé présents)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def _extract_json(text: str) -> dict | None:
    """Extrait le premier objet JSON d'une réponse LLM (tolère le texte autour)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def route_with_llm(pcb_bytes: bytes, max_steps: int = _MAX_STEPS,
                   model: str = _MODEL) -> tuple[bytes, int]:
    """Sauvetage de routage par le reasoner LLM (Claude + PCBReasoningAgent).

    Retourne (pcb_bytes, routed_percent). Lève si anthropic/clé absents ou si
    l'agent échoue à charger.
    """
    import anthropic
    from kicad_tools.reasoning import PCBReasoningAgent

    with tempfile.TemporaryDirectory() as tmp:
        board = Path(tmp) / "board.kicad_pcb"
        out = Path(tmp) / "out.kicad_pcb"
        board.write_bytes(pcb_bytes)

        agent = PCBReasoningAgent.from_pcb(str(board))
        client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY

        for step in range(max_steps):
            if agent.is_complete():
                logger.info("reasoner LLM: complet après %d étapes", step)
                break

            prompt = agent.get_prompt()
            try:
                resp = client.messages.create(
                    model=model,
                    max_tokens=512,
                    system=[{"type": "text", "text": _SYSTEM_PROMPT,
                             "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": prompt}],
                )
            except Exception as exc:
                logger.warning("reasoner LLM: appel Claude échoué (%s) — stop", exc)
                break

            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            command = _extract_json(text)
            if not command:
                logger.warning("reasoner LLM: pas de JSON dans la réponse — stop")
                break

            try:
                result, diagnosis = agent.execute_dict(command)
                logger.info("reasoner LLM étape %d: %s → %s",
                            step + 1, command.get("type"),
                            "OK" if result.success else f"échec ({diagnosis or ''[:60]})")
            except Exception as exc:
                logger.warning("reasoner LLM: commande invalide (%s) — continue", exc)
                continue

        agent.save(str(out))
        prog = agent.get_progress()
        pct = round(prog.nets_routed / prog.nets_total * 100) if prog.nets_total else 100
        return out.read_bytes(), pct

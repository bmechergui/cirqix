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


def _claude_decider(model: str, system: str = _SYSTEM_PROMPT):
    """Décideur par défaut : un appel Claude (Haiku) → une commande JSON dict.

    Isolé pour permettre l'injection d'un décideur déterministe dans les tests
    (sans ANTHROPIC_API_KEY). ``system`` permet de restreindre le vocabulaire
    (boucle placement-feedback : place_component/delete_trace uniquement).
    """
    import anthropic

    client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY

    def decide(prompt: str) -> dict | None:
        resp = client.messages.create(
            model=model,
            max_tokens=512,
            system=[{"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return _extract_json(text)

    return decide


def _refresh_agent(agent, board: Path):
    """Resynchronise l'état de l'agent depuis le board sauvegardé.

    L'interpréteur écrit les pistes routées dans l'éditeur mais NE remet PAS à
    jour ``PCBState.nets[*].traces`` ; ``NetState.is_routed`` (= traces présentes)
    reste donc False en session → ``get_progress``/``is_complete``/``unrouted_nets``
    périmés (pct sous-évalué, boucle qui ne s'arrête jamais). Recharger re-dérive
    ces champs depuis le board. ``history`` est préservé pour que le LLM garde son
    journal d'actions au prompt suivant. Coût négligeable : reasoner = ~10% corner
    cases, max_steps bornés, parsing < appel Claude.
    """
    from kicad_tools.reasoning import PCBReasoningAgent

    agent.save(str(board))
    fresh = PCBReasoningAgent.from_pcb(str(board))
    fresh.history = agent.history
    fresh.step_count = agent.step_count
    fresh.initial_unrouted = agent.initial_unrouted
    fresh.initial_violations = agent.initial_violations
    return fresh


def route_with_llm(pcb_bytes: bytes, max_steps: int = _MAX_STEPS,
                   model: str = _MODEL, *,
                   decide=None) -> tuple[bytes, int, list[str]]:
    """Sauvetage de routage par le reasoner LLM (Claude + PCBReasoningAgent).

    ⚠ Conservé volontairement (pas de caller en prod) : mode "full LLM" où le
    LLM route lui-même — utile en debug manuel et comme filet si la boucle
    placement-feedback (``rescue_with_placement_feedback``, voie primaire de
    /reason/auto) devait être désactivée. Voir examples/stm32-validation pour
    la comparaison des deux approches (22% full-LLM-router vs 92% feedback).

    Retourne (pcb_bytes, routed_percent, steps_log). ``steps_log`` décrit chaque
    action IA en français pour l'affichage UI/SSE. ``decide`` est le décideur
    (prompt → commande dict) ; par défaut Claude Haiku (nécessite la clé).
    """
    from kicad_tools.reasoning import PCBReasoningAgent

    steps_log: list[str] = []
    if decide is None:
        decide = _claude_decider(model)

    with tempfile.TemporaryDirectory() as tmp:
        board = Path(tmp) / "board.kicad_pcb"
        out = Path(tmp) / "out.kicad_pcb"
        board.write_bytes(pcb_bytes)

        agent = PCBReasoningAgent.from_pcb(str(board))

        for step in range(max_steps):
            if agent.is_complete():
                steps_log.append(f"✓ Routage complet après {step} action(s) IA")
                break

            prompt = agent.get_prompt()
            try:
                command = decide(prompt)
            except Exception as exc:
                logger.warning("reasoner LLM: décision échouée (%s) — stop", exc)
                steps_log.append(f"⚠ Appel IA échoué : {exc}")
                break

            if not command:
                steps_log.append("⚠ Pas de commande exploitable — arrêt")
                break

            try:
                result, _diagnosis = agent.execute_dict(command)
            except Exception:
                steps_log.append(f"⚠ Commande invalide ({command.get('type')}) — ignorée")
                continue

            ok = "✓" if result.success else "✗"
            desc = _describe(command)
            steps_log.append(f"{ok} {desc}")
            logger.info("reasoner LLM étape %d: %s", step + 1, desc)

            if result.success:
                # Resynchronise l'état (cf. _refresh_agent) : sans ça is_complete
                # reste False et le pct final est sous-évalué malgré un board routé.
                agent = _refresh_agent(agent, board)

        agent.save(str(out))
        prog = agent.get_progress()
        pct = round(prog.nets_routed / prog.nets_total * 100) if prog.nets_total else 100
        return out.read_bytes(), pct, steps_log


# ---------------------------------------------------------------------------
# Boucle placement-feedback — le LLM déplace, kct route reroute
# (validée sur examples/stm32-validation : 22% → 92% en déplaçant D1/R2)
# ---------------------------------------------------------------------------

_MAX_ITERATIONS = 3
_MAX_MOVES_PER_ITER = 4
_ALLOWED_FEEDBACK_COMMANDS = frozenset({"place_component", "delete_trace"})

_PLACEMENT_SYSTEM_PROMPT = """\
Tu es un ingénieur placement PCB. Le routeur automatique a échoué sur certains \
nets : son analyse d'échec t'indique QUELS composants bloquent QUELS chemins.

Ton SEUL levier est le placement. À chaque tour, réponds par UNE commande JSON \
(rien d'autre) :
- {"type":"place_component","ref":"D1","at":[x,y]}  ou  {"ref":"D1","near":"U1","offset":[3,0]}
- {"type":"delete_trace","net":"NOM","delete_all_routing":true}

INTERDIT : route_net, add_via, define_zone — le routage appartient au routeur \
négocié qui repassera après tes déplacements.

Stratégie : suis les suggestions du routeur (« Move D1 north… ») ; déplace les \
petits composants (R, C, D) hors des couloirs bloqués, de quelques mm seulement ; \
n'empile jamais deux composants. Si plus rien d'utile à déplacer, réponds null."""


_ROUTING_BLOCK_RE = re.compile(r'\n\s*\((segment|via|zone)[\s\n]')


def _strip_routing(pcb_bytes: bytes) -> tuple[bytes, dict[str, int]]:
    """Retire tous les blocs ``(segment|via|zone …)`` d'un .kicad_pcb.

    kct route ne sait pas ripper le routage existant : les anciennes pistes,
    vias et zones deviennent des obstacles durs pour sa passe from-scratch
    (mesuré le 2026-06-10 sur stm32-validation : 33 % avec routage résiduel,
    89 % une fois dé-routé, placement identique). La boucle placement-feedback
    dé-route donc TOUT avant chaque re-route ; kct route re-coule les zones
    power lui-même.

    Scan à parenthèses équilibrées, insensible aux parenthèses dans les
    chaînes quotées (net names KiCad type ``"Net-(U1-X)"``).
    Renvoie (nouveau board, comptes par type) — l'entrée n'est jamais modifiée.
    """
    text = pcb_bytes.decode("utf-8")
    counts = {"segment": 0, "via": 0, "zone": 0}
    out: list[str] = []
    i = 0
    while True:
        m = _ROUTING_BLOCK_RE.search(text, i)
        if not m:
            out.append(text[i:])
            break
        out.append(text[i:m.start()])
        j = text.index("(", m.start())
        depth, in_str = 0, False
        while True:
            if j >= len(text):
                raise ValueError(
                    f"_strip_routing: parenthèses non équilibrées dans le bloc "
                    f"({m.group(1)} à l'offset {m.start()} — .kicad_pcb malformé")
            c = text[j]
            if in_str:
                if c == "\\":
                    j += 1
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        counts[m.group(1)] += 1
        i = j + 1
    return "".join(out).encode("utf-8"), counts


def rescue_with_placement_feedback(
    pcb_bytes: bytes,
    *,
    route_fn,
    max_iterations: int = _MAX_ITERATIONS,
    max_moves_per_iter: int = _MAX_MOVES_PER_ITER,
    decide=None,
    model: str = _MODEL,
) -> tuple[bytes, int, list[str]]:
    """Sauvetage de routage : le LLM DÉPLACE, le vrai routeur ROUTE.

    Boucle (max ``max_iterations``) :
      1. dé-routage COMPLET du board (``_strip_routing`` — kct route ne rippe
         pas l'existant : pistes/vias/zones résiduels = obstacles durs) ;
      2. ``route_fn(pcb) -> (routed_bytes, pct, failure_analysis)`` — routeur
         négocié complet (kct route), from scratch ;
      3. si pct = 100 → terminé ; sinon le LLM décide jusqu'à
         ``max_moves_per_iter`` déplacements (place_component / delete_trace
         uniquement — jamais route_net) à partir de l'analyse d'échec ;
      4. re-route au tour suivant.

    Garde anti-régression : renvoie toujours le MEILLEUR (bytes, pct) rencontré
    (les pct sont comparables entre itérations : chaque passe est un routage
    from-scratch complet des nets signaux).
    """
    from kicad_tools.reasoning import PCBReasoningAgent

    steps_log: list[str] = []
    if decide is None:
        decide = _claude_decider(model, system=_PLACEMENT_SYSTEM_PROMPT)

    best_bytes, best_pct = pcb_bytes, -1
    current = pcb_bytes

    with tempfile.TemporaryDirectory() as tmp:
        board = Path(tmp) / "board.kicad_pcb"

        for iteration in range(1, max_iterations + 1):
            stripped, counts = _strip_routing(current)
            if any(counts.values()):
                steps_log.append(
                    f"♻ Dé-routage complet avant routage ({counts['segment']} segments, "
                    f"{counts['via']} vias, {counts['zone']} zones)")
            routed, pct, analysis = route_fn(stripped)
            steps_log.append(f"Itération {iteration}/{max_iterations} : routage {pct}%")
            if pct > best_pct:
                best_bytes, best_pct = routed, pct
            if pct >= 100:
                steps_log.append(f"✓ Routage complet à l'itération {iteration}")
                break
            if iteration == max_iterations:
                break  # plus de re-routage possible — inutile de déplacer encore

            # --- Le LLM décide des déplacements sur le board routé ------------
            board.write_bytes(routed)
            agent = PCBReasoningAgent.from_pcb(str(board))

            moved_refs: list[str] = []
            for _ in range(max_moves_per_iter):
                prompt = (agent.get_prompt()
                          + "\n## Analyse d'échec du routeur\n" + analysis)
                try:
                    command = decide(prompt)
                except Exception as exc:
                    logger.warning("placement-feedback: décision échouée (%s)", exc)
                    steps_log.append(f"⚠ Appel IA échoué : {exc}")
                    return best_bytes, best_pct, steps_log
                if not command:
                    break

                ctype = command.get("type")
                if ctype not in _ALLOWED_FEEDBACK_COMMANDS:
                    steps_log.append(
                        f"✗ Commande {ctype} interdite (le routage appartient à kct route)")
                    continue

                try:
                    result, _diag = agent.execute_dict(command)
                except Exception:
                    steps_log.append(f"⚠ Commande invalide ({ctype}) — ignorée")
                    continue

                ok = "✓" if result.success else "✗"
                steps_log.append(f"{ok} {_describe(command)}")
                if result.success and ctype == "place_component":
                    moved_refs.append(command.get("ref", ""))

            if not moved_refs:
                steps_log.append("Aucun déplacement utile — arrêt")
                break

            # Pas de nettoyage des traces orphelines ici : le dé-routage complet
            # en tête d'itération (_strip_routing) les retire de toute façon.
            # Pas de _refresh_agent non plus : save() sérialise le board interne de
            # l'interpréteur (toujours juste), pas agent.state — et cette boucle
            # n'appelle jamais is_complete()/get_progress() sur l'agent, contrairement
            # à route_with_llm. Si on ajoute un tel check un jour : resync d'abord.
            agent.save(str(board))
            current = board.read_bytes()

    if best_pct < 0:
        best_bytes, best_pct = pcb_bytes, 0
    steps_log.append(f"Sauvetage terminé : meilleur résultat conservé ({best_pct}%)")
    return best_bytes, best_pct, steps_log


def _describe(command: dict) -> str:
    """Description FR lisible d'une commande IA, pour l'UI."""
    t = command.get("type")
    if t == "route_net":
        return f"Route le net {command.get('net')}"
    if t == "place_component":
        ref = command.get("ref")
        near = command.get("near")
        return f"Déplace {ref}" + (f" près de {near}" if near else "")
    if t == "add_via":
        return f"Ajoute un via sur {command.get('net')}"
    if t == "delete_trace":
        return f"Supprime la piste {command.get('net')}"
    if t == "define_zone":
        return f"Crée une zone {command.get('net')} ({command.get('layer')})"
    return f"Action : {t}"

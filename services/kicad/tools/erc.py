"""ERC (Electrical Rules Check) utilities for the Cirqix KiCad service.

Two pure functions consumed by ``routers/erc.py``:

- ``parse_erc_report(json_str)`` — parser for ``kicad-cli sch erc --format json``
  (raises ``InvalidReportError`` on invalid/truncated reports — fail-closed)
- ``apply_no_connect_fixes(sch_content, violations)`` — append-only auto-fix for
  ``pin_not_connected`` violations (NEVER modifies connectivity).

The router additionally orchestrates ``kicad-cli`` invocation with up to 3
auto-fix iterations; that logic lives in ``routers/erc.py``.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class InvalidReportError(ValueError):
    """Raised when an official kicad-cli ERC JSON report is invalid or truncated.

    Callers must treat this as a control failure (fail-closed), never as
    « zero violations ».
    """


# Matches "Symbol <ref> Pin <pin>" — KiCad item.description format
_ITEM_RE = re.compile(r"Symbol\s+(?P<ref>\S+)\s+Pin\s+(?P<pin>\S+)", re.IGNORECASE)


def _extract_ref_pin(description: str) -> tuple[str | None, str | None]:
    """Extract (ref, pin) from a KiCad ERC item description string."""
    if not description:
        return None, None
    match = _ITEM_RE.search(description)
    if not match:
        return None, None
    return match.group("ref"), match.group("pin")


def _collect_violations(report: dict[str, Any]) -> list[Any]:
    """Extrait les violations d'un rapport ERC, quelle que soit sa forme.

    ``kicad-cli sch erc --format json`` (schema ``erc.v1``) ne publie PAS de
    ``violations`` de premier niveau : il les range par feuille, sous
    ``sheets[].violations``. Le DRC, lui, en publie un. Le parseur exigeait la
    forme du DRC, si bien que l'ERC d'autorité échouait à chaque exécution et
    que seul le repli TypeScript rendait un verdict.

    Les deux formes sont acceptées ici ; une forme inconnue reste une erreur —
    ne rien savoir lire n'est jamais « zéro violation ».
    """
    if "violations" in report:
        raw = report["violations"]
        if not isinstance(raw, list):
            raise InvalidReportError(
                f"ERC report field 'violations' must be a list, got {type(raw).__name__}"
            )
        return raw

    sheets = report.get("sheets")
    if isinstance(sheets, list):
        collected: list[Any] = []
        for sheet in sheets:
            if not isinstance(sheet, dict):
                continue
            raw = sheet.get("violations", [])
            if not isinstance(raw, list):
                raise InvalidReportError(
                    f"ERC report field 'sheets[].violations' must be a list, got "
                    f"{type(raw).__name__}"
                )
            collected.extend(raw)
        return collected

    raise InvalidReportError(
        "ERC report has neither 'violations' nor 'sheets[].violations'"
    )


# ⚠️ `kicad-cli sch erc --format json` annonce `coordinate_units: mm` mais rend
# des positions CENT fois trop petites (mesuré le 2026-09-15, KiCad 10.0.6) :
# U1.44 à (0.3048, 0.4826) pour une broche posée à (30.48, 48.26). Les
# `(no_connect)` de l'auto-correction tombaient près de l'origine et 78 broches
# libres du banc restaient en erreur ; le viewer affichait « LOC: (0.30, 0.36) ».
# Garde : tests/test_erc_autocorrection.py.
_ECHELLE_POSITIONS_ERC = 100.0


def parse_erc_report(report_json: str) -> list[dict[str, Any]]:
    """Parse a ``kicad-cli sch erc --format json`` report.

    Returns a list of violation dicts matching the ``ERCViolation`` TypeScript
    interface from ``@cirqix/types`` (id, severity, message, type, ref, pin,
    x_mm, y_mm).

    Raises ``InvalidReportError`` when the report is not valid JSON or lacks
    the expected structure — never treat a truncated report as clean.
    """
    try:
        report = json.loads(report_json)
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidReportError(f"ERC report not valid JSON: {exc}") from exc

    if not isinstance(report, dict):
        raise InvalidReportError(
            f"ERC report must be a JSON object, got {type(report).__name__}"
        )

    raw_violations = _collect_violations(report)

    out: list[dict[str, Any]] = []
    for raw in raw_violations:
        if not isinstance(raw, dict):
            continue
        severity = str(raw.get("severity", "warning")).lower()
        if severity not in ("error", "warning"):
            severity = "warning"
        message = str(raw.get("description", raw.get("type", "ERC violation")))
        v_type = str(raw.get("type", "")) or None

        items = raw.get("items")
        if isinstance(items, list) and items:
            for item in items:
                if not isinstance(item, dict):
                    continue
                ref, pin = _extract_ref_pin(str(item.get("description", "")))
                pos = item.get("pos") if isinstance(item.get("pos"), dict) else {}
                x_mm = pos.get("x") if isinstance(pos, dict) else None
                y_mm = pos.get("y") if isinstance(pos, dict) else None
                # L id doit etre UNIQUE PAR ENTREE, pas par objet du schema : un
                # meme pin (meme uuid KiCad) figure dans plusieurs violations —
                # « pin non connecte » ET « entree non pilotee » —, et React
                # refusait deux enfants de meme cle dans ErcView (run 09f7ee80,
                # 2026-09-13). L uuid de l objet reste disponible dans `item_uuid`.
                item_uuid = str(item.get("uuid") or "")
                entry: dict[str, Any] = {
                    "id": f"{len(out)}-{item_uuid}" if item_uuid else str(uuid.uuid4()),
                    "severity": severity,
                    "message": message,
                    "type": v_type,
                }
                if item_uuid:
                    entry["item_uuid"] = item_uuid
                if ref is not None:
                    entry["ref"] = ref
                if pin is not None:
                    entry["pin"] = pin
                if isinstance(x_mm, (int, float)):
                    entry["x_mm"] = round(float(x_mm) * _ECHELLE_POSITIONS_ERC, 4)
                if isinstance(y_mm, (int, float)):
                    entry["y_mm"] = round(float(y_mm) * _ECHELLE_POSITIONS_ERC, 4)
                out.append(entry)
        else:
            # No items — still keep the violation with just metadata
            out.append({
                "id": str(uuid.uuid4()),
                "severity": severity,
                "message": message,
                "type": v_type,
            })
    return out


# Un schema de 190 ko s analyse en quelques secondes ; au-dela, ce n est plus
# une lenteur mais une panne, et l ERC de secours vaut mieux qu une attente.
_ERC_ENFANT_TIMEOUT_S: int = 120


def run_kicad_tools_erc(
    sch_content: str,
    auto_fix: bool = True,
) -> tuple[list[dict], str, int]:
    """kicad-tools Schematic.validate() — pure Python, no kicad-cli subprocess.

    Returns (violations, updated_sch_content, fixed_count).
    Fixes off-grid symbols and duplicate refs automatically when auto_fix=True.
    """
    import json as _json
    import subprocess
    import sys as _sys
    import tempfile
    from pathlib import Path as _Path

    # ⚠️ DANS UN ENFANT, JAMAIS DANS LE WORKER. `Schematic.load` est du Python
    # PUR : il tient le GIL pendant toute l analyse, et uvicorn tue par SIGKILL
    # tout worker muet plus de 5 s. Mesure du 2026-09-23, deux cartes du banc
    # perdues le meme jour sur un HTTP 500 de cette route — carte-08 (schema de
    # 190 ko) et carte-10 (141 ko). C est la SŒUR du defaut corrige le
    # 2026-09-10 sur le journal Freerouting, que `CLAUDE.md` interdit en toutes
    # lettres et qui n avait jamais ete traitee ici.
    runner = _Path(__file__).resolve().parent / "erc_runner.py"

    with tempfile.TemporaryDirectory() as tmp:
        sch_path = _Path(tmp) / "schematic.kicad_sch"
        sch_path.write_text(sch_content, encoding="utf-8")
        resultat = _Path(tmp) / "erc.json"

        proc = subprocess.run(
            [_sys.executable, str(runner),
             _json.dumps({"sch": str(sch_path), "resultat": str(resultat),
                          "auto_fix": bool(auto_fix)})],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_ERC_ENFANT_TIMEOUT_S, check=False)
        if proc.returncode != 0 or not resultat.is_file():
            # ⚠️ LEVER, jamais rendre une liste vide : « aucune violation » et
            # « je n ai pas pu analyser » ne doivent pas se ressembler. Le
            # fail-closed de l appelant bascule alors sur l ERC de secours.
            raise RuntimeError(
                "ERC kicad-tools : l enfant a echoue (code %s) — %s"
                % (proc.returncode, (proc.stderr or "").strip()[-400:] or "sans message"))
        issues = _json.loads(resultat.read_text(encoding="utf-8")).get("issues", [])
        fixed_content = (sch_path.read_text(encoding="utf-8")
                         if auto_fix else sch_content)

        violations: list[dict] = []
        fixed_count = 0
        for issue in issues:
            if issue.get("fix_applied"):
                fixed_count += 1
            violations.append({
                "id": str(uuid.uuid4()),
                "severity": issue.get("severity", "warning"),
                "message": issue.get("message", ""),
                "type": issue.get("type"),
            })

        return violations, fixed_content, fixed_count


def apply_no_connect_fixes(
    sch_content: str,
    violations: list[dict[str, Any]],
) -> tuple[str, int]:
    """Append-only auto-fix: add ``(no_connect ...)`` markers for unconnected pins.

    Returns ``(new_sch_content, fixed_count)``. The original ``sch_content`` is
    never mutated. ONLY ``pin_not_connected`` violations with both ``x_mm`` and
    ``y_mm`` produce a marker.

    Connectivity (symbols, wires, labels) is preserved char-for-char.
    """
    candidates = [
        v for v in violations
        if v.get("type") == "pin_not_connected"
        and isinstance(v.get("x_mm"), (int, float))
        and isinstance(v.get("y_mm"), (int, float))
    ]
    if not candidates:
        return sch_content, 0

    # Build the no_connect S-expression lines
    new_markers: list[str] = []
    for v in candidates:
        new_uuid = str(uuid.uuid4())
        marker = f'  (no_connect (at {v["x_mm"]} {v["y_mm"]}) (uuid "{new_uuid}"))'
        new_markers.append(marker)

    # Insert before the final closing paren of the top-level (kicad_sch ...) form.
    # Strategy: locate the LAST ")" in the content and inject markers before it.
    last_paren = sch_content.rfind(")")
    if last_paren < 0:
        logger.warning("ERC autofix: malformed .kicad_sch — no closing paren")
        return sch_content, 0

    head = sch_content[:last_paren]
    tail = sch_content[last_paren:]
    inserted = "\n".join(new_markers)
    # Ensure newline separation around the markers
    sep_before = "" if head.endswith("\n") else "\n"
    new_sch = f"{head}{sep_before}{inserted}\n{tail}"
    return new_sch, len(candidates)

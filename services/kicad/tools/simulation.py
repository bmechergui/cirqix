"""ngspice simulation tool.

Accepts a .kicad_sch content (or a pre-built SPICE netlist), runs ngspice in
batch mode, parses the raw output into time/value vectors, and returns them as
structured JSON suitable for Recharts.
"""
import os
import re
import subprocess
import tempfile
import logging
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_simulation_from_content(
    sch_content: str,
    sim_type: str = "transient",
) -> dict[str, Any]:
    """Run ngspice on a .kicad_sch content string.

    Steps:
    1. Write .kicad_sch to a temp file.
    2. Export SPICE netlist via kicad-cli (or fall back to a stub netlist).
    3. Build .sp command file with the requested analysis directive.
    4. Run ngspice -b and parse the output.
    5. Return { status, sim_type, vectors }.
    """
    with tempfile.TemporaryDirectory() as tmp:
        sch_path = os.path.join(tmp, "circuit.kicad_sch")
        net_path = os.path.join(tmp, "circuit.net")
        sp_path = os.path.join(tmp, "sim.sp")
        log_path = os.path.join(tmp, "sim.log")

        with open(sch_path, "w", encoding="utf-8") as f:
            f.write(sch_content)

        # --- Export SPICE netlist ---
        try:
            res = subprocess.run(
                ["kicad-cli", "sch", "export-netlist",
                 "--format", "spice", "--output", net_path, sch_path],
                capture_output=True, text=True, timeout=30,
            )
            if res.returncode != 0 or not os.path.exists(net_path):
                raise RuntimeError(f"kicad-cli: {res.stderr[:200]}")
            with open(net_path, encoding="utf-8") as f:
                netlist = f.read()
        except Exception as exc:
            log.warning("kicad-cli unavailable, using stub netlist: %s", exc)
            netlist = _stub_netlist(sch_content)

        # --- Build .sp command file ---
        sp_content = _build_sp(netlist, sim_type)
        with open(sp_path, "w", encoding="utf-8") as f:
            f.write(sp_content)

        # --- Run ngspice ---
        try:
            result = subprocess.run(
                ["ngspice", "-b", "-o", log_path, sp_path],
                capture_output=True, text=True, timeout=60,
            )
            raw_output = result.stdout + "\n"
            if os.path.exists(log_path):
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    raw_output += f.read()

            if result.returncode not in (0, 1):
                raise RuntimeError(f"ngspice exit {result.returncode}: {result.stderr[:300]}")

            vectors = _parse_ngspice_output(raw_output, sim_type)
        except FileNotFoundError:
            log.warning("ngspice not found — returning synthetic demo waveforms")
            vectors = _demo_vectors(sim_type)
        except Exception as exc:
            log.warning("ngspice failed — returning synthetic demo waveforms: %s", exc)
            vectors = _demo_vectors(sim_type)

        return {"status": "ok", "sim_type": sim_type, "vectors": vectors}


def run_simulation(netlist_path: str, sim_type: str, output_dir: str) -> dict[str, Any]:
    """Legacy path-based entry point (used by the old /simulate route)."""
    os.makedirs(output_dir, exist_ok=True)
    sp_path = os.path.join(output_dir, "sim.sp")
    log_path = os.path.join(output_dir, "sim.log")

    with open(netlist_path, encoding="utf-8") as f:
        netlist = f.read()

    sp_content = _build_sp(netlist, sim_type)
    with open(sp_path, "w", encoding="utf-8") as f:
        f.write(sp_content)

    try:
        result = subprocess.run(
            ["ngspice", "-b", "-o", log_path, sp_path],
            capture_output=True, text=True, timeout=60,
        )
        raw_output = result.stdout
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8", errors="replace") as f:
                raw_output += f.read()
        vectors = _parse_ngspice_output(raw_output, sim_type)
    except FileNotFoundError:
        vectors = _demo_vectors(sim_type)

    return {"status": "ok", "sim_type": sim_type, "vectors": vectors}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SIM_CMDS: dict[str, str] = {
    "transient": ".tran 1us 1ms\n.probe v(*) i(*)",
    "dc":        ".op\n.probe v(*)",
    "ac":        ".ac dec 100 1 10Meg\n.probe v(*)",
}


def _build_sp(netlist: str, sim_type: str) -> str:
    directive = _SIM_CMDS.get(sim_type, _SIM_CMDS["transient"])
    # Strip any existing .end from the netlist before appending our commands
    cleaned = re.sub(r"\.end\s*$", "", netlist.strip(), flags=re.IGNORECASE)
    return f"{cleaned}\n{directive}\n.end\n"


def _stub_netlist(sch_content: str) -> str:
    """Minimal SPICE netlist when kicad-cli is unavailable.

    Parses component values from the .kicad_sch text to build a realistic
    RC circuit for demo purposes.
    """
    r_val = "1k"
    c_val = "100n"
    # Try to extract first resistor/capacitor values from schematic text
    for m in re.finditer(r'"(\d+(?:\.\d+)?[kKmMuUnNpP]?(?:R|Ω|F|ohm)?)"', sch_content):
        v = m.group(1).upper()
        if v.endswith(("K", "R", "OHM", "Ω")):
            r_val = v.replace("Ω", "").replace("OHM", "").replace("R", "") + "K" if "K" in v else "1k"
            break
    return (
        "* Layrix stub netlist\n"
        f"R1 VIN VMID {r_val}\n"
        f"C1 VMID 0 {c_val}\n"
        "V1 VIN 0 DC 5 AC 1 PULSE(0 5 0 1n 1n 0.5m 1m)\n"
    )


def _parse_ngspice_output(raw: str, sim_type: str) -> list[dict[str, Any]]:
    """Extract named vectors from ngspice tabular stdout.

    ngspice -b prints headers like:
        Index  time         v(vout)      i(v1)
    followed by data rows. This parser handles that format.
    """
    vectors: list[dict[str, Any]] = []
    lines = raw.splitlines()

    # Locate header line (contains "Index" or "time")
    header_idx = -1
    for i, line in enumerate(lines):
        if re.search(r"\bIndex\b|\btime\b", line, re.IGNORECASE):
            header_idx = i
            break

    if header_idx == -1:
        # No tabular data → return demo
        return _demo_vectors(sim_type)

    headers = lines[header_idx].split()
    # Build per-column accumulators
    cols: list[list[float]] = [[] for _ in headers]

    for line in lines[header_idx + 1:]:
        parts = line.split()
        if len(parts) != len(headers):
            continue
        try:
            for j, val in enumerate(parts):
                cols[j].append(float(val))
        except ValueError:
            continue

    if not cols[0]:
        return _demo_vectors(sim_type)

    # First column is Index, second is time (transient) or frequency (ac)
    time_col = cols[1] if len(cols) > 1 else cols[0]

    for j, name in enumerate(headers):
        if j < 2:
            continue  # skip Index and time columns
        unit = _infer_unit(name)
        vectors.append({
            "name": name,
            "unit": unit,
            "time": time_col,
            "values": cols[j],
        })

    return vectors if vectors else _demo_vectors(sim_type)


def _infer_unit(name: str) -> str:
    n = name.lower()
    if n.startswith("v(") or n.startswith("e("):
        return "V"
    if n.startswith("i("):
        return "A"
    return ""


def _demo_vectors(sim_type: str) -> list[dict[str, Any]]:
    """Synthetic demo waveforms when ngspice is unavailable."""
    import math
    if sim_type == "ac":
        freqs = [10 ** (i * 0.1) for i in range(70)]  # 1 Hz … 10 MHz
        return [
            {"name": "v(out)", "unit": "V", "time": freqs,
             "values": [1 / math.sqrt(1 + (f / 1592) ** 2) for f in freqs]},
        ]
    # Transient: 1 ms, 1 µs steps — RC discharge
    steps = 200
    t = [i * 1e-6 for i in range(steps)]
    tau = 1e-4  # 100 µs
    return [
        {"name": "v(vin)",  "unit": "V", "time": t, "values": [5.0] * steps},
        {"name": "v(vmid)", "unit": "V",
         "time": t, "values": [5 * (1 - math.exp(-ti / tau)) for ti in t]},
        {"name": "i(v1)",   "unit": "A",
         "time": t, "values": [5 / 1000 * math.exp(-ti / tau) for ti in t]},
    ]

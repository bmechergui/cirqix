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

def _simulation_failure(sim_type: str, reason: str) -> dict[str, Any]:
    """Echec de simulation — AUCUNE donnee fabriquee.

    Le service renvoyait `status: "ok"` sur chacun de ses quatre chemins
    degrades (kicad-cli absent, ngspice absent, ngspice en echec, sortie non
    parsable). Le client TS n'echoue que si `status != 'ok'` : les mesures
    inventees traversaient donc toute la chaine et s'affichaient comme reelles.

    Le message distingue « notre service est indisponible » de « votre circuit
    ne se simule pas » : les deux appellent des actions opposees, et les
    confondre envoie l'utilisateur deboguer un circuit sain.

    MODE DEMONSTRATION — opt-in EXPLICITE, jamais un repli sur erreur. Son
    utilite en developpement local est reelle ; c'est le silence qui ne l'etait
    pas. Symetrique de `CIRQIX_SIMULATION_DEMO` cote TypeScript.
    """
    if os.environ.get("CIRQIX_SIMULATION_DEMO"):
        log.warning("CIRQIX_SIMULATION_DEMO actif — vecteurs SYNTHETIQUES : %s", reason)
        return {
            "status": "ok",
            "sim_type": sim_type,
            "vectors": _demo_vectors(sim_type),
            "engine": "demo",
            "warning": reason,
        }

    log.error("simulation impossible, aucune donnee produite : %s", reason)
    return {
        "status": "error",
        "sim_type": sim_type,
        "vectors": [],
        "reason": reason,
    }


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
            # FAIL CLOSED (2026-08-12). On substituait ici `_stub_netlist` : un
            # circuit RC de DEMONSTRATION, sans aucun rapport avec le schema
            # recu. Avec un ngspice fonctionnel, le service simulait donc
            # CORRECTEMENT UN AUTRE CIRCUIT et renvoyait `status: "ok"` : sortie
            # authentique, chiffres plausibles, aucun rapport avec le produit du
            # client. Une decision de conception prise la-dessus est prise sur
            # une mesure inventee.
            return _simulation_failure(
                sim_type,
                f"export du netlist SPICE impossible (kicad-cli) : {exc}",
            )

        # --- Filter out digital ICs that have no SPICE models ---
        netlist, excluded_refs = _filter_analog_netlist(netlist)
        if excluded_refs:
            log.info("Analog-only simulation: excluded %d component(s): %s",
                     len(excluded_refs), ", ".join(excluded_refs))

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
            if not vectors:
                # Une sortie sans tableau ne prouve AUCUNE mesure. Le parseur
                # renvoyait les vecteurs de demonstration dans ce cas.
                return _simulation_failure(
                    sim_type, "ngspice n'a produit aucune donnee exploitable"
                )
        except FileNotFoundError:
            return _simulation_failure(sim_type, "ngspice absent du conteneur")
        except Exception as exc:
            return _simulation_failure(sim_type, f"ngspice a echoue : {exc}")

        return {
            "status": "ok",
            "sim_type": sim_type,
            "vectors": vectors,
            "excluded_components": excluded_refs,
        }


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
        if not vectors:
            return _simulation_failure(
                sim_type, "ngspice n'a produit aucune donnee exploitable"
            )
    except FileNotFoundError:
        return _simulation_failure(sim_type, "ngspice absent du conteneur")

    return {"status": "ok", "sim_type": sim_type, "vectors": vectors}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Component model names that lack SPICE simulation models (MCUs, digital ICs, etc.)
_DIGITAL_IC_PATTERNS = [
    r"STM32", r"STM8",                     # ST MCUs
    r"ESP32", r"ESP8266",                   # Espressif
    r"ATMEGA", r"ATTINY", r"ATXMEGA",      # Microchip AVR
    r"PIC\d", r"DSPIC",                    # Microchip PIC
    r"LPC\d",                               # NXP LPC
    r"RP\d",                                # RP2040
    r"MSP430",                              # TI MSP430
    r"FPGA", r"CPLD",                       # Programmable logic
    r"XC\d",                                # Xilinx FPGA
    r"FT232", r"FT245", r"FT4232",         # FTDI USB bridges
    r"CH340", r"CH341", r"CP210",           # USB-UART bridges
    r"W25Q", r"MX25L", r"AT25",            # SPI Flash
    r"24LC", r"24C0", r"M24C",             # I2C EEPROM
    r"MPU6050", r"BME280", r"BMP280",      # Complex sensors
    r"SSD1306", r"ILI9341",                # Display controllers
]


def _is_digital_ic(model_name: str) -> bool:
    """Return True if model_name matches a known digital IC without a SPICE model."""
    upper = model_name.upper()
    return any(re.search(pat, upper) for pat in _DIGITAL_IC_PATTERNS)


def _filter_analog_netlist(netlist: str) -> tuple[str, list[str]]:
    """Remove non-simulatable digital ICs from a SPICE netlist.

    Returns (filtered_netlist, excluded_refs). Subcircuit instantiations (X
    lines) whose model matches a known digital IC are dropped along with their
    SPICE continuation lines.
    """
    lines = netlist.splitlines(keepends=True)
    kept: list[str] = []
    excluded_refs: list[str] = []
    skip_continuation = False

    for line in lines:
        stripped = line.strip()

        # SPICE continuation line — inherit the fate of the previous element
        if stripped.startswith("+"):
            if not skip_continuation:
                kept.append(line)
            continue

        skip_continuation = False

        # Empty lines, comments, directives — always keep
        if not stripped or stripped.startswith("*") or stripped.startswith("."):
            kept.append(line)
            continue

        if stripped[0].upper() == "X":
            tokens = stripped.split()
            model = tokens[-1] if len(tokens) > 1 else ""
            ref = tokens[0] if tokens else stripped
            if _is_digital_ic(model):
                excluded_refs.append(ref)
                skip_continuation = True
                continue

        kept.append(line)

    return "".join(kept), excluded_refs


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
        # Aucun tableau : on ne fabrique rien. L'appelant traduit une liste vide
        # en `status: "error"` (fail closed, 2026-08-12). On renvoyait ici
        # `_demo_vectors`, des courbes synthetiques presentees comme mesurees.
        return []

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
        # Tableau vide : aucune mesure. L'appelant traduit en status error.
        return []

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

    # Jamais de repli fabrique ici : une liste vide remonte telle quelle et
    # l'appelant la traduit en `status: "error"` (fail closed, 2026-08-12).
    return vectors


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

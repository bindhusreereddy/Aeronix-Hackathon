import argparse, os, re, sys
from datetime import datetime
from typing import Dict, List, Set
import json
try:
    import yaml  # pip install pyyaml
except Exception:
    yaml = None

from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
import time
from pathlib import Path
from collections import defaultdict

def safe_docx_save(doc, desired_path: str, attempts: int = 3) -> str:
    """
    Try to save to desired_path. If it's locked (PermissionError),
    fall back to a timestamped filename in the same folder.
    Returns the actual path written.
    """
    p = Path(desired_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    for i in range(attempts):
        try:
            doc.save(str(p))
            return str(p)
        except PermissionError:
            # OneDrive/Word lock; wait and retry briefly
            time.sleep(0.5)

    # Still locked: write to a unique fallback next to it
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fallback = p.with_name(f"{p.stem}__{ts}.docx")
    doc.save(str(fallback))
    sys.stderr.write(
        f"⚠️ Could not overwrite '{p.name}' (locked). Wrote fallback: {fallback}\n"
    )
    return str(fallback)

def _add_heading(doc: Document, text: str, level: int = 1):
    h = doc.add_heading(text, level=level)
    return h

def _add_para(doc: Document, text: str, bold=False):
    p = doc.add_paragraph()
    run = p.add_run(text)
    if bold:
        run.bold = True
    return p

def _add_numbered_or_bullets(doc: Document, lines: List[str]):
    """
    Very light parser:
    - '1. text' => numbered paragraph
    - 'a. text' => indented bulleted (lettered) paragraph
    - default => normal paragraph
    """
    for line in lines:
        s = line.strip()
        if not s:
            doc.add_paragraph()
            continue
        if re.match(r"^\d+\.\s", s):         # numbered
            p = doc.add_paragraph(style='List Number')
            p.add_run(re.sub(r"^\d+\.\s*", "", s))
        elif re.match(r"^[a-zA-Z]\.\s", s):  # lettered => bullets (approx)
            p = doc.add_paragraph(style='List Bullet 2')
            p.add_run(re.sub(r"^[a-zA-Z]\.\s*", "", s))
        else:
            doc.add_paragraph(s)

def _add_rails_table(doc: Document, rows: List[dict]):
    if not rows:
        _add_para(doc, "No recognizable power rails found in the IPC by name.")
        return
    _add_para(doc, "Table – Voltage Rails to Check", bold=True)
    table = doc.add_table(rows=1+len(rows), cols=6)
    hdr = table.rows[0].cells
    hdr[0].text = "Item"
    hdr[1].text = "Pin"
    hdr[2].text = "Net"
    hdr[3].text = "Expected"
    hdr[4].text = "Probe Points"
    hdr[5].text = "Measured / P/F"

    # Derive a simple "Item" label sequence a., b., c., ...
    label = ord('a')
    for i, r in enumerate(rows):
        cells = table.rows[i+1].cells
        cells[0].text = chr(label + i) + "."
        # Try to surface a primary pin hint from probe points (first ref-pin)
        first_pin = r["points"].split(",")[0].strip() if r["points"] else ""
        cells[1].text = first_pin
        cells[2].text = r["net"]
        cells[3].text = f"{r['expected']} ({r['tol']})"
        cells[4].text = r["points"]
        cells[5].text = ""  # left blank for operator to fill
    # A bit of spacing after
    doc.add_paragraph()

def write_docx(procedure_text: str, nets: Dict[str, List[str]], out_docx: str, board_hint: str | None, meta: dict | None = None):
    doc = Document()

    # Title
    title = "Test Plan"
    if board_hint:
        title += f" – {board_hint}"
    _add_heading(doc, title, level=1)
    _add_para(doc, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    doc.add_paragraph()

    # Split into blocks and render
    blocks = re.split(r"\n\s*\n", procedure_text.strip())
    for block in blocks:
        lines = [ln.rstrip() for ln in block.splitlines() if ln.strip() != "" or ln == ""]
        if not lines:
            continue
        head = lines[0].strip()

        # Section header like "4.2. Voltage Rail Checks" OR Markdown "# ..."
        if re.match(r"^\d+(\.\d+)*\.\s", head) or re.match(r"^\d+\.\s[A-Z]", head):
            _add_heading(doc, head, level=2)
            body = lines[1:]
        elif _MD_H.match(head):
            _add_md_heading_or_para(doc, head)
            body = lines[1:]
        else:
            # Figure captions (make bold + try to insert image)
            if re.match(r"^Figure\s+\d", head, re.IGNORECASE):
                _add_para(doc, head, bold=True)
                _insert_figure_if_any(doc, head, meta)
                body = lines[1:]
            else:
                body = lines

        _add_numbered_or_bullets(doc, body)

        # If this block is the Rails section, inject our structured table
        if re.search(r"Voltage\s+Rail\s+Checks", head, re.IGNORECASE):
            rows = power_rows_from_nets(nets)
            _add_rails_table(doc, rows)

    # Save
    # Save (robust)
    actual_path = safe_docx_save(doc, out_docx)
    return actual_path  # optionally return the path we actually wrote
# Map rails to expected values/tolerance for the table
_POWER_SPEC = {
    "PWR_5V":   (5.0, 0.10),
    "PWR_3V3":  (3.3, 0.10),
    "PWR_3V3_RF": (3.3, 0.10),
}

def load_meta(path: str) -> dict:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        if path.lower().endswith((".yaml", ".yml")) and yaml:
            return yaml.safe_load(f) or {}
        return json.load(f)

def power_rows_from_nets(nets: Dict[str, List[str]]):
    rows = []  # list of dicts: {net, expected, tol, probe_points}
    for label, (exp, tol) in _POWER_SPEC.items():
        for n, refs in nets.items():
            if classify(n) == label:
                points = ", ".join(probe_points(n, refs)) or "(<missing testpoints>)"
                rows.append({
                    "net": n,
                    "expected": f"{exp:.2f} V",
                    "tol": f"±{tol:.2f} V",
                    "points": points,
                })
    return rows

# -------------------------------
# 0) Single VALIDATION method
# -------------------------------
def validate_and_read_ipc(ipc_path: str) -> str:
    """
    SINGLE place to validate the input. It MUST be an IPC-ish netlist text.
    If invalid, raise ValueError("INVALID DOCUMENT: ...").
    """
    if not os.path.exists(ipc_path):
        raise ValueError("INVALID DOCUMENT: File does not exist.")

    # We only allow .ipc by policy, but we still validate content.
    if not ipc_path.lower().endswith(".ipc"):
        # keep hard policy strict:
        raise ValueError("INVALID DOCUMENT: Only .ipc netlist files are allowed.")

    # Read as text (ignore undecodable bytes)
    try:
        with open(ipc_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except Exception:
        raise ValueError("INVALID DOCUMENT: Could not read as text.")

    # Fast content sanity checks: reject HTML, XML, JSON, PDFs, DOCX, etc.
    head = text[:8000].lower()
    if "<html" in head or "<?xml" in head or head.strip().startswith("{"):
        raise ValueError("INVALID DOCUMENT: Not a plain text netlist.")

    # Must look like IPC-D-356 style or a vendor testpoint report with NET lines.
    # We require at least TWO of these signals to reduce false positives.
    patterns = [
    r"(?mi)^\s*Net\s+[^\s:]+:\s*.+$",                 # "NET <name>: ..."
    r"(?mi)^\s*N\s+[A-Za-z0-9_\-+./]+",               # "N <name>" blocks
    # IPC-D-356A table-style rows like:
    # 317AD5/SCL          ZU4   -28   D0335PA00X+069715Y-046890...
    # 327GND              Y2    -2    A01X+061215Y-042040...
    r"""(?mx)
    ^(?![CP]\s)                   # skip header/comment rows starting with 'C ' or 'P '
    \s*\d{3}[A-Za-z0-9+_.#/\\-]+  # 3-digit net index (e.g., 317/327) + net token
    \s+[A-Za-z][A-Za-z0-9_]*(?:-X)? # refdes like ZU4, Y2, TP_PB7-X
    (?:\s+-\s*[A-Za-z0-9]+)?      # optional ' - <pin>' column
    \b
    """,
    r"(?i)\bIPC[- ]?D[- ]?356",                       # mentions standard
    r"(?i)\bTEST\s*POINT\b",
    r"(?i)\bTP\d+\b",
    r"(?i)\b[A-Z]+[A-Z0-9]*-[A-Za-z0-9]+\b"           # U6-14, P2-2, J3-1
]

    hits = sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))
    if hits < 2:
        raise ValueError("INVALID DOCUMENT: Not a recognizable IPC netlist.")

    return text

# -------------------------------
# 1) Minimal IPC parser (nets -> connections)
#    Supports "NET <name>: ..." and "N <name>" styles.
# -------------------------------
_PAD = re.compile(r"\b([A-Z]+[A-Z0-9]*)-([A-Za-z0-9]+)\b")
_TP  = re.compile(r"\bTP\d+\b", re.IGNORECASE)

# NEW: robust matcher for IPC-D-356A column-style net rows
# Matches lines like:
#   327+5V              U7    -2         PA01X ...
#   327NetJ4_1          TP1   -1         PA01X ...
#   317GND              VIA   -     D0100PA00X ...   (we'll skip VIA)
_IPC_TABLINE = re.compile(
    r"""(?mx)               # multiline, verbose
    ^(?![CP]\s)             # don't start with 'C ' or 'P ' (comments/params)
    \s*([0-9A-Za-z+_.#/\\-]+)   # (1) net name token (allows + _ . - / \ #)
    \s+([A-Za-z][A-Za-z0-9]*)   # (2) refdes like U7, C69, J4, TP1, VIA, PTH3...
    \s+-\s*([A-Za-z0-9]*)?      # (3) optional pin after the dash (may be blank)
    \b
    """
)

ROW = re.compile(r"""
    ^(?![CP]\s)                                  # skip lines starting with 'C ' or 'P '
    \s*([0-9A-Za-z+_.#/\\\-$]+)                  # (1) NET name (allow + _ . - / \ # $)
    \s+([A-Za-z][A-Za-z0-9_]*?(?:_[A-Za-z0-9]+)?(?:-X)?)   # (2) REF (ZU4, L0, Y2, TP_PB7-X)
    (?:\s+-\s*([A-Za-z0-9]+))?                   # (3) optional PIN after a standalone '-' column (e.g., 25, A)
    \b
""", re.VERBOSE | re.MULTILINE)

def parse_ipc_d356(text: str) -> Dict[str, List[str]]:
    """
    Parse IPC-D-356A table-style rows including 317/327 netlines.
    Returns: { net: sorted([ref, ref-pin, TP alias ...]) }
    """
    nets = defaultdict(set)

    for m in ROW.finditer(text):
        net = m.group(1).strip()
        ref = m.group(2).strip()
        pin = (m.group(3) or "").strip()

        RU = ref.upper()
        if RU == "VIA":
            continue  # vias are not probe points

        # If there's an explicit pin column, emit REF-PIN (e.g., ZU4-28, L0-A)
        if pin:
            refpin = f"{RU}-{pin}"
            nets[net].add(refpin)
        # Always keep the ref itself too
        nets[net].add(RU)

        # Convenience aliases for TP_* refs ending with -X (e.g., TP_PB7-X -> TP_PB7)
        if RU.startswith("TP") and RU.endswith("-X"):
            alias = RU.rsplit("-", 1)[0]
            nets[net].add(alias)

    # Return sorted, deduped lists
    return {k: sorted(v) for k, v in nets.items()}



# -------------------------------
# 2) Build compact CONTEXT for LLM (power nets, buses, summary)
# -------------------------------
def classify(name: str) -> str:
    n = name.upper()
    if n in ("GND","PGND","AGND","DGND") or n.endswith("GND"):
        return "GND"
    if re.search(r"(?:\+?5V|VCC5|5\.0V|VBUS)", n):
        return "PWR_5V"
    if "3V3_RF" in n:
        return "PWR_3V3_RF"
    if re.search(r"(?:\+?3V3|3\.3V|VCC3)", n):
        return "PWR_3V3"
    if re.search(r"\bSCL\b", n):   return "I2C_SCL"
    if re.search(r"\bSDA\b", n):   return "I2C_SDA"
    if re.search(r"\bMOSI\b", n):  return "SPI_MOSI"
    if re.search(r"\bMISO\b", n):  return "SPI_MISO"
    if re.search(r"\bSCK\b|\bSCLK\b", n): return "SPI_SCK"
    if re.search(r"\bTX\b|\bUART_TX\b", n): return "UART_TX"
    if re.search(r"\bRX\b|\bUART_RX\b", n): return "UART_RX"
    if "PPS" in n: return "PPS"
    if "ANT" in n: return "RF_ANT"
    return "OTHER"

def probe_points(netname: str, refs: List[str]) -> List[str]:
    pts = []
    for r in refs:
        if r.upper().startswith("TP"): pts.append(r.upper())
        elif re.match(r"^[A-Z]+[A-Z0-9]*-\w+$", r): pts.append(r)
    return sorted(set(pts))

def build_context(nets: Dict[str, List[str]]) -> str:
    # Collect key nets and a short connection list
    power_rows = []
    for label, exp, tol in [("PWR_5V",5.0,0.10),("PWR_3V3",3.3,0.10),("PWR_3V3_RF",3.3,0.10)]:
        for n, refs in nets.items():
            if classify(n) == label:
                points = ", ".join(probe_points(n, refs))
                power_rows.append(f"- {n}: expect {exp:.2f} V ±{tol:.2f} V; probe at {points or '(<missing testpoints>)'}")

    i2c = {"SCL":[],"SDA":[]}
    spi = {"MOSI":[],"MISO":[],"SCK":[]}
    uart= {"TX":[],"RX":[]}
    pps = []
    ant = []
    for n, refs in nets.items():
        c = classify(n)
        if c=="I2C_SCL": i2c["SCL"].append(n)
        elif c=="I2C_SDA": i2c["SDA"].append(n)
        elif c=="SPI_MOSI": spi["MOSI"].append(n)
        elif c=="SPI_MISO": spi["MISO"].append(n)
        elif c=="SPI_SCK":  spi["SCK"].append(n)
        elif c=="UART_TX":  uart["TX"].append(n)
        elif c=="UART_RX":  uart["RX"].append(n)
        elif c=="PPS":      pps.append(n)
        elif c=="RF_ANT":   ant.append(n)

    conn_preview = []
    MAX_ROWS = 80  # keep context short enough for LLM
    for i, (n, refs) in enumerate(sorted(nets.items())):
        if i >= MAX_ROWS: break
        conn_preview.append(f"{n}: {', '.join(refs)}")

    ctx_parts = [
        "POWER RAILS (from IPC):",
        *(power_rows or ["- <none detected by name>"]),
        "",
        "BUSES (from IPC):",
        f"- I2C: SCL={', '.join(i2c['SCL']) or 'none'}, SDA={', '.join(i2c['SDA']) or 'none'}",
        f"- SPI: MOSI={', '.join(spi['MOSI']) or 'none'}, MISO={', '.join(spi['MISO']) or 'none'}, SCK={', '.join(spi['SCK']) or 'none'}",
        f"- UART: TX={', '.join(uart['TX']) or 'none'}, RX={', '.join(uart['RX']) or 'none'}",
        f"- PPS nets: {', '.join(pps) or 'none'}",
        f"- RF ANT nets: {', '.join(ant) or 'none'}",
        "",
        "CONNECTIONS PREVIEW (subset):",
        *conn_preview
    ]
    return "\n".join(ctx_parts)

# --- Markdown-ish inline bold renderer ---
_BOLD_TOKEN = re.compile(r'(\*\*[^*]+\*\*)')

def _add_md_runs(p, text: str):
    """Write text into a python-docx paragraph with **bold** support."""
    # Split by **...** and alternate
    parts = _BOLD_TOKEN.split(text)
    for part in parts:
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            run = p.add_run(part[2:-2])
            run.bold = True
        else:
            p.add_run(part)

# --- Minimal Markdown heading detector: "#", "##", "###"
_MD_H = re.compile(r'^\s*(#{1,6})\s+(.*)$')

def _add_md_heading_or_para(doc: Document, line: str):
    """
    Turn '# Title' -> heading, otherwise paragraph that understands **bold**.
    """
    m = _MD_H.match(line)
    if m:
        level = min(len(m.group(1)), 3)  # map #=1, ##=2, ###+=3
        doc.add_heading(m.group(2).strip(), level=level)
    else:
        p = doc.add_paragraph()
        _add_md_runs(p, line)

def _insert_figure_if_any(doc: Document, caption_line: str, meta: dict | None):
    """
    If the line looks like 'Figure 4-1 ...' or 'Figure 4–1 ...',
    try to insert an image below it. Priority:
    - meta['figures'] dict: keys '4-1' or 'Figure 4-1' -> path
    - default filenames in cwd: 'Figure_4-1.png', 'Figure_4-1.jpg'
    """
    if meta is None:
        meta = {}
    m = re.match(r'^\s*Figure\s+(\d+[-–]\d+)\b', caption_line, re.IGNORECASE)
    if not m:
        return
    key = m.group(1).replace("–", "-")
    width_in = float(meta.get("figure_width_in", 5.5))

    # 1) metadata map
    candidate = None
    figs = meta.get("figures") if isinstance(meta.get("figures"), dict) else {}
    if figs:
        candidate = figs.get(key) or figs.get(f"Figure {key}")

    # 2) default filenames if not supplied in meta
    if not candidate:
        for ext in (".png", ".jpg", ".jpeg"):
            cand = f"Figure_{key}{ext}"
            if os.path.exists(cand):
                candidate = cand
                break

    # 3) insert if it exists
    if candidate and os.path.exists(candidate):
        try:
            from docx.shared import Inches
            doc.add_picture(candidate, width=Inches(width_in))
        except Exception:
            pass  # don't crash on image issues

# -------------------------------
# 3) LLM call (OpenAI) to write the plan
# -------------------------------
PROMPT_TMPL = """You are an electronics bring-up expert.

Write a clear, beginner-friendly Test Plan Procedure that matches the customer house style shown below.
Use ONLY the validated IPC netlist context and provided metadata. If some details are missing, write safe,
generic steps and clearly label them as generic. Do NOT invent parts that are not implied by net names.

STYLE / FORMAT REQUIREMENTS (STRICT):
- Use section numbering exactly like: 1., 2., 3., 4., 5., 6.
- Use numbered steps (1., 2., 3., …) with lettered sub-steps (a., b., c., …) when listing items to probe.
- Reference the exact pins/nets detected from context: {J3_1}, {J3_2}, {U6_14_16}, {P2_2}, {U12_1}.
- Refer to figures verbatim as “Figure 4-1 Test Configuration A” and “Figure 4-2 Test Configuration B”.
- Do NOT include Markdown tables for the rail checks; write rows as bullet/numbered lines so downstream can build Word tables.
- Keep wording terse and technical; mirror the tone of engineering procedures.
- Include warnings exactly as parenthetical “(WARNING: …)”.

CONTENT REQUIREMENTS:
1. Test Equipment
- Emit an equipment list “Item, Manufacturer, Part Number, Description” using metadata.equipment if present.
  If metadata is missing, emit a generic list (power supply, DMM, oscilloscope, JTAG programmer, USB-TTL cable, test PC).

2. Procedure

2.1. Visual Inspection
1. Instruct to inspect per IPC-610 and drawing numbers from metadata.visual if present; otherwise generic IPC-610 Class 2.

2.2. Voltage Rail Checks
(Reference “Figure 4-1 Test Configuration A” when describing cabling.)
1. Set multimeter to diode/beep mode.
2. With black probe on {GND_PAD}, verify the following locations ARE connected to ground:
   a. P2 pin 1 (GPIO Header)   [generic if not found]
3. With black probe still on {GND_PAD}, verify the following are NOT connected to ground:
   a. {PWR_JACK}
   b. {PLUS5}
   c. {PLUS3}
   d. {PLUS3RF}
4. With black probe on {PLUS5}, verify NOT connected:
   a. {PLUS3}
   b. {PLUS3RF}
5. With black probe on {PLUS3}, verify NOT connected:
   a. {PLUS3RF}
6. Instruct safe power-up using metadata.power (default 5.0 V, 200 mA), warnings on over-current.
7. Connect supply to barrel jack via Item 3 (power cable). Reference Figure 4-1.
8. (WARNING: If UUT draws too much current, be prepared to turn off the power supply quickly.)
9. (WARNING) If current exceeds limit (constant-current mode), disable supply and stop procedure.
10. With black probe on {GND_PAD}, measure and record:
    a. {PWR_JACK}: 5V ±100mV (or metadata tolerance if provided)
    b. {PLUS5}:    5V ±100mV
    c. {PLUS3}:    3.3V ±100mV
    d. {PLUS3RF}:  3.3V ±100mV
11. Oscilloscope setup (Item 7): CH1 1V/div, 5us/div, measurement=frequency.
12. Probe Y1 pin 1 and verify ~16 MHz (use metadata.oscillators if provided).
13. Probe Y2 pin 1 and verify ~32 MHz (use metadata.oscillators if provided).
14. Power off UUT.

2.3. Firmware Programming
(Reference “Figure 4-2 Test Configuration B”.)
1. Connect JTAG Programmer (Item 4) to test PC (Item 5) via USB; connect to UUT JTAG.
2. Connect USB-TTL cable (Item 6) to test PC and UUT debug header (P2) with pinout:
   - P2 pin 1 → GND (black)
   - P2 pin 8 → Rx (white)
   - P2 pin 10 → Tx (green)
3. Program the UUT per metadata.programming.procedure_doc if present; otherwise write “per programming procedure”. Verify success.

2.4. Functional Test
1. Open a serial terminal with parameters (use metadata.serial, else 115200/8N1).
2. Reset the UUT by pressing SW1.
3. Verify welcome screen prints.
4. Run commands: “bit.lora”, “bit.gps”, “bit.imu”, “bit.i2c”; verify each shows Pass.

CONTEXT (IPC nets):
---------
{context}
---------

METADATA (optional):
---------
{metadata}
---------
"""

def call_openai_procedure(context: str, nets: Dict[str, List[str]], meta: dict) -> str:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set. Cannot generate document via OpenAI.")

    try:
        from openai import OpenAI
    except Exception as e:
        raise RuntimeError("OpenAI client not installed. pip install openai") from e

    client = OpenAI(api_key=api_key)

    # Build the final prompt (fills {J3_1}, {PLUS5}, etc.) cleanly.
    prompt = build_prompt(context, nets, meta)

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "You are a precise, safe hardware bring-up planner."},
            {"role": "user", "content": prompt},
        ],
    )
    return completion.choices[0].message.content

def call_openai_markdown(context: str, nets: Dict[str, List[str]], meta: dict) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set. Cannot generate document via OpenAI.")
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    prompt = build_prompt(context, nets, meta)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.1,
        messages=[
            {"role": "system", "content": "You are a precise, safe hardware bring-up planner."},
            {"role": "user", "content": prompt},
        ],
    )
    md = completion.choices[0].message.content
    if not md.strip().lower().startswith("3.2"):
        md = f"3.2. Test Equipment\n\n" + md  # ensure numbering starts per spec
    return md

def build_prompt(context: str, nets: Dict[str, List[str]], meta: dict) -> str:
    a = pick_anchors(nets)
    return PROMPT_TMPL.format(
        context=context,
        metadata=json.dumps(meta or {}, indent=2),
        J3_1=(a["J3_1_PWR_JACK"][0] if a["J3_1_PWR_JACK"] else "J3 pin 1"),
        J3_2=(a["J3_2_GND"][0] if a["J3_2_GND"] else "J3 pin 2"),
        U6_14_16=", ".join(a["U6_14_16_5V"]) if a["U6_14_16_5V"] else "U6 pins (5V)",
        P2_2=(a["P2_2_3V3"][0] if a["P2_2_3V3"] else "P2 pin 2"),
        U12_1=(a["U12_1_3V3RF"][0] if a["U12_1_3V3RF"] else "U12 pin 1"),
        GND_PAD=a["human"]["gnd_pad"],
        PWR_JACK=a["human"]["pwrjack"],
        PLUS5=a["human"]["p5v"],
        PLUS3=a["human"]["p3v3"],
        PLUS3RF=a["human"]["p3v3rf"],
    )

def pick_anchors(nets: Dict[str, List[str]]) -> dict:
    """Pick canonical probe points matching your doc style."""
    def by_net(name):
        return [r for r in nets.get(name, []) if re.match(r"^[A-Z]+[A-Z0-9]*-\w+$", r)]

    # try to find typical refs
    gnd_refs = by_net("327GND") or by_net("GND") or []
    pwrjack_refs = by_net("327PWR_JACK") or by_net("PWR_JACK") or []
    plus5_refs = by_net("327+5V") or by_net("+5V") or []
    plus3_refs = by_net("327+3V3") or by_net("+3V3") or []
    plus3rf_refs = by_net("327+3V3_RF") or by_net("+3V3_RF") or []

    # choose specific pins to mirror your sample
    def pick(refs, want_prefix, want_pins=None):
        # want_prefix like "J3", "U6", "P2", "U12"
        cands = [r for r in refs if r.startswith(want_prefix + "-")]
        if want_pins:
            cands = [f"{want_prefix}-{p}" for p in want_pins if f"{want_prefix}-{p}" in cands]
        return cands

    anchors = {
        "J3_1_PWR_JACK": pick(pwrjack_refs, "J3", ["1"]) or pick(pwrjack_refs, "J3"),
        "J3_2_GND":      pick(gnd_refs, "J3", ["2"]) or pick(gnd_refs, "J3"),
        "U6_14_16_5V":   pick(plus5_refs, "U6", ["14","15","16"]) or [r for r in plus5_refs if r.startswith("U6-")],
        "P2_2_3V3":      pick(plus3_refs, "P2", ["2"]) or pick(plus3_refs, "P2"),
        "U12_1_3V3RF":   pick(plus3rf_refs, "U12", ["1"]) or pick(plus3rf_refs, "U12"),
    }
    # flatten ranges into compact text like "U6 pins 14–16"
    def fmt_range(lst, label):
        pins = [x.split("-")[1] for x in lst if "-" in x]
        if pins == ["14","15","16"]: return f"U6 pins 14–16 {label}"
        if len(pins) == 1: return f"{lst[0]} {label}"
        return f"{', '.join(lst)} {label}"
    anchors["human"] = {
        "gnd_pad": "ground pad (pin 2) of the input barrel jack (J3) (GND)" if anchors["J3_2_GND"] else "a known GND pad",
        "pwrjack": f"{anchors['J3_1_PWR_JACK'][0]} (PWR_JACK)" if anchors["J3_1_PWR_JACK"] else "J3 pin 1 (PWR_JACK)",
        "p5v":     fmt_range(anchors["U6_14_16_5V"], "(+5V)") if anchors["U6_14_16_5V"] else "+5V rail pins",
        "p3v3":    f"{anchors['P2_2_3V3'][0]} (+3V3)" if anchors["P2_2_3V3"] else "+3V3 rail pins",
        "p3v3rf":  f"{anchors['U12_1_3V3RF'][0]} (+3V3_RF)" if anchors["U12_1_3V3RF"] else "+3V3_RF rail pins",
    }
    return anchors

# -------------------------------
# 4) Main
# -------------------------------
def main():
    ap = argparse.ArgumentParser(description="Validate IPC netlist, then generate bring-up plan via OpenAI.")
    ap.add_argument("--ipc", required=True, help="Path to .ipc netlist (ONLY).")
    ap.add_argument("--out-docx", required=True, help="Path to output Word .docx.")
    ap.add_argument("--out-md", help="(Optional) Also write Markdown here.")
    ap.add_argument("--board-hint", help="Optional hint like 'Car Radio' or 'Arduino Uno' (shown in title).")
    ap.add_argument("--meta", help="Optional YAML/JSON with equipment/serial/etc. (reserved for future use)")
    args = ap.parse_args()

    # 1) VALIDATE
    try:
        text = validate_and_read_ipc(args.ipc)
    except ValueError as ve:
        sys.stderr.write(str(ve) + "\n")
        sys.exit(2)

    # 2) PARSE
    nets = parse_ipc_d356(text)
    if not nets:
        sys.stderr.write("INVALID DOCUMENT: No nets/testpoints parsed from the file.\n")
        sys.exit(2)

    # 3) Build context
    ctx = build_context(nets)
    if args.board_hint:
        ctx = f"[Board hint: {args.board_hint}]\n\n" + ctx

    # 3b) Load optional metadata
    meta = load_meta(args.meta) if args.meta else {}

    # 4) Get step-by-step procedure text from LLM
    try:
        try:
            proc_txt = call_openai_procedure(ctx, nets, meta)
        except Exception as e:
            sys.stderr.write(f"LLM ERROR: {e}\n")
            sys.exit(3)
    except Exception as e:
        sys.stderr.write(f"LLM ERROR: {e}\n")
        sys.exit(3)

    # 5) Ensure output directories exist and write DOCX
    out_docx_dir = os.path.dirname(os.path.abspath(args.out_docx))
    if out_docx_dir:
        os.makedirs(out_docx_dir, exist_ok=True)
    actual_docx = write_docx(proc_txt, nets, args.out_docx, args.board_hint)
    print(f"✅ Wrote Word doc: {actual_docx}")


    # (Optional) also write Markdown for diffing/review
    if args.out_md:
        out_md_dir = os.path.dirname(os.path.abspath(args.out_md))
        if out_md_dir:
            os.makedirs(out_md_dir, exist_ok=True)
        with open(args.out_md, "w", encoding="utf-8") as f:
            f.write(proc_txt)

    print(f"✅ Valid IPC netlist: {args.ipc}")
    print(f"✅ Nets parsed: {len(nets)}")
    print(f"✅ Wrote Word doc: {args.out_docx}")
    if args.out_md:
        print(f"✅ Also wrote Markdown: {args.out_md}")

if __name__ == "__main__":
    main()

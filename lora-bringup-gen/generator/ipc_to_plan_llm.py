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
def write_docx(procedure_text: str, nets: Dict[str, List[str]], out_docx: str, board_hint: str | None):
    doc = Document()

    # Title
    title = "Factory Bring-Up Procedure"
    if board_hint:
        title += f" – {board_hint}"
    _add_heading(doc, title, level=1)
    _add_para(doc, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    doc.add_paragraph()

    # Split the LLM output roughly into sections by blank lines and write
    # We also detect likely section titles like "4.2. Voltage Rail Checks"
    blocks = re.split(r"\n\s*\n", procedure_text.strip())
    for block in blocks:
        lines = [ln.rstrip() for ln in block.splitlines()]
        if not lines:
            continue
        head = lines[0].strip()

        # If looks like a section header (e.g., "4.2. Voltage Rail Checks")
        if re.match(r"^\d+(\.\d+)*\.\s", head) or re.match(r"^\d+\.\s[A-Z]", head):
            _add_heading(doc, head, level=2)
            body = lines[1:]
        else:
            # Non-numbered heading lines like "Figure 4 1 Test Configuration A"
            if re.match(r"^Figure\s+\d", head, re.IGNORECASE):
                _add_para(doc, head, bold=True)
                body = lines[1:]
            else:
                # plain body
                body = lines

        _add_numbered_or_bullets(doc, body)

        # If this block is the Rails section, inject our structured table
        if re.search(r"Voltage\s+Rail\s+Checks", head, re.IGNORECASE):
            rows = power_rows_from_nets(nets)
            _add_rails_table(doc, rows)

    # Save
    os.makedirs(os.path.dirname(os.path.abspath(out_docx)), exist_ok=True)
    doc.save(out_docx)

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
        r"(?mi)^\s*Net\s+[^\s:]+:\s*.+$",                # IPC-D-356 signature
        r"(?mi)^\s*N\s+[A-Za-z0-9_\-+./]+",        # "NET <name>: U6-14, P2-2, TP7"
        r"(?mi)^\s*\S+\s+[A-Z]+[0-9A-Z]+\s+-?[A-Za-z0-9]+\s+[PU][A-Z]\d{2,3}X\s+\d+Y\s+\d+X",   # "N <name>"
        r"(?i)\bIPC[- ]?D[- ]?356",                   # mentions test points
        r"(?i)\bTEST\s*POINT\b",                          # TP5, TP7, ...
        r"(?i)\bTP\d+\b",
        r"(?i)\b[A-Z]+[A-Z0-9]*-[A-Za-z0-9]+\b"   # U6-14, P2-2, J3-1
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

def parse_ipc_text(text: str) -> Dict[str, List[str]]:
    nets: Dict[str, Set[str]] = {}

    # A) "NET <name>: ..." lines
    for m in re.finditer(r"(?m)^\s*NET\s+([^\s:]+)\s*:\s*(.+)$", text):
        name = m.group(1).strip()
        rhs  = m.group(2)
        cons: Set[str] = set()
        for pad in _PAD.findall(rhs):
            cons.add(f"{pad[0]}-{pad[1]}")
        for tp in _TP.findall(rhs):
            cons.add(tp.upper())
        if cons:
            nets.setdefault(name, set()).update(cons)

    # B) "N <name>" blocks
    current = None
    for line in text.splitlines():
        ln = line.strip()
        nm = re.match(r"^N\s+([A-Za-z0-9_\-\+\./]+)", ln)
        if nm:
            current = nm.group(1)
            nets.setdefault(current, set())
            continue
        if current:
            for pad in _PAD.findall(ln):
                nets[current].add(f"{pad[0]}-{pad[1]}")
            for tp in _TP.findall(ln):
                nets[current].add(tp.upper())

    # C) IPC-D-356A table rows (the file you posted)
    for m in _IPC_TABLINE.finditer(text):
        net = m.group(1).strip()
        ref = m.group(2).upper()
        pin = (m.group(3) or "").strip()

        # Skip pure mechanical holes; keep PTH* if you want them—here we drop VIA only
        if ref == "VIA":
            continue

        # Compose ref-pin like U7-2 if we have a pin; else keep the ref
        refpin = f"{ref}-{pin}" if pin else ref

        # Capture TP references both ways (as TPx and TPx-<pin>) for easier probing
        cons = nets.setdefault(net, set())
        cons.add(refpin)
        if ref.startswith("TP"):
            cons.add(ref)  # e.g., TP1

    # finalize
    nets = {k: sorted(v) for k, v in nets.items() if v}
    return nets



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


# -------------------------------
# 3) LLM call (OpenAI) to write the plan
# -------------------------------
PROMPT_TMPL = """You are an electronics bring-up expert.
Write a clear, beginner-friendly FACTORY BRING-UP PROCEDURE using ONLY the validated IPC netlist context below.
Do NOT invent components that are not implied by net names. If some nets are missing, write generic but safe steps.

Strict format:
- Section numbering like 4., 4.1., 4.2. ...
- Numbered steps (1., 2., 3., ...). Use lettered sub-steps (a., b., c., ...) where helpful.
- Include a "Voltage Rail Checks" section with shorts checks that reference specific pins/nets found in the context (e.g., J3-1, J3-2 (GND), U6-14..16 (+5V), P2-2 (+3V3), U12-1 (+3V3_RF)).
- Include "Firmware Programming" and "Functional Test" sections. If serial/JTAG details aren't in the context, write safe generic steps.
- Do NOT include a Markdown table for rails; the app will build a Word table itself.

Context:
---------
{context}
---------
"""
def call_openai_procedure(context: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set. Cannot generate document via OpenAI.")
    try:
        from openai import OpenAI
    except Exception as e:
        raise RuntimeError("OpenAI client not installed. pip install openai") from e

    client = OpenAI(api_key=api_key)
    prompt = PROMPT_TMPL.format(context=context)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "You are a precise, safe hardware bring-up planner."},
            {"role": "user", "content": prompt},
        ],
    )
    return completion.choices[0].message.content

def call_openai_markdown(context: str) -> str:
    """
    Calls OpenAI to produce the step-by-step plan (Markdown).
    Requires OPENAI_API_KEY in env. Uses gpt-4o-mini by default.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set. Cannot generate document via OpenAI.")

    # Lightweight, direct client (no heavy LangChain needed for this use).
    try:
        from openai import OpenAI  # pip install openai>=1.0
    except Exception as e:
        raise RuntimeError("OpenAI client not installed. pip install openai") from e

    client = OpenAI(api_key=api_key)

    prompt = PROMPT_TMPL.format(context=context)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Use Responses API (new SDK). If your env only has older SDK, adjust accordingly.
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "You are a precise, safe hardware bring-up planner."},
            {"role": "user", "content": prompt},
        ],
    )
    md = completion.choices[0].message.content
    # Prepend a title if model didn't add one
    if not md.strip().lower().startswith("#"):
        md = f"# Auto Bring-Up Plan (from IPC)\nGenerated: {ts}\n\n" + md
    return md


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
    nets = parse_ipc_text(text)
    if not nets:
        sys.stderr.write("INVALID DOCUMENT: No nets/testpoints parsed from the file.\n")
        sys.exit(2)

    # 3) Build context
    ctx = build_context(nets)
    if args.board_hint:
        ctx = f"[Board hint: {args.board_hint}]\n\n" + ctx

    # (Optional) metadata load – not used directly in this minimal Word writer yet
    meta = load_meta(args.meta) if args.meta else {}

    # 4) Get step-by-step procedure text from LLM
    try:
        proc_txt = call_openai_procedure(ctx)
    except Exception as e:
        sys.stderr.write(f"LLM ERROR: {e}\n")
        sys.exit(3)

    # 5) Write DOCX
    write_docx(proc_txt, nets, args.out_docx, args.board_hint)

    # (Optional) also write Markdown for diffing/review
    if args.out_md:
        os.makedirs(os.path.dirname(os.path.abspath(args.out_md)), exist_ok=True)
        with open(args.out_md, "w", encoding="utf-8") as f:
            f.write(proc_txt)

    print(f"✅ Valid IPC netlist: {args.ipc}")
    print(f"✅ Nets parsed: {len(nets)}")
    print(f"✅ Wrote Word doc: {args.out_docx}")
    if args.out_md:
        print(f"✅ Also wrote Markdown: {args.out_md}")

 

if __name__ == "__main__":
    main()

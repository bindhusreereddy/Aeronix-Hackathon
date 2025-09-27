import argparse, csv, textwrap, yaml, json, os
from datetime import datetime

def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_probe_points(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)  # { "NET": ["TP7","P2-2"], ... }

def merge_points(rails, derived):
    for r in rails:
        pts = list(r.get("points", []))
        extra = derived.get(r["name"], [])
        for p in extra:
            if p not in pts:
                pts.append(p)
        r["points"] = pts

MD_TEMPLATE = """# {product} Bring-Up Plan (Auto-Generated)
Generated: {timestamp}

## Tools
- Bench PSU (set **5.0 V**, current limit **{current_limit} mA**)
- DMM (multimeter), Oscilloscope
- J-Link debugger, USB-to-TTL cable
- PC with serial terminal (**{baud} N81**)

## 1) Visual Inspection (NO POWER)
Look for solder bridges, missing parts, wrong orientations. Record Pass/Fail.

## 2) Continuity Checks (NO POWER)
- Verify no shorts GND↔ +5V / +3V3 / +3V3_RF.
- Verify +5V is NOT tied to +3V3 or +3V3_RF; and +3V3 is NOT tied to +3V3_RF.

## 3) Safe Power-On
- Set PSU to **5.0 V**, current limit **{current_limit} mA**.
- If supply hits current limit (CC), power off and inspect.

## 4) Rail Measurements (DMM)
| Net      | Expected | Tol  | Probe points         | Measured | P/F |
|----------|---------:|-----:|----------------------|---------:|:---:|
{rail_rows}

## 5) Clocks (Oscilloscope)
{clock_lines}

*(Tip: scope ~1 V/div, ~5 µs/div; short ground lead for clean signal.)*

## 6) Programming
- Connect **J-Link** to SWD header; connect **USB-TTL** to serial header:
  - GND → {pin_gnd}
  - PC-RX → {pin_rx}
  - PC-TX → {pin_tx}
- Run programming script/procedure. Confirm success.

## 7) Functional Tests (Serial @ {baud})
- Open terminal, press reset, expect welcome screen.
{func_lines}

## 8) Datasheet
Record measured values and Pass/Fail for all steps. No blanks.
"""

def render_markdown(cfg):
    rails_rows = []
    for r in cfg["rails"]:
        pts = ", ".join(r.get("points", [])) if r.get("points") else ""
        rails_rows.append(f"| {r['name']} | {r['expected']:.2f} V | ±{r['tol']:.2f} V | {pts} |  |  |")
    rail_rows = "\n".join(rails_rows)

    clock_lines = "\n".join([f"- **{c['ref']}** ≈ {c['expected_mhz']:.2f} MHz"
                             for c in cfg.get("clocks", [])])

    func_lines = "\n".join([f"- `{t['cmd']}` → expect **{t['expect']}**"
                            for t in cfg.get("functional_tests", [])])

    return MD_TEMPLATE.format(
        product=cfg["product"],
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        current_limit=cfg["safety"]["current_limit_ma"],
        baud=cfg["programming"]["serial"]["baud"],
        rail_rows=rail_rows,
        clock_lines=clock_lines if clock_lines else "- (none)",
        pin_gnd=cfg["programming"]["serial"]["pins"]["GND"],
        pin_rx=cfg["programming"]["serial"]["pins"]["RX"],
        pin_tx=cfg["programming"]["serial"]["pins"]["TX"],
        func_lines=func_lines if func_lines else "- (none)",
    )

def write_csv(cfg, out_csv):
    rows = []
    # Rails
    for idx, r in enumerate(cfg["rails"], start=1):
        rows.append([f"4.{idx}", r["name"], r["expected"], r["tol"],
                     "; ".join(r.get("points", [])), "", ""])
    # Clocks
    for idx, c in enumerate(cfg.get("clocks", []), start=1):
        rows.append([f"5.{idx}", c["ref"], f"{c['expected_mhz']} MHz", "0.1 MHz", f"{c['ref']} pad", "", ""])
    # Functional tests
    for idx, t in enumerate(cfg.get("functional_tests", []), start=1):
        rows.append([f"7.{idx}", t["cmd"], t["expect"], "", "Serial", "", ""])

    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Step","Item","Expected","Tolerance","Where","Measured","Result"])
        w.writerows(rows)

def main():
    ap = argparse.ArgumentParser(description="Bring-up plan generator")
    ap.add_argument("--requirements", required=True, help="Path to requirements.yaml")
    ap.add_argument("--derived", help="Optional derived_probe_points.json")
    ap.add_argument("--out-md", required=True, help="Output Markdown path")
    ap.add_argument("--out-csv", required=True, help="Output CSV path")
    args = ap.parse_args()

    cfg = load_yaml(args.requirements)
    derived = load_probe_points(args.derived)
    merge_points(cfg.get("rails", []), derived)

    md = render_markdown(cfg)
    os.makedirs(os.path.dirname(args.out_md), exist_ok=True)
    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write(md)
    write_csv(cfg, args.out_csv)
    print(f"✅ Wrote {args.out_md}")
    print(f"✅ Wrote {args.out_csv}")

if __name__ == "__main__":
    main()

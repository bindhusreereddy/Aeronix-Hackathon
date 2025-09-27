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

def llm_goodwill_from_blocks(
    blocks: Union[str, List[str], Tuple[str, ...]],
    *,
    k: int = 8,
    min_par_len: int = 40,
    filter_to_goodwill: bool = True,
    verbose: bool = False,
    print_retrieval: bool = False,   # <— NEW
) -> Optional[str]:
    """
    Extracts goodwill amount from text blocks using a RAG (LLM) pipeline.

    This function takes text, finds relevant paragraphs concerning goodwill using
    vector embeddings, and then uses a large language model (LLM) to extract
    the specific monetary amount.
    """
    # 1. Normalize input into a list of strings.
    if isinstance(blocks, str):
        text_blocks: List[str] = [blocks]
    else:
        text_blocks = [b for b in blocks if isinstance(b, str) and b.strip()]

    if not text_blocks:
        if verbose: print("[goodwill LLM] No text blocks provided.", file=sys.stderr)
        return None

    # 2. Chunk text into paragraphs based on blank lines.
    paras: List[str] = []
    for b in text_blocks:
        for p in re.split(r"\n\s*\n", b):
            p = p.strip()
            if len(p) >= min_par_len:
                paras.append(p)

    # 3. (Optional) Pre-filter paragraphs to only those containing "goodwill".
    if filter_to_goodwill:
        paras = [p for p in paras if re.search(r"\bgoodwill\b", p, flags=re.IGNORECASE)]

    if not paras:
        if verbose: print("[goodwill LLM] No paragraphs after filtering.", file=sys.stderr)
        return None

    try:
        # 4. Set up the RAG pipeline.
        # 4a. Initialize embeddings model (OpenAI or local HuggingFace).
        if os.getenv("OPENAI_API_KEY"):
            from langchain_openai import OpenAIEmbeddings
            embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        else:
            from langchain_community.embeddings import HuggingFaceEmbeddings
            embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

        # 4b. Create LangChain documents and build a FAISS vector store for fast retrieval.
        from langchain.schema import Document
        docs = [Document(page_content=p) for p in paras]
        if not docs:
            if verbose: print("[goodwill LLM] No docs to index.", file=sys.stderr)
            return None

        from langchain_community.vectorstores import FAISS
        vs = FAISS.from_documents(docs, embeddings)
        retriever = vs.as_retriever(search_kwargs={"k": max(3, k)})

        # 4c. Define a query to find relevant paragraphs about goodwill allocation.
        query = (
            "goodwill amount recorded recognized purchase price allocation "
            "'recorded as goodwill' 'Goodwill of approximately' amount value currency"
        )

        # 4d. (Optional) Print the most similar paragraphs for debugging.
        if print_retrieval:
            try:
                hits = vs.similarity_search_with_score(query, k=max(3, k))
                print(f"\n[retriever] top {len(hits)} paragraphs (lower score is closer):")
                for rank, (doc, score) in enumerate(hits, 1):
                    print(f"\n--- #{rank} | score={score:.4f} ---")
                    print(doc.page_content)
                    # Quick one-line preview if helpful
                    print("\n[preview]", textwrap.shorten(doc.page_content.replace("\n", " "), width=200))
                print("\n[end retriever dump]\n")
            except Exception as e:
                print(f"[retriever] could not print hits: {e}", file=sys.stderr)

        # 5. If no OpenAI key, stop here. The retrieval part is still useful for debugging.
        if not os.getenv("OPENAI_API_KEY"):
            if verbose: print("[goodwill LLM] OPENAI_API_KEY not set; skipping LLM step.", file=sys.stderr)
            return None

        # LLM + prompt (IMPORTANT: includes {context})
        from langchain_openai import ChatOpenAI
        from langchain.prompts import ChatPromptTemplate
        from langchain.chains import RetrievalQA

        # 6a. Initialize the LLM and the prompt template.
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        prompt = ChatPromptTemplate.from_template(
            "You are a precise financial extraction assistant.\n"
            "Use ONLY the context to extract the monetary amount(s) explicitly recorded as goodwill.\n"
            "Return ONLY the amount(s) with units/currency (e.g., \"$129 million\").\n"
            "If no goodwill amount is present, answer exactly: No goodwill amount found.\n\n"
            "Context:\n{context}\n\n"
            "Question: {question}"
        )

        # 6b. Create the RetrievalQA chain that combines the retriever and LLM.
        qa = RetrievalQA.from_chain_type(
            llm=llm,
            retriever=retriever,
            chain_type="stuff",
            chain_type_kwargs={"prompt": prompt},
            return_source_documents=False,
        )

        # 6c. Invoke the chain and get the answer.
        result = qa.invoke({"query": query})
        answer = (result.get("result") or result.get("output_text") or "").strip()

        if verbose:
            print(f"[goodwill LLM] Raw answer: {answer!r}", file=sys.stderr)

        # 7. Process the LLM's raw output.
        if not answer or answer.lower().startswith("no goodwill"):
            return None

        # Extract structured amounts from the free-text answer and return them.
        amounts = _extract_amounts(answer)
        return "; ".join(amounts) if amounts else (answer or None)

    except Exception as e:
        if verbose:
            import traceback
            print(f"[goodwill LLM] Exception: {e}", file=sys.stderr)
            traceback.print_exc()
        return None
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

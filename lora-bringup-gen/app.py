# app.py — minimal Streamlit UI for generate_plan.py (MD + CSV outputs)
# Usage:
#   pip install streamlit pyarrow pyyaml toml
#   streamlit run app.py

import streamlit as st
import subprocess, sys, tempfile, json, shutil
from pathlib import Path
from datetime import datetime

st.set_page_config(page_title="Plan Generator", layout="centered")
st.title("Plan Generator")

ipc_file = st.file_uploader("Upload .ipc file", type=["ipc"])
run = st.button("Generate", type="primary", use_container_width=True)

def run_cmd(cmd):
    """Run a command and return (code, stdout, stderr)."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr

if run:
    if not ipc_file:
        st.error("Please upload a .ipc file first.")
        st.stop()

    # Project layout
    project_root = Path(__file__).resolve().parent
    generator = project_root / "generator/generate_plan.py"
    artifacts = project_root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_md  = artifacts / f"plan_{ts}.md"
    out_csv = artifacts / f"plan_{ts}.csv"

    # We'll save the upload into a *persistent* ./input folder,
    # because many pipelines expect input discovery there.
    input_dir = project_root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    ipc_path = input_dir / ipc_file.name
    ipc_path.write_bytes(ipc_file.getbuffer())

    # Minimal requirements (some scripts require this flag/file)
    # If your script needs specific keys, adjust this content.
    req_dir = Path(tempfile.mkdtemp(prefix="req_"))
    req_path = req_dir / "requirements.yaml"
    req_path.write_text("{}", encoding="utf-8")

    if not generator.exists():
        st.error(f"generate_plan.py not found at: {generator}")
        st.stop()

    # First try: pass --input-dir (if your script supports it)
    base_cmd = [
        sys.executable, str(generator),
        "--requirements", str(req_path),
        "--out-md", str(out_md),
        "--out-csv", str(out_csv),
    ]
    cmd_with_input = base_cmd + ["--input-dir", str(input_dir)]

    with st.spinner("Generating plan..."):
        code, stdout, stderr = run_cmd(cmd_with_input)

        # Auto-fallback: if --input-dir is not recognized, re-run without it
        if code != 0 and ("unrecognized arguments: --input-dir" in stderr or
                          "no such option: --input-dir" in stderr):
            code, stdout, stderr = run_cmd(base_cmd)

    # Show logs to diagnose quickly (kept simple)
    st.subheader("Execution log")
    st.code(stdout or "(no stdout)", language="bash")

    if code != 0:
        st.subheader("Error output")
        st.code(stderr or "(no stderr)", language="bash")
        st.error("Generation failed. See error output above.")
        st.stop()

    # Success: offer downloads if files exist
    success = False
    if out_md.exists():
        success = True
        with open(out_md, "rb") as f:
            st.download_button(
                "Download plan.md",
                data=f.read(),
                file_name=out_md.name,
                mime="text/markdown",
                use_container_width=True,
            )
    if out_csv.exists():
        success = True
        with open(out_csv, "rb") as f:
            st.download_button(
                "Download plan.csv",
                data=f.read(),
                file_name=out_csv.name,
                mime="text/csv",
                use_container_width=True,
            )

    if success:
        st.success("Done.")
    else:
        st.warning("Generation finished, but no output files were found.")

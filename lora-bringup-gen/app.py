# app.py — ultra-minimal UI for ipc_to_plan_llm.py + OpenAI API key
# Usage:
#   pip install streamlit
#   streamlit run app.py

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Test Plan Generator", layout="centered")
st.title("Test Plan Generator")

# 1) OpenAI API key (masked)
api_key = st.text_input("OpenAI API Key", type="password")

# 2) Single file upload (ANY file type)
uploaded = st.file_uploader("Upload file")  # no 'type=' => accepts any file

# 3) Generate button
run = st.button("Generate", type="primary", use_container_width=True)

def run_cmd(cmd, extra_env=None):
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout, proc.stderr

if run:
    # Minimal validation
    if not api_key:
        st.error("Please enter your OpenAI API key.")
        st.stop()
    if not uploaded:
        st.error("Please upload a file first.")
        st.stop()

    project_root = Path(__file__).resolve().parent
    script = project_root / "generator/ipc_to_plan_llm.py"  # your generator script
    artifacts = project_root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_docx = artifacts / f"TestPlan_{ts}.docx"

    # Save the uploaded file to a temp path and pass that path as --ipc
    tmp_dir = Path(tempfile.mkdtemp(prefix="ipc_input_"))
    try:
        input_path = tmp_dir / uploaded.name
        input_path.write_bytes(uploaded.getbuffer())

        if not script.exists():
            st.error(f"Script not found: {script}")
            st.stop()

        with st.spinner("Generating..."):
            cmd = [
                sys.executable, str(script),
                "--ipc", str(input_path),          # script requires --ipc (path can be any file)
                "--out-docx", str(out_docx),       # required output
                # Optional flags (uncomment if your script uses them):
                # "--out-md", str(artifacts / f"plan_{ts}.md"),
                # "--board-hint", "YOUR_HINT",
                # "--meta", str(project_root / "meta.json"),
            ]
            code, stdout, stderr = run_cmd(cmd, extra_env={"OPENAI_API_KEY": api_key})

        # Logs (kept minimal: only show on demand)
        with st.expander("Execution log", expanded=False):
            st.code(stdout or "(no stdout)", language="bash")
        if code != 0:
            with st.expander("Error output", expanded=True):
                st.code(stderr or "(no stderr)", language="bash")
            st.error("Generation failed.")
            st.stop()

        if out_docx.exists():
            st.success("Done.")
            with open(out_docx, "rb") as f:
                st.download_button(
                    "Download plan.docx",
                    data=f.read(),
                    file_name=out_docx.name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )
        else:
            st.error("No output file produced.")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

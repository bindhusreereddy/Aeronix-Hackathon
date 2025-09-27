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

st.set_page_config(page_title="Plan Generator", layout="centered")
st.title("Plan Generator")

# 1) API key (masked). Stored only in memory for this session.
api_key = st.text_input("OpenAI API Key", type="password", help="Required to generate the document.")

# 2) Single file upload (.ipc)
ipc_file = st.file_uploader("Upload .ipc file", type=["ipc"])

# 3) Generate button
run = st.button("Generate", type="primary", use_container_width=True)

def run_cmd(cmd, extra_env=None):
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout, proc.stderr

if run:
    # Basic validations (keep UI minimal but helpful)
    if not api_key:
        st.error("Please enter your OpenAI API key.")
        st.stop()
    if not ipc_file:
        st.error("Please upload a .ipc file first.")
        st.stop()

    project_root = Path(__file__).resolve().parent
    script = project_root / "generator/ipc_to_plan_llm.py"  # your generator script
    artifacts = project_root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_docx = artifacts / f"plan_{ts}.docx"

    tmp_dir = Path(tempfile.mkdtemp(prefix="ipc_"))
    try:
        # Save uploaded IPC into a temp file
        ipc_path = tmp_dir / ipc_file.name
        ipc_path.write_bytes(ipc_file.getbuffer())

        if not script.exists():
            st.error(f"Script not found: {script}")
            st.stop()

        with st.spinner("Generating..."):
            cmd = [
                sys.executable, str(script),
                "--ipc", str(ipc_path),
                "--out-docx", str(out_docx),
                # If your script also supports optional outputs/flags, add them here:
                # "--out-md", str(artifacts / f"plan_{ts}.md"),
                # "--board-hint", "XYZ",
                # "--meta", "some.json",
            ]
            # Pass the API key to the subprocess as an env var
            code, stdout, stderr = run_cmd(cmd, extra_env={"OPENAI_API_KEY": api_key})

        # Logs (kept visible for quick debugging)
        st.subheader("Execution log")
        st.code(stdout or "(no stdout)", language="bash")

        if code != 0:
            st.subheader("Error output")
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

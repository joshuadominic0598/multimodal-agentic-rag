"""Start or stop the personal desktop server."""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from app.core.paths import ROOT

def main():
    root = ROOT
    port = int(os.environ.get("AGENTIC_RAG_PORT", "8020"))
    url = f"http://127.0.0.1:{port}"

    def running():
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                obj = json.load(response)
                return obj if obj.get("app") == "agentic-rag" else None
        except Exception:
            return None

    if "--stop" in sys.argv:
        current = running()
        if current:
            os.kill(current["pid"], signal.SIGTERM)
            for _ in range(100):
                if not running():
                    break
                time.sleep(0.1)
            print("Agentic RAG stopped.")
        else:
            print("Agentic RAG is not running on this port.")
        raise SystemExit
    if not running():
        python = Path(sys.executable)
        if not python.exists():
            raise SystemExit("Run scripts/setup.command first to install the local environment.")
        (root / "data").mkdir(exist_ok=True)
        with open(root / "data/server.log", "ab") as log:
            subprocess.Popen(
                [
                    str(python),
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=root,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        for _ in range(60):
            if running():
                break
            time.sleep(0.25)
        else:
            raise SystemExit(
                "Agentic RAG could not start. Check data/server.log, or choose another AGENTIC_RAG_PORT."
            )
    print("Agentic RAG is ready at " + url)
    if os.environ.get("OPEN_BROWSER", "1") != "0":
        webbrowser.open(url)

if __name__ == "__main__":
    main()

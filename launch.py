"""Set up and launch Paper Radio using only Python's standard library."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import venv
import webbrowser
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

PROJECT = Path(__file__).resolve().parent
IMPORT_CHECK = (
    "import fastapi, uvicorn, python_multipart, pypdf, numpy, faiss, openai, httpx, dotenv"
)


def environment_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def dependency_signature(root: Path) -> str:
    return hashlib.sha256((root / "requirements.txt").read_bytes()).hexdigest()


def dependencies_ready(python: Path) -> bool:
    try:
        result = subprocess.run(
            [str(python), "-c", IMPORT_CHECK],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        return result.returncode == 0
    except OSError:
        return False


def prepare(root: Path = PROJECT) -> Path:
    python = environment_python(root)
    if not python.is_file():
        print("First launch: creating Paper Radio's Python environment…", flush=True)
        venv.EnvBuilder(with_pip=True).create(root / ".venv")
    stamp = root / ".venv" / ".paper-radio-requirements"
    signature = dependency_signature(root)
    cached = stamp.read_text().strip() if stamp.exists() else ""
    if cached != signature or not dependencies_ready(python):
        print("Installing Paper Radio's dependencies. First launch may take a few minutes…", flush=True)
        subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check",
             "-r", str(root / "requirements.txt")],
            cwd=root, check=True,
        )
        if not dependencies_ready(python):
            raise RuntimeError("Dependency installation finished, but a required package cannot be imported.")
        stamp.write_text(signature + "\n")
    example = root / ".env.example"
    if not (root / ".env").exists() and example.exists():
        shutil.copyfile(example, root / ".env")
    return python


def available_port(start: int) -> int:
    if not 1 <= start <= 65535:
        raise ValueError("Choose a port between 1 and 65535.")
    for port in range(start, min(start + 11, 65536)):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free local port was found. Close the old app window and try again.")


def wait_until_ready(process: subprocess.Popen, url: str, timeout: float = 30) -> None:
    opener = build_opener(ProxyHandler({}))
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError("The server exited during startup. Check the error above.")
        try:
            with opener.open(url + "/health", timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            time.sleep(0.15)
    raise RuntimeError("The server did not become ready. Check the error above.")


def start(python: Path, root: Path, port: int, open_browser: bool) -> int:
    url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [str(python), str(root / "run.py"), "--port", str(port)],
        cwd=root, env=dict(os.environ, PYTHONNOUSERSITE="1"),
    )
    try:
        wait_until_ready(process, url)
        print(f"\nPaper Radio is ready: {url}\nKeep this window open. Press Ctrl+C to stop.\n", flush=True)
        if open_browser:
            try:
                webbrowser.open(url)
            except webbrowser.Error:
                print(f"Open this address in your browser: {url}", flush=True)
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="Install dependencies and open Paper Radio.")
    parser.add_argument("--no-browser", action="store_true", help="Start the app without opening a browser.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        print("Paper Radio needs Python 3.11 or newer.", file=sys.stderr)
        return 1
    try:
        python = prepare()
        return start(python, PROJECT, available_port(args.port), not args.no_browser)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"\nSetup could not finish: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

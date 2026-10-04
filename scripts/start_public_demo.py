"""Start only the isolated public demo stack; secrets arrive through psst.

psst GOOGLE_AI_STUDIO_API_KEY KONTROFERTA_SESSION_SECRET -- .venv/Scripts/python.exe -m scripts.start_public_demo --base-url https://chosen.example --build
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    origin = args.base_url.rstrip("/")
    url = urlparse(origin)
    if url.scheme != "https" and url.hostname not in {"localhost", "127.0.0.1"}:
        parser.error("Public origin must use HTTPS")
    if url.path or url.query or url.fragment or url.username or url.password:
        parser.error("Provide only the origin, without a path or credentials")
    environment = dict(os.environ)
    if not environment.get("GOOGLE_AI_STUDIO_API_KEY") or len(environment.get("KONTROFERTA_SESSION_SECRET", "")) < 32:
        parser.error("Inject GOOGLE_AI_STUDIO_API_KEY and KONTROFERTA_SESSION_SECRET using psst")
    environment["KONTROFERTA_SESSION_SECRET"] = hashlib.sha256(
        ("kontroferta-public-demo:" + environment["KONTROFERTA_SESSION_SECRET"]).encode()).hexdigest()
    environment["APP_BASE_URL"] = origin
    command = ["docker", "compose", "-f", "compose.public-demo.yaml", "up", "-d"]
    if args.build:
        command.append("--build")
    subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=environment, check=True)
    print("Public demo started with an independent data volume and restart policy.")


if __name__ == "__main__":
    main()

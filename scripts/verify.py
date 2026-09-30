"""Run the assignment's tests and demo in a fresh, disposable database."""

import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[1]


def main():
    environment = {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}
    for name in ("POSTGRES_PASSWORD", "IRIS_NRW_PASSWORD", "IRIS_PEAT_PASSWORD",
                 "IRIS_PROMOTER_PASSWORD", "IRIS_APP_PASSWORD"):
        environment[name] = secrets.token_hex(24)

    with tempfile.TemporaryDirectory(prefix="iris-verify-") as folder:
        empty_env = Path(folder) / "empty.env"
        empty_env.touch()
        command = [
            "docker", "compose", "--env-file", str(empty_env),
            "--project-name", f"iris-verify-{uuid.uuid4().hex[:12]}",
            "--file", str(ROOT / "compose.verify.yaml"),
        ]

        def run(*args, check=True):
            return subprocess.run(
                command + list(args), cwd=ROOT, env=environment, check=check,
            )

        failed = False
        try:
            print("Building the assignment and starting a fresh database.", flush=True)
            run("build", "verify")
            run("up", "-d", "--wait", "db")
            run("run", "--rm", "-T", "verify")
            print("Demonstrating contributor ingestion, promotion, and app reads.", flush=True)
            run("run", "--rm", "-T", "verify", "python", "-m", "iris")
        except (subprocess.CalledProcessError, KeyboardInterrupt):
            failed = True
            run("logs", "--tail", "50", "db", check=False)
        finally:
            if run("down", "--volumes", "--remove-orphans", "--rmi", "local", check=False).returncode:
                failed = True
        if failed:
            raise SystemExit(1)
        print("Tests and demo passed. Temporary database removed.", flush=True)


if __name__ == "__main__":
    main()

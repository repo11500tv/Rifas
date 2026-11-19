"""Emitir solicitudes de aprobación de un solo uso para firmar fuera del destino."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
from uuid import uuid4

from deployment.artifact import verify_signature

IDENTITY = "rifas-operator"
MAX_AGE = timedelta(hours=1)
START_OPERATIONS = {"apply", "intervene"}
RECOVERY_OPERATIONS = {"recover", "recover-intervention"}


def namespace(environment):
    return f"rifas-approval-v1-{environment}"


def request(operation, environment, root, fingerprint, run=None):
    nonce = uuid4().hex
    if (operation not in START_OPERATIONS | RECOVERY_OPERATIONS or environment not in {"synthetic", "staging", "production"}
            or not re.fullmatch(r"[a-f0-9]{64}", fingerprint)
            or (operation in RECOVERY_OPERATIONS and not re.fullmatch(r"[a-f0-9]{32}", run or ""))
            or (operation in START_OPERATIONS and run is not None)
            or not Path(root).is_absolute()):
        raise ValueError("Alcance de aprobación inválido")
    return {
        "format": 1, "operation": operation, "environment": environment, "installation": str(root),
        "digest": fingerprint, "run": run or nonce, "nonce": nonce,
        "expires": (datetime.now(timezone.utc) + MAX_AGE).isoformat(),
    }


def verified(path, signers, operation, environment, root, fingerprint, run=None):
    try:
        raw = verify_signature(path, Path(str(path) + ".sig"), signers, IDENTITY, namespace(environment))
        data = json.loads(raw)
        now = datetime.now(timezone.utc)
        expires = datetime.fromisoformat(data["expires"])
        expected = request(operation, environment, root, fingerprint, run)
        if (data.keys() != expected.keys() or not now < expires <= now + MAX_AGE
                or not re.fullmatch(r"[a-f0-9]{32}", data["nonce"])):
            raise ValueError("Formato o caducidad incorrectos")
        for key in ("format", "operation", "environment", "installation", "digest"):
            if data[key] != expected[key]:
                raise ValueError("Alcance incorrecto")
        if data["run"] != (data["nonce"] if operation in START_OPERATIONS else run):
            raise ValueError("Ejecución incorrecta")
        return data
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as error:
        raise ValueError("Aprobación inválida, caducada o fuera de alcance") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=sorted(START_OPERATIONS | RECOVERY_OPERATIONS))
    parser.add_argument("--environment", required=True)
    parser.add_argument("--installation", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--run")
    args = parser.parse_args()
    print(json.dumps(request(args.operation, args.environment, args.installation, args.digest, args.run),
                     sort_keys=True))


if __name__ == "__main__":
    main()

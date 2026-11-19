"""Build an unsigned candidate from an explicitly reviewed Git commit."""

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

NAMESPACE = "rifas-deploy-v1"
IDENTITY = "rifas-release"
MANIFEST = "manifest.json"
SIGNATURE = "manifest.json.sig"


def git(repository, *arguments):
    return subprocess.check_output(["git", "-C", str(repository), *arguments])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def payload_path(name):
    path = PurePosixPath(name)
    if str(path) != name or any(part in (".", "..") for part in path.parts):
        raise ValueError(f"Ruta de artefacto inválida: {name}")
    if name != "wsgi.py" and (
        not name.startswith("platform_app/") or path.suffix not in (".py", ".html")
    ):
        raise ValueError(f"Ruta de artefacto no autorizada: {name}")
    return path


def platform_version(data):
    tree = ast.parse(data)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PLATFORM_VERSION"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError("El código no declara PLATFORM_VERSION")


def build(repository, commit, recipe_path, output):
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Se requiere el SHA completo del commit revisado")
    if git(repository, "rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip() != commit:
        raise ValueError("La referencia debe ser un commit")
    recipe_path = PurePosixPath(recipe_path)
    if recipe_path.parent != PurePosixPath("deployment/packages") or recipe_path.suffix != ".json":
        raise ValueError("La receta debe estar en deployment/packages")
    recipe = json.loads(git(repository, "show", f"{commit}:{recipe_path}"))
    if set(recipe) != {"package", "version", "platform_from", "platform_to", "schema", "migration", "checks"}:
        raise ValueError("Receta inválida")
    files = {}
    entries = git(repository, "ls-tree", "-rz", commit, "--", "platform_app", "wsgi.py")
    for entry in entries.rstrip(b"\0").split(b"\0"):
        metadata, name = entry.decode().split("\t", 1)
        mode, kind, object_id = metadata.split()
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ValueError(f"Entrada Git no regular: {name}")
        payload_path(name)
        files[name] = git(repository, "cat-file", "blob", object_id)
    if "wsgi.py" not in files or platform_version(files["platform_app/__init__.py"]) != recipe["platform_to"]:
        raise ValueError("Código incompatible con la receta")
    manifest = {
        **recipe,
        "format": 1,
        "commit": commit,
        "recipe": str(recipe_path),
        "files": {name: digest(data) for name, data in files.items()},
    }
    output.mkdir(mode=0o700)
    for name, data in files.items():
        path = output / "payload" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (output / MANIFEST).write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return digest((output / MANIFEST).read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--commit", required=True)
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.repository, args.commit, args.recipe, args.output))


if __name__ == "__main__":
    main()

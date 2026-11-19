"""SQLite contracts and registered migrations used by all deployment phases."""

import ast
from contextlib import closing
import importlib.util
from pathlib import Path
import re
import sqlite3

MIGRATIONS = {None, "sorteos-2.4.0"}
CONTRACTS = {"sorteos-v2"}
TEMPLATE = Path("central/plantillas/entidad_maestra.sqlite3")
CENTRAL = Path("central/plataforma.sqlite")
RAFFLE_COLUMNS = {"image_filename": "TEXT", "extended_info": "TEXT"}


def connect(path, mode):
    connection = sqlite3.connect(f"{path.as_uri()}?{mode}", uri=True, timeout=15)
    connection.execute("PRAGMA foreign_keys=ON")
    if mode == "mode=rw":
        connection.execute("PRAGMA synchronous=FULL")
    return connection


def inspect(connection):
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("SQLite no íntegra")
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("SQLite contiene referencias inválidas")


def safe_database(root, relative, dry):
    path = root / relative
    if path.resolve() != path or not path.is_file():
        raise ValueError(f"Base ausente o ruta insegura: {relative}")
    if dry and any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-journal", "-shm")):
        raise ValueError(f"Simulación requiere una copia estable sin archivos auxiliares: {relative}")
    return path


def inventory(root, dry):
    mode = "mode=ro&immutable=1" if dry else "mode=ro"
    with closing(connect(safe_database(root, CENTRAL, dry), mode)) as connection:
        inspect(connection)
        slugs = [row[0] for row in connection.execute("SELECT slug FROM entities ORDER BY slug")]
    if any(not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,49}", slug) for slug in slugs):
        raise ValueError("Catálogo central contiene un slug inválido")
    entities = root / "entidades"
    if not entities.is_dir() or entities.resolve() != entities:
        raise ValueError("Directorio de entidades ausente o inseguro")
    expected = {Path("entidades", slug, "data", "rifas.sqlite3") for slug in slugs}
    observed = {path.relative_to(root) for path in entities.glob("*/data/rifas.sqlite3")}
    if expected != observed:
        raise ValueError(f"Catálogo y disco difieren: {sorted(str(p) for p in expected ^ observed)}")
    return [CENTRAL, TEMPLATE, *sorted(expected)]


def raffle_contract(connection, target):
    versions = connection.execute(
        "SELECT version FROM module_versions WHERE module='sorteos'"
    ).fetchall()
    allowed = {"2.4.0"} if target else {"2.2.0", "2.4.0"}
    if len(versions) != 1 or versions[0][0] not in allowed:
        raise ValueError(f"Versión de sorteos incompatible: {versions}")
    version = versions[0][0]
    columns = {row[1]: row for row in connection.execute("PRAGMA table_info(raffles)")}
    if not columns:
        raise ValueError("Falta la tabla raffles")
    for name, expected in RAFFLE_COLUMNS.items():
        column = columns.get(name)
        if column is None and version == "2.2.0":
            continue
        if column is None or (column[2].upper(), column[3], column[4], column[5]) != (expected, 0, None, 0):
            raise ValueError(f"Columna de sorteos incompatible: {name}")
    if target:
        definitions = connection.execute(
            "SELECT name, sql FROM sqlite_schema "
            "WHERE tbl_name IN ('raffles', 'module_versions') "
            "AND type IN ('table', 'index', 'trigger') ORDER BY name"
        ).fetchall()
        return list(columns.values()), [(name, sql_tokens(sql or "")) for name, sql in definitions]
    return version


def sql_tokens(sql):
    # Preserve quoted values while ignoring whitespace outside SQL tokens.
    return tuple(
        token if token[0] in "'\"`[" else token.casefold()
        for token in re.findall(r"""'(?:''|[^'])*'|"(?:""|[^"])*"|`[^`]*`|\[[^\]]*\]|\w+|[^\s]""", sql)
    )


def expected_raffles(payload):
    path = payload / "platform_app/raffle_schema.py"
    for node in ast.parse(path.read_bytes()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(name, ast.Name) and name.id == "SCHEMA_RAFFLES" for name in node.targets
        ):
            with closing(sqlite3.connect(":memory:")) as connection:
                connection.execute(ast.literal_eval(node.value))
                columns = connection.execute("PRAGMA table_info(raffles)").fetchall()
                ddl = connection.execute("SELECT sql FROM sqlite_schema WHERE name='raffles'").fetchone()[0]
                return columns, sql_tokens(ddl)
    raise ValueError("El código no declara SCHEMA_RAFFLES")


def validate(root, contract_name, *, expected=None, target=False, dry=False):
    databases = inventory(root, dry)
    mode = "mode=ro&immutable=1" if dry else "mode=ro"
    template_contract = None
    for relative in databases[1:]:
        path = safe_database(root, relative, dry)
        with closing(connect(path, mode)) as connection:
            inspect(connection)
            if contract_name == "sorteos-v2":
                contract = raffle_contract(connection, target)
                if target and expected is not None:
                    columns, definitions = contract
                    if (columns, dict(definitions)["raffles"]) != expected:
                        raise ValueError(f"Tabla raffles incompatible con el código: {relative}")
                if relative == TEMPLATE:
                    template_contract = contract
                elif target and contract != template_contract:
                    raise ValueError(f"Esquema de sorteos distinto de la plantilla: {relative}")
        if dry:
            safe_database(root, relative, dry)
    if dry:
        safe_database(root, CENTRAL, dry)
    return databases


def migrate(root, databases, name, payload, event):
    if name is None:
        return
    path = payload / "platform_app/raffle_migration.py"
    spec = importlib.util.spec_from_file_location("rifas_release_migration", path)
    module = importlib.util.module_from_spec(spec)
    # Cargar el código firmado sin generar __pycache__ en el release.
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    for relative in databases[1:]:
        with closing(connect(root / relative, "mode=rw")) as connection:
            if raffle_contract(connection, target=False) == "2.4.0":
                event("migration_skipped", database=str(relative), reason="already_current")
                continue
            result = module.migrate_raffles(connection, update_version=True)
        event("migrated", database=str(relative), result=result)

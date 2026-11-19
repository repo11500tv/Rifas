"""SQLite contracts and registered migrations used by all deployment phases."""

import ast
from contextlib import closing
import importlib.util
from pathlib import Path
import re
import sqlite3

TEMPLATE = Path("central/plantillas/entidad_maestra.sqlite3")
CENTRAL = Path("central/plataforma.sqlite")


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
    for candidate in (path, *(Path(str(path) + suffix) for suffix in ("-wal", "-journal", "-shm"))):
        if candidate.is_symlink() or (candidate.exists() and (
            not candidate.is_file() or candidate.stat().st_nlink != 1
        )):
            raise ValueError(f"SQLite o archivo auxiliar compartido o inseguro: {relative}")
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


def version(connection, contract, target):
    rows = connection.execute(
        "SELECT version FROM module_versions WHERE module=?", (contract["module"],)
    ).fetchall()
    allowed = [contract["to"]] if target else [*contract["from"], contract["to"]]
    if len(rows) != 1 or rows[0][0] not in allowed:
        raise ValueError(f"Versión de {contract['module']} incompatible: {rows}")
    return rows[0][0]


def definitions(connection, tables):
    return {
        table: [(kind, name, sql_tokens(sql or "")) for kind, name, sql in connection.execute(
            "SELECT type, name, sql FROM sqlite_schema WHERE tbl_name=? "
            "AND type IN ('table', 'index', 'trigger') ORDER BY type, name", (table,)
        )] for table in tables
    }


def sql_tokens(sql):
    # Preserve quoted values while ignoring whitespace outside SQL tokens.
    return tuple(
        token if token[0] in "'\"`[" else token.casefold()
        for token in re.findall(r"""'(?:''|[^'])*'|"(?:""|[^"])*"|`[^`]*`|\[[^\]]*\]|\w+|[^\s]""", sql)
    )


def referenced_files(contract, migration):
    if (not isinstance(contract, dict) or set(contract) != {"module", "from", "to", "tables"}
            or not all(isinstance(contract[key], str) and contract[key] for key in ("module", "to"))
            or not isinstance(contract["from"], list)
            or any(not isinstance(value, str) for value in contract["from"])
            or not isinstance(contract["tables"], dict) or not contract["tables"]):
        raise ValueError("Contrato SQLite inválido")
    paths = set()
    for table, reference in contract["tables"].items():
        if (not table.isidentifier() or not isinstance(reference, dict)
                or set(reference) != {"file", "symbol"} or not reference["symbol"].isidentifier()):
            raise ValueError("Referencia de esquema SQLite inválida")
        paths.add(reference["file"])
    if migration is not None:
        if (not isinstance(migration, dict) or set(migration) != {"file", "function", "arguments"}
                or not migration["function"].isidentifier() or not isinstance(migration["arguments"], dict)):
            raise ValueError("Migración declarada inválida")
        paths.add(migration["file"])
    return paths


def expected_schema(payload, contract):
    expected = {}
    for table, reference in contract["tables"].items():
        tree = ast.parse((payload / reference["file"]).read_bytes())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(name, ast.Name) and name.id == reference["symbol"] for name in node.targets
            ):
                with closing(sqlite3.connect(":memory:")) as connection:
                    connection.set_authorizer(lambda action, *_: (
                        sqlite3.SQLITE_DENY if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH,
                                                         sqlite3.SQLITE_PRAGMA) else sqlite3.SQLITE_OK
                    ))
                    connection.executescript(ast.literal_eval(node.value))
                    ddl = connection.execute(
                        "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (table,)
                    ).fetchone()
                    if ddl is not None:
                        expected[table] = sql_tokens(ddl[0])
                break
        if table not in expected:
            raise ValueError(f"El código no declara la tabla {table}")
    return expected


def validate(root, contract, *, expected=None, target=False, dry=False):
    databases = inventory(root, dry)
    mode = "mode=ro&immutable=1" if dry else "mode=ro"
    template = None
    for relative in databases[1:]:
        path = safe_database(root, relative, dry)
        with closing(connect(path, mode)) as connection:
            inspect(connection)
            current = version(connection, contract, target)
            if expected is not None and current == contract["to"]:
                actual = definitions(connection, {"module_versions", *expected})
                for table, ddl in expected.items():
                    if ("table", table, ddl) not in actual[table]:
                        raise ValueError(f"Tabla {table} incompatible con el código: {relative}")
                if target:
                    if relative == TEMPLATE:
                        template = actual
                    elif actual != template:
                        raise ValueError(f"Esquema distinto de la plantilla: {relative}")
        if dry:
            safe_database(root, relative, dry)
    if dry:
        safe_database(root, CENTRAL, dry)
    return databases


def migrate(root, databases, contract, migration, payload, event):
    if migration is None:
        return
    path = payload / migration["file"]
    spec = importlib.util.spec_from_file_location("rifas_release_migration", path)
    module = importlib.util.module_from_spec(spec)
    # El contenido pertenece al payload privado, verificado antes del drenaje.
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    operation = getattr(module, migration["function"])
    for relative in databases[1:]:
        with closing(connect(root / relative, "mode=rw")) as connection:
            if version(connection, contract, target=False) == contract["to"]:
                event("migration_skipped", database=str(relative), reason="already_current")
                continue
            operation(connection, **migration["arguments"])
            version(connection, contract, target=True)
        event("migrated", database=str(relative))

"""Limpieza controlada de fotografias de sorteos."""

from pathlib import Path
import sqlite3

from platform_app.raffle_image_storage import valid_filename


def cleanup_unreferenced_image(entity_directory, filename):
    """Elimina una imagen solamente si ningun sorteo la referencia."""

    if not valid_filename(filename):
        return False

    entity_directory = Path(entity_directory).resolve()
    database = entity_directory / "data" / "rifas.sqlite3"
    directory = entity_directory / "uploads" / "sorteos"

    if not directory.is_dir() or directory.is_symlink():
        return False

    if not database.is_file():
        return False

    with sqlite3.connect(
        database.resolve().as_uri() + "?mode=ro",
        uri=True
    ) as con:
        references = con.execute(
            "SELECT COUNT(*) FROM raffles WHERE image_filename=?",
            (filename,)
        ).fetchone()[0]

    if references:
        return False

    path = directory / filename

    if path.is_symlink() or not path.is_file():
        return False

    path.unlink()
    return True

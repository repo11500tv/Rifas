import io
import os
import secrets
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_LOGO_SIZE = 2 * 1024 * 1024
MAX_PIXELS = 4_000_000

FORMATS = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "WEBP": ".webp",
}


def validate_logo(file_storage):
    data = file_storage.stream.read(MAX_LOGO_SIZE + 1)

    if not data or len(data) > MAX_LOGO_SIZE:
        raise ValueError("El archivo debe ocupar como maximo 2 MB")

    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = image.format

            if image_format not in FORMATS:
                raise ValueError("Formato no permitido")

            if image.width * image.height > MAX_PIXELS:
                raise ValueError("Dimensiones excesivas")

            image.verify()

        with Image.open(io.BytesIO(data)) as image:
            image.load()

    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("Imagen no valida") from exc

    return data, FORMATS[image_format]


def save_logo(file_storage, entity_directory):
    data, extension = validate_logo(file_storage)

    entity_directory = Path(entity_directory).resolve()
    destination = entity_directory / "uploads" / "logos"

    if not destination.is_dir() or destination.is_symlink():
        raise ValueError("Directorio de logotipos no disponible")

    filename = "logo_" + secrets.token_hex(16) + extension
    path = destination / filename

    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o640,
    )

    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise

    return filename

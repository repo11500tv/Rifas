"""Almacenamiento seguro de fotografias de sorteos."""
import io
import os
import re
import secrets
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_PIXELS = 12_000_000
MAX_DIMENSION = 2400

FORMATS = {
    "PNG": (".png", "PNG"),
    "JPEG": (".jpg", "JPEG"),
    "WEBP": (".webp", "WEBP"),
}

FILENAME_PATTERN = re.compile(
    r"^premio_[0-9a-f]{32}\.(png|jpg|webp)$"
)

def validate_image(upload):
    data = upload.stream.read(MAX_IMAGE_SIZE + 1)

    if not data or len(data) > MAX_IMAGE_SIZE:
        raise ValueError("La fotografia debe ocupar como maximo 5 MB.")

    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = image.format
            if image_format not in FORMATS:
                raise ValueError("Formato no permitido: utiliza JPEG, PNG o WebP.")

            if image.width * image.height > MAX_PIXELS:
                raise ValueError("La imagen tiene demasiados pixeles.")

            image.verify()

        with Image.open(io.BytesIO(data)) as image:
            image.load()
            image = ImageOps.exif_transpose(image)
            image.thumbnail((MAX_DIMENSION, MAX_DIMENSION))

            extension, output_format = FORMATS[image_format]
            if output_format == "JPEG":
                image = image.convert("RGB")
            elif image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")

            output = io.BytesIO()
            image.save(output, format=output_format)
            result = output.getvalue()

    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
    ) as exc:
        raise ValueError("El archivo no contiene una imagen valida.") from exc

    if len(result) > MAX_IMAGE_SIZE:
        raise ValueError("La imagen procesada supera 5 MB.")

    return result, extension

def save_raffle_image(upload, entity_directory):
    data, extension = validate_image(upload)

    entity_directory = Path(entity_directory).resolve()
    destination = entity_directory / "uploads" / "sorteos"

    if not destination.is_dir() or destination.is_symlink():
        raise ValueError("Directorio de fotografias no disponible.")

    filename = "premio_" + secrets.token_hex(16) + extension
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

def valid_filename(filename):
    return bool(FILENAME_PATTERN.fullmatch(filename or ""))

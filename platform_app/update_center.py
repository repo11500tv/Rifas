"""Centro de actualizaciones: validación no ejecutable (fase 1)."""
import hashlib
import html
import io
import json
import re
import zipfile
import subprocess
import tempfile
from pathlib import Path
from pathlib import PurePosixPath
from flask import Blueprint, abort, redirect, render_template_string, request, session, url_for

bp = Blueprint("update_center", __name__, url_prefix="/admin/actualizaciones")
MAX_ZIP_BYTES = 700_000
MAX_FILES = 150
MAX_UNCOMPRESSED = 8_000_000
MAX_SIGNATURE_BYTES = 20_000
PUBLIC_KEY_PATH = Path(__file__).resolve().parents[1] / "rifas_actualizaciones_ed25519.pub"
SIGNING_IDENTITY = "rifas-actualizaciones"
SIGNING_NAMESPACE = "rifas-actualizaciones"


def _superadmin():
    if not session.get("admin"):
        return redirect(url_for("login"))
    return None


def _page(content):
    from platform_app import PAGE
    return render_template_string(PAGE, body=content)


def _validate(data):
    """Inspección de datos no confiables. Nunca escribe ni extrae archivos."""
    if not data or len(data) > MAX_ZIP_BYTES:
        raise ValueError("Tamaño ZIP no permitido (máximo 700 KB).")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        raise ValueError("El archivo no es un ZIP válido.") from None
    with archive as z:
        infos = z.infolist()
        if not infos or len(infos) > MAX_FILES:
            raise ValueError("Cantidad de entradas no permitida.")
        total = 0
        seen = set()
        for entry in infos:
            name = entry.filename
            path = PurePosixPath(name)
            if (not name or name.startswith("/") or "\\" in name
                    or any(part in ("", ".", "..") for part in name.split("/") if part != "")
                    or ":" in name or name.startswith("__MACOSX/")):
                raise ValueError("El ZIP contiene una ruta no permitida.")
            if name in seen:
                raise ValueError("El ZIP contiene nombres duplicados.")
            seen.add(name)
            mode = (entry.external_attr >> 16) & 0o170000
            if mode not in (0, 0o100000, 0o040000):
                raise ValueError("El ZIP contiene enlaces u otros tipos no permitidos.")
            if entry.flag_bits & 1:
                raise ValueError("No se admiten archivos cifrados.")
            total += entry.file_size
            if total > MAX_UNCOMPRESSED:
                raise ValueError("El ZIP supera el límite descomprimido.")
        if "manifest.json" not in seen:
            raise ValueError("Falta manifest.json.")
        try:
            manifest = json.loads(z.read("manifest.json"))
        except (ValueError, UnicodeError, RuntimeError, zipfile.BadZipFile):
            raise ValueError("Manifest JSON incorrecto.") from None
        if not isinstance(manifest, dict):
            raise ValueError("Manifest debe ser un objeto JSON.")
        version = manifest.get("version")
        if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            raise ValueError("Versión del paquete inválida.")
        files = manifest.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError("Manifest debe declarar archivos y sus SHA-256.")
        if set(files) != {n for n in seen if n != "manifest.json" and not n.endswith("/")}:
            raise ValueError("Los archivos no coinciden con el manifest.")
        for name, digest in files.items():
            if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise ValueError("Huella SHA-256 inválida.")
            try:
                actual = hashlib.sha256(z.read(name)).hexdigest()
            except (RuntimeError, zipfile.BadZipFile, KeyError, OSError):
                raise ValueError("Error leyendo archivo del paquete.") from None
            if actual != digest:
                raise ValueError("La huella de un archivo no coincide.")
        return version, len(files), hashlib.sha256(data).hexdigest()


def _verify_signature(data, signature):
    """Verifica una firma SSHSIG Ed25519 sin guardar paquetes en producción."""
    if not signature or len(signature) > MAX_SIGNATURE_BYTES:
        raise ValueError("Firma ausente o demasiado grande (máximo 20 KB).")
    if not signature.startswith(b"-----BEGIN SSH SIGNATURE-----"):
        raise ValueError("El archivo de firma no tiene formato SSHSIG.")
    try:
        key_text = PUBLIC_KEY_PATH.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        raise ValueError("No está configurada la clave pública de actualizaciones.") from None
    fields = key_text.split()
    if len(fields) < 2 or fields[0] != "ssh-ed25519":
        raise ValueError("La clave pública configurada no es Ed25519.")
    # ssh-keygen requiere un archivo allowed_signers; se genera temporalmente.
    try:
        with tempfile.TemporaryDirectory(prefix="rifas_firma_") as directory:
            folder = Path(directory)
            allowed = folder / "allowed_signers"
            sig = folder / "package.sig"
            allowed.write_text(SIGNING_IDENTITY + " " + key_text + "\n", encoding="ascii")
            sig.write_bytes(signature)
            result = subprocess.run(
                ["ssh-keygen", "-Y", "verify", "-f", str(allowed),
                 "-I", SIGNING_IDENTITY, "-n", SIGNING_NAMESPACE, "-s", str(sig)],
                input=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=15, check=False,
            )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("No se ha podido completar la verificación de firma.") from None
    if result.returncode != 0:
        raise ValueError("Firma digital no válida para este paquete o clave pública.")


@bp.route("/", methods=["GET", "POST"])
def home():
    denial = _superadmin()
    if denial is not None:
        return denial
    result = ""
    if request.method == "POST":
        uploaded = request.files.get("package")
        signed = request.files.get("signature")
        if not uploaded or not uploaded.filename.lower().endswith(".zip"):
            result = "<p style='color:#a21d1d'>Selecciona un archivo ZIP.</p>"
        elif not signed or not signed.filename.lower().endswith(".sig"):
            result = "<p style='color:#a21d1d'>Selecciona la firma digital .sig.</p>"
        else:
            data = uploaded.stream.read(MAX_ZIP_BYTES + 1)
            signature = signed.stream.read(MAX_SIGNATURE_BYTES + 1)
            try:
                version, count, sha = _validate(data)
                _verify_signature(data, signature)
                result = ("<div class='notice'><strong>Paquete y firma digital válidos.</strong> "
                          "Versión: " + html.escape(version) + "; archivos: " + str(count) +
                          "; SHA-256 del ZIP: <code>" + sha + "</code>.</div>" +
                          "<p>La firma Ed25519 coincide con la clave pública autorizada. "
                          "El paquete NO se ha instalado ni guardado.</p>")
            except ValueError as exc:
                result = "<p style='color:#a21d1d'>Paquete rechazado: " + html.escape(str(exc)) + "</p>"
    token = html.escape(session.get("_csrf", ""), quote=True)
    return _page("<div class='card'><h2>Centro de actualizaciones</h2>"
                 "<p><strong>Fase 2A: validación y firma digital.</strong> "
                 "No instala, no guarda paquetes y no modifica el código ni las bases de datos.</p>"
                 "<p>Se verifican el manifiesto, las huellas SHA-256 y la firma SSH Ed25519 "
                 "con la clave pública autorizada.</p>"
                 "<form method='post' enctype='multipart/form-data'>"
                 "<input type='hidden' name='_csrf' value='" + token + "'>"
                 "<label>Paquete ZIP (máximo 700 KB)<input type='file' name='package' "
                 "accept='.zip' required></label>"
                 "<label>Firma digital (.zip.sig, máximo 20 KB)<input type='file' "
                 "name='signature' accept='.sig' required></label>"
                 "<button type='submit'>Validar paquete y firma</button>"
                 "</form>" + result + "<p><a href='" + url_for("index") +
                 "'>Volver a la administración central</a></p></div>")

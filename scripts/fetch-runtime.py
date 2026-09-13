"""Fetch the pinned upstream innoextract release, with SHA-256 validation."""
import hashlib
from pathlib import Path
import tempfile
import urllib.request
import zipfile

URL = "https://github.com/dscharrer/innoextract/releases/download/1.9/innoextract-1.9-windows.zip"
SHA256 = "6989342c9b026a00a72a38f23b62a8e6a22cc5de69805cf47d68ac2fec993065"
root = Path(__file__).resolve().parents[1]/"runtime/innoextract"
with urllib.request.urlopen(URL, timeout=60) as response:
    data = response.read(2*1024*1024)
if hashlib.sha256(data).hexdigest() != SHA256:
    raise RuntimeError("innoextract checksum mismatch")
root.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryFile() as temporary:
    temporary.write(data); temporary.seek(0)
    with zipfile.ZipFile(temporary) as archive:
        for member in archive.infolist():
            destination = (root/member.filename).resolve()
            if not destination.is_relative_to(root.resolve()):
                raise RuntimeError("Invalid archive member")
        archive.extractall(root)
print("innoextract 1.9 verified and ready")

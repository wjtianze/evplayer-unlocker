"""Known synthetic fixture; contains no user's content or authorization data."""
from pathlib import Path
import hashlib
import struct
import tempfile
from Crypto.Cipher import AES
from .core import BLOCK_SIZE, SessionKey, block_key, choose_session, convert

PUBLIC_MASTER = b"0123456789abcdef0123456789abcdef"

def fixture(directory):
    # Independently simplified result of applying '+-*/' to sum(master)=2244:
    # each block's suffix is 2251 + floor(3 / index).
    ftyp = struct.pack(">I4s4sI4s4s", 24, b"ftyp", b"isom", 512, b"isom", b"iso2")
    payload = bytes(range(256)) * 2300
    plain = ftyp + struct.pack(">I4s", len(payload)+8, b"mdat") + payload + struct.pack(">I4s", 8, b"moov")
    padded = plain + b"\0" * ((-len(plain)) % 16)
    encrypted = bytearray()
    for number, start in enumerate(range(0, len(padded), BLOCK_SIZE), 1):
        suffix = 2251 + 3//number
        key = hashlib.md5(PUBLIC_MASTER+b"-"+str(suffix).encode()).hexdigest().encode()
        encrypted.extend(AES.new(key, AES.MODE_ECB).encrypt(padded[start:start+BLOCK_SIZE]))
    encrypted.extend(b"Synthetic trailer; not a real course.")
    source = Path(directory)/"synthetic.ev4a"
    source.write_bytes(encrypted)
    return source, plain

def run():
    session = SessionKey(PUBLIC_MASTER, b"+-*/")
    assert block_key(session, 1) == hashlib.md5(PUBLIC_MASTER+b"-2254").hexdigest().encode()
    assert block_key(session, 2) == hashlib.md5(PUBLIC_MASTER+b"-2252").hexdigest().encode()
    with tempfile.TemporaryDirectory(prefix="evplayer-selftest-") as directory:
        source, plain = fixture(directory)
        selected = choose_session(source, [session])
        destination = Path(directory)/"result.mp4"
        convert(source, destination, selected)
        assert destination.read_bytes() == plain

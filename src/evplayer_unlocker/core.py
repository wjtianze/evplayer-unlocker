"""Streaming V4A mode 110 conversion. Does not change the source file."""
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import os
import struct
import tempfile
from collections.abc import Callable
from Crypto.Cipher import AES

BLOCK_SIZE = 0x40000
BOX_TYPES = {b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip", b"uuid", b"moof", b"mfra", b"styp", b"sidx", b"pdin", b"meta"}

class ExportError(Exception):
    """A user-facing, non-secret diagnostic."""

class Cancelled(ExportError):
    pass

@dataclass(frozen=True)
class SessionKey:
    master: bytes = field(repr=False)
    operations: bytes = field(repr=False)

    def __post_init__(self):
        if len(self.master) != 32 or not self.operations or len(self.operations) > 32:
            raise ExportError("播放参数不符合已验证的 V4A 模式。")
        if any(op not in b"+-*/" for op in self.operations):
            raise ExportError("不支持该视频的分块参数。")

def block_key(session: SessionKey, index: int) -> bytes:
    if index < 1:
        raise ValueError("Block index starts at one")
    value = sum(c if c < 128 else c - 256 for c in session.master)
    for op in session.operations:
        if op == 43:
            value += index + 1
        elif op == 45:
            value += 2 - index
        elif op == 42:
            value = value * index + 3
        else:
            value = (abs(value) // index) * (-1 if value < 0 else 1) + 4
        value = ((value + 2**31) % 2**32) - 2**31
    material = session.master + b"-" + str(value).encode("ascii")
    return hashlib.md5(material).hexdigest().encode("ascii")

def inspect_boxes(path: Path):
    size = path.stat().st_size
    position = 0
    result = []
    with path.open("rb") as stream:
        while position + 8 <= size:
            stream.seek(position)
            header = stream.read(16)
            length = struct.unpack(">I", header[:4])[0]
            kind = header[4:8]
            minimum = 8
            if kind not in BOX_TYPES:
                break
            if length == 1:
                if len(header) < 16:
                    break
                length = struct.unpack(">Q", header[8:16])[0]
                minimum = 16
            elif length == 0:
                # A size-zero box would absorb the encrypted trailer. Its true
                # boundary is unverified for this format, so fail closed.
                raise ExportError("不支持长度为零的 MP4 顶层数据块。")
            if length < minimum or position + length > size or kind not in BOX_TYPES:
                break
            result.append({"offset": position, "size": length, "type": kind.decode("ascii")})
            position += length
    return result, position, size - position

def choose_session(source: Path, sessions: list[SessionKey]) -> SessionKey:
    with source.open("rb") as stream:
        encrypted = stream.read(64)
    if len(encrypted) < 32:
        raise ExportError("文件过短，不是支持的 V4A 视频。")
    for session in sessions:
        plain = AES.new(block_key(session, 1), AES.MODE_ECB).decrypt(encrypted[:len(encrypted)//16*16])
        box_size = int.from_bytes(plain[:4], "big")
        if plain[4:8] == b"ftyp" and 16 <= box_size <= 4096:
            return session
    raise ExportError("当前播放参数与此文件不匹配，请先在 EVPlayer 中正常播放同一课程的视频。")

def convert(source: Path, destination: Path, session: SessionKey,
            progress: Callable[[int, int], None] | None = None,
            cancelled: Callable[[], bool] | None = None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise ExportError("输出文件已存在；工具不会覆盖文件。")
    before = source.stat()
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=".evplayer-", suffix=".partial", dir=destination.parent)
    temporary = Path(name)
    digest = hashlib.sha256()
    total = 0
    try:
        with os.fdopen(handle, "wb") as output, source.open("rb") as input_file:
            index = 1
            while block := input_file.read(BLOCK_SIZE):
                if cancelled and cancelled():
                    raise Cancelled("转换已取消。")
                digest.update(block)
                aligned = len(block)//16*16
                output.write(AES.new(block_key(session, index), AES.MODE_ECB).decrypt(block[:aligned]))
                output.write(block[aligned:])
                total += len(block)
                index += 1
                if progress:
                    progress(total, before.st_size)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ExportError("源文件在转换过程中发生变化，已停止输出。")
        atoms, end, trailing = inspect_boxes(temporary)
        if not atoms or atoms[0]["type"] != "ftyp" or not {"moov", "mdat"} <= {a["type"] for a in atoms}:
            raise ExportError("未还原出完整 MP4 结构；参数或格式不匹配。")
        if trailing > 65536:
            raise ExportError("文件尾长度超出已验证范围，未生成结果。")
        if trailing:
            with temporary.open("r+b") as output:
                output.truncate(end)
        # Windows rename is atomic and refuses to replace an existing target.
        # Elsewhere use an exclusive link for the same no-clobber guarantee.
        if os.name == "nt":
            os.rename(temporary, destination)
        else:
            os.link(temporary, destination)
            temporary.unlink()
        return {"name": source.name, "output": destination.name, "source_bytes": total,
                "output_bytes": end, "source_sha256": digest.hexdigest(),
                "removed_trailing_bytes": trailing, "container_verified": True}
    finally:
        temporary.unlink(missing_ok=True)

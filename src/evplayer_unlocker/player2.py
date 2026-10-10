"""Experimental EVPlayer2 5.0.4 x64 EV5/6/7 adapter.

Native AES and key-schedule reconstruction are verified against the official
DLL in Unicorn. Real course files and the Windows process reader have NOT
been validated end to end. Unknown builds and other decryptors are rejected.
"""
from pathlib import Path
import ctypes as C
import hashlib
import os
import struct
import time
from .core import ExportError, Cancelled, FixedAESKey

ENGINE_SHA256 = "9997bfab88148ce1c90c031d353d9d15611f2f6733a7956cec76221971a9897a"
VTABLES = {0x801108: "EV5", 0x801190: "EV6", 0x801200: "EV7"}
AES_DECRYPT_RVA = 0x20110
OBJECT_SIZE = 0x368


def gf_multiply(a, b):
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        a = ((a << 1) ^ (0x11b if a & 0x80 else 0)) & 255
        b >>= 1
    return result


def _sbox(value):
    power, inverse, exponent = value, 1, 254
    while exponent:
        if exponent & 1:
            inverse = gf_multiply(inverse, power)
        power = gf_multiply(power, power)
        exponent >>= 1
    if value == 0:
        inverse = 0
    result = inverse ^ 0x63
    for shift in (1, 2, 3, 4):
        result ^= ((inverse << shift) | (inverse >> (8 - shift))) & 255
    return result


SBOX = bytes(_sbox(value) for value in range(256))


def mix_columns(data, inverse=False):
    if len(data) % 4:
        raise ValueError("Columns must contain four bytes")
    row = (14, 11, 13, 9) if inverse else (2, 3, 1, 1)
    output = bytearray()
    for start in range(0, len(data), 4):
        column = data[start:start + 4]
        for n in range(4):
            value = 0
            for j in range(4):
                value ^= gf_multiply(column[j], row[(j - n) % 4])
            output.append(value)
    return bytes(output)


def decrypt_schedule(key):
    """Exact 240-byte schedule produced by native init(key, 256, decrypt=1)."""
    if len(key) != 32:
        raise ValueError("AES-256 requires 32 bytes")
    words = [key[n:n + 4] for n in range(0, 32, 4)]
    rcon = 1
    for n in range(8, 60):
        temporary = words[-1]
        if n % 8 == 0:
            temporary = bytes(SBOX[x] for x in temporary[1:] + temporary[:1])
            temporary = bytes([temporary[0] ^ rcon]) + temporary[1:]
            rcon = gf_multiply(rcon, 2)
        elif n % 8 == 4:
            temporary = bytes(SBOX[x] for x in temporary)
        words.append(bytes(a ^ b for a, b in zip(words[n - 8], temporary)))
    expanded = b"".join(words)
    return expanded[:16] + mix_columns(expanded[16:224], inverse=True) + expanded[224:]


def recover_key(schedule):
    if len(schedule) != 240:
        raise ExportError("AES 调度表长度不匹配。")
    # Native decrypt init retains round zero and inverse-mixes all interior
    # rounds, including the second half of the original 256-bit key.
    key = schedule[:16] + mix_columns(schedule[16:32])
    if decrypt_schedule(key) != schedule:
        raise ExportError("AES 调度表校验不通过。")
    return key


def candidate_session(obj, base):
    if len(obj) != OBJECT_SIZE:
        return None
    mode = VTABLES.get(struct.unpack_from("<Q", obj)[0] - base)
    if mode is None or struct.unpack_from("<I", obj, 0x118)[0] != 14:
        return None
    if struct.unpack_from("<Q", obj, 0x120)[0] != base + AES_DECRYPT_RVA:
        return None
    if not all(struct.unpack_from("<QQ", obj, 0x128)):
        return None
    try:
        return FixedAESKey(recover_key(obj[8:0xf8]), mode)
    except ExportError:
        return None


def check_engine(path):
    path = Path(path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != ENGINE_SHA256:
        raise ExportError("未适配的 EVPlayer2 组件：实验适配仅接受官方 5.0.4 x64 特定构建。")
    return {"product": "EVPlayer2", "version": "5.0.4", "architecture": "x64",
            "sha256": digest, "experimental": True,
            "native_aes_verified": True, "real_video_verified": False}


def sessions(pid=None, cancelled=lambda: False, notify=lambda message: None):
    from .windows import api, ProcessEntry, ModuleEntry, MemoryInfo, failure, ENGINE_NAME
    k = api()

    def snapshot(flags, target):
        handle = k.CreateToolhelp32Snapshot(flags, target)
        if handle == C.c_void_p(-1).value:
            raise failure()
        return handle

    handle = snapshot(2, 0)
    entry = ProcessEntry()
    entry.size = C.sizeof(entry)
    matches = []
    try:
        ok = k.Process32FirstW(handle, C.byref(entry))
        while ok:
            if entry.name.lower() == "evplayer2.exe":
                matches.append(entry.pid)
            ok = k.Process32NextW(handle, C.byref(entry))
    finally:
        k.CloseHandle(handle)
    if pid is None:
        if len(matches) != 1:
            raise ExportError("请保留一个 EVPlayer2 实例，并正常播放对应课程；多实例请指定 --pid。")
        pid = matches[0]
    elif pid not in matches:
        raise ExportError("指定进程不是正在运行的 EVPlayer2。")

    handle = snapshot(0x18, pid)
    entry = ModuleEntry()
    entry.size = C.sizeof(entry)
    module = None
    try:
        ok = k.Module32FirstW(handle, C.byref(entry))
        while ok:
            if entry.name.lower() == ENGINE_NAME.lower():
                module = entry.base, Path(entry.path)
                break
            ok = k.Module32NextW(handle, C.byref(entry))
    finally:
        k.CloseHandle(handle)
    if module is None:
        raise ExportError("没有找到 EVPlayer2 播放核心，请先正常播放视频。")
    check_engine(module[1])
    base = module[0]
    needles = [struct.pack("<Q", base + rva) for rva in VTABLES]
    handle = k.OpenProcess(0x410, False, pid)  # query + read; never writes
    if not handle:
        raise failure()

    def read(address, length):
        buffer = C.create_string_buffer(length)
        count = C.c_size_t()
        ok = k.ReadProcessMemory(handle, address, buffer, length, C.byref(count))
        return buffer.raw[:count.value] if ok else b""

    address = 0
    found = []
    deadline = time.monotonic() + 120
    try:
        while address < 0x0000800000000000:
            if cancelled():
                raise Cancelled("检查已取消。")
            if time.monotonic() > deadline:
                raise ExportError("播放器只读检查超时；请重启播放器并只播放对应视频后重试。")
            region = MemoryInfo()
            if not k.VirtualQueryEx(handle, address, C.byref(region), C.sizeof(region)):
                break
            start = region.base or 0
            end = start + region.length
            if (region.state == 0x1000 and region.type == 0x20000
                    and (region.protection & 0xff) in (4, 8, 0x40, 0x80)
                    and not region.protection & 0x100):
                for chunk in range(start, end, 1024 * 1024):
                    if cancelled():
                        raise Cancelled("检查已取消。")
                    if time.monotonic() > deadline:
                        raise ExportError("播放器只读检查超时。")
                    data = read(chunk, min(end - chunk, 1024 * 1024 + OBJECT_SIZE - 1))
                    for needle in needles:
                        offset = data.find(needle)
                        while offset >= 0:
                            location = chunk + offset
                            obj = read(location, OBJECT_SIZE)
                            candidate = candidate_session(obj, base)
                            # Playback may mutate buffers, but key schedule and
                            # function pointer must be stable across both reads.
                            if candidate and read(location, 0x128) == obj[:0x128]:
                                if candidate not in found:
                                    found.append(candidate)
                            offset = data.find(needle, offset + 1)
            if end <= address:
                break
            address = end
    finally:
        k.CloseHandle(handle)
    if not found:
        raise ExportError("未找到 EV5/EV6/EV7 的有效 AES-256 播放参数；EVS、V4A、V8A 和未成功播放的视频不适用。")
    notify(f"找到 {len(found)} 组有效实验播放参数（参数仅保留在内存）。")
    return found


def collect(inputs):
    files = []
    suffixes = {".ev5", ".ev6", ".ev7"}
    for name in inputs:
        path = Path(name).absolute()
        if path.is_symlink():
            raise ExportError("实验适配不处理符号链接。")
        if not path.exists():
            raise ExportError("输入路径不存在。")
        candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
        files.extend(p.resolve() for p in candidates if p.is_file()
                     and not p.is_symlink() and p.suffix.lower() in suffixes)
    files = list(dict.fromkeys(files))
    if not files:
        raise ExportError("没有找到 .ev5、.ev6 或 .ev7 文件；EVS 与其它格式尚未适配。")
    return files


def export_batch(inputs, output, pid=None, ffmpeg=None, notify=print,
                 progress=lambda done, total: None, cancelled=lambda: False):
    from .runner import verify
    from .core import choose_session, convert
    from .windows import low_priority
    files = collect(inputs)
    output = Path(output).resolve()
    if output.exists() and not output.is_dir():
        raise ExportError("输出位置必须是文件夹。")
    if ffmpeg is not None and not Path(ffmpeg).is_file():
        raise ExportError("指定的 FFmpeg 不存在。")
    low_priority()
    notify("实验适配：原生 AES 已验证，真实课程与 Windows 进程读取尚未端到端验证。")
    keys = sessions(pid, cancelled, notify)
    common = Path(os.path.commonpath([str(p.parent) for p in files]))
    results = []
    for index, source in enumerate(files, 1):
        if cancelled():
            break
        destination = output / source.relative_to(common).with_suffix(".mp4")
        notify(f"[{index}/{len(files)}] {source.name}")
        try:
            key = choose_session(source, keys)
            result = convert(source, destination, key, progress, cancelled)
            result["experimental"] = True
            result["mode"] = key.mode
            result["full_decode_verified"] = verify(destination, ffmpeg, cancelled) if ffmpeg else False
            result["success"] = True
            notify("完成（完整解码已验证）" if ffmpeg else "完成（仅 MP4 结构已验证）")
        except Cancelled:
            notify("已取消，原文件和此前结果保留。")
            break
        except (ExportError, OSError) as error:
            result = {"name": source.name, "success": False, "error": str(error)}
            notify("失败：" + str(error))
        results.append(result)
    return results

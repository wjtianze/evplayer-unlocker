"""Read-only access to EVPlayer playback state; never writes session keys."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import os
from pathlib import Path
import struct
from .core import ExportError, SessionKey, Cancelled

ENGINE_NAME = "PlayerLibRender56_vs.dll"

# Data mode handled by this tool (Decryptor_V4A).
MODE_V4A = 110

# Fingerprints of components whose session layout was verified against real
# recordings. These builds get the fast, exact scan below. Unknown builds are
# not refused: they are attempted with a structural scan instead.
#   pointer    - size of a pointer in the player process (4 = x86, 8 = x64)
#   vtable_rva - RVA of the V4A (mode 110) session object vtable in the component
BUILDS = {
    # EVPlayer 3.4.9.1, 32-bit player component.
    "40285804d2aea4e911c282e6f421d5b90baa8c2338158ddcf8fc6d5a25fb58bb": {
        "version": "3.4.9.1", "machine": 0x014C, "pointer": 4,
        "vtable_rva": 0x81B1BC,
    },
    # EVPlayer 3.5.9, 64-bit player component.
    "6a4a481d81ce606b959355265fa27a9db6274bf1978291d04d0c6c19a377a2c3": {
        "version": "3.5.9", "machine": 0x8664, "pointer": 8,
        "vtable_rva": 0x7FB150,
    },
}

# PE machine type -> pointer size, used for builds that are not fingerprinted.
MACHINES = {0x014C: 4, 0x8664: 8, 0xAA64: 8}


def pe_machine(path: Path):
    """Read the COFF machine type from a PE file without loading it."""
    with path.open("rb") as stream:
        header = stream.read(0x40)
        if len(header) < 0x40 or header[:2] != b"MZ":
            return None
        offset = struct.unpack_from("<I", header, 0x3C)[0]
        stream.seek(offset)
        coff = stream.read(6)
        if len(coff) < 6 or coff[:4] != b"PE\0\0":
            return None
        return struct.unpack_from("<H", coff, 4)[0]


def layout(pointer):
    """Field offsets of the session object: vtable, session, mode, two buffers."""
    return {
        "pointer": pointer,
        "size": 5*pointer,
        "session": pointer,
        "mode": 2*pointer,
        "input": 3*pointer,
        "output": 4*pointer,
        "master": 0x10,
        "operations": 0x20 + 2*pointer,
        "string_size": 16 + 2*pointer,
    }


def architecture(pointer):
    return {4: "x86", 8: "x64"}.get(pointer, "unknown")


def check_engine(path: Path):
    """Fingerprint the component. Unknown builds are reported, not rejected."""
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    build = BUILDS.get(digest)
    pointer = build["pointer"] if build else MACHINES.get(pe_machine(path))
    return {
        "engine": ENGINE_NAME,
        "sha256": digest,
        "version": build["version"] if build else None,
        "architecture": architecture(pointer),
        "pointer": pointer,
        "supported": build is not None,
    }


def object_layout(obj, pointer, module_base, module_size):
    """Describe a plausible mode-110 session object, or None if implausible."""
    if pointer not in (4, 8):
        return None
    shape = layout(pointer)
    if len(obj) != shape["size"]:
        return None
    packing = "<I" if pointer == 4 else "<Q"
    vtable = struct.unpack_from(packing, obj, 0)[0]
    if not module_base <= vtable < module_base + module_size:
        return None
    mode = struct.unpack_from("<i", obj, shape["mode"])[0]
    helper = struct.unpack_from(packing, obj, shape["session"])[0]
    input_buffer = struct.unpack_from(packing, obj, shape["input"])[0]
    output_buffer = struct.unpack_from(packing, obj, shape["output"])[0]
    if mode != MODE_V4A or not helper or not input_buffer or not output_buffer:
        return None
    return {"helper": helper, "master": helper + shape["master"],
            "operations": helper + shape["operations"]}


class ProcessEntry(C.Structure):
    _fields_ = [("size", W.DWORD), ("usage", W.DWORD), ("pid", W.DWORD), ("heap", C.c_size_t), ("module", W.DWORD), ("threads", W.DWORD), ("parent", W.DWORD), ("priority", W.LONG), ("flags", W.DWORD), ("name", W.WCHAR * 260)]


class ModuleEntry(C.Structure):
    _fields_ = [("size", W.DWORD), ("module_id", W.DWORD), ("pid", W.DWORD), ("global_usage", W.DWORD), ("usage", W.DWORD), ("base", C.c_void_p), ("length", W.DWORD), ("handle", W.HMODULE), ("name", W.WCHAR * 256), ("path", W.WCHAR * 260)]


class MemoryInfo(C.Structure):
    _fields_ = [("base", C.c_void_p), ("allocation_base", C.c_void_p), ("allocation_protection", W.DWORD), ("partition", W.WORD), ("length", C.c_size_t), ("state", W.DWORD), ("protection", W.DWORD), ("type", W.DWORD)]


def api():
    if os.name != "nt" or C.sizeof(C.c_void_p) != 8:
        raise ExportError("读取播放器需要 64 位 Windows 和 64 位 Python。")
    k = C.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateToolhelp32Snapshot": ([W.DWORD, W.DWORD], W.HANDLE),
        "Process32FirstW": ([W.HANDLE, C.POINTER(ProcessEntry)], W.BOOL),
        "Process32NextW": ([W.HANDLE, C.POINTER(ProcessEntry)], W.BOOL),
        "Module32FirstW": ([W.HANDLE, C.POINTER(ModuleEntry)], W.BOOL),
        "Module32NextW": ([W.HANDLE, C.POINTER(ModuleEntry)], W.BOOL),
        "CloseHandle": ([W.HANDLE], W.BOOL),
        "OpenProcess": ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        "ReadProcessMemory": ([W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)], W.BOOL),
        "VirtualQueryEx": ([W.HANDLE, C.c_void_p, C.POINTER(MemoryInfo), C.c_size_t], C.c_size_t),
        "SetPriorityClass": ([W.HANDLE, W.DWORD], W.BOOL),
    }
    for name, (args, result) in signatures.items():
        getattr(k, name).argtypes = args
        getattr(k, name).restype = result
    return k


def low_priority():
    if os.name == "nt":
        api().SetPriorityClass(C.c_void_p(-1), 0x40)


def failure():
    code = C.get_last_error()
    if code == 5:
        return ExportError("Windows 拒绝读取播放器。请关闭本工具后，右键选择“以管理员身份运行”。")
    return ExportError(f"Windows 只读检查失败，错误码 {code}。")


def sessions(pid=None, cancelled=lambda: False):
    k = api()

    def snapshot(flags, target):
        h = k.CreateToolhelp32Snapshot(flags, target)
        if h == C.c_void_p(-1).value:
            raise failure()
        return h

    h = snapshot(2, 0)
    entry = ProcessEntry(); entry.size = C.sizeof(entry)
    matches = []
    try:
        ok = k.Process32FirstW(h, C.byref(entry))
        while ok:
            if entry.name.lower() == "evplayer.exe":
                matches.append(entry.pid)
            ok = k.Process32NextW(h, C.byref(entry))
    finally:
        k.CloseHandle(h)
    if pid is not None:
        if pid not in matches:
            raise ExportError("指定进程不是正在运行的 EVPlayer。")
    elif len(matches) != 1:
        raise ExportError("请保留一个 EVPlayer 实例，并先正常播放待导出的课程。")
    else:
        pid = matches[0]
    h = snapshot(0x18, pid)
    entry = ModuleEntry(); entry.size = C.sizeof(entry)
    module = None
    try:
        ok = k.Module32FirstW(h, C.byref(entry))
        while ok:
            if entry.name.lower() == ENGINE_NAME.lower():
                module = (entry.base, entry.length, Path(entry.path))
                break
            ok = k.Module32NextW(h, C.byref(entry))
    finally:
        k.CloseHandle(h)
    if module is None:
        raise ExportError("未找到播放器解码组件，请先打开并正常播放视频。")
    report = check_engine(module[2])
    pointer = report["pointer"]
    if pointer is None:
        raise ExportError("无法识别播放器组件是 32 位还是 64 位；请确认使用的是 EVPlayer 自带的组件。")
    shape = layout(pointer)
    packing = "<I" if pointer == 4 else "<Q"
    limit = 0x100000000 if pointer == 4 else 0x7FFFFFFFFFFF
    h = k.OpenProcess(0x410, False, pid)
    if not h:
        raise failure()

    def read(address, size):
        buffer = C.create_string_buffer(size); count = C.c_size_t()
        if not k.ReadProcessMemory(h, address, buffer, size, C.byref(count)):
            return b""
        return buffer.raw[:count.value]

    def string_at(address):
        header = read(address, shape["string_size"])
        if len(header) != shape["string_size"]:
            return b""
        size, capacity = struct.unpack_from("<II", header, 16) if pointer == 4 else struct.unpack_from("<QQ", header, 16)
        if size > 32 or capacity < size:
            return b""
        value = read(struct.unpack_from(packing, header)[0], size) if capacity >= 16 else header[:size]
        return value if read(address, shape["string_size"]) == header else b""

    if report["supported"]:
        # Verified build: the vtable RVA is the exact anchor used during validation.
        needle = struct.pack(packing, module[0] + BUILDS[report["sha256"]]["vtable_rva"])
        skip = 0
    else:
        # Unknown build: look for the mode field itself and validate the object
        # shape around it (vtable inside the component, two live buffers).
        needle = struct.pack("<i", MODE_V4A)
        skip = shape["mode"]
    address = 0
    found = []
    try:
        while address < limit:
            if cancelled():
                raise Cancelled("检查已取消。")
            region = MemoryInfo()
            if not k.VirtualQueryEx(h, address, C.byref(region), C.sizeof(region)):
                break
            start = region.base or 0
            end = start + region.length
            if region.state == 0x1000 and region.type == 0x20000 and (region.protection & 0xFF) in (4, 8, 0x40, 0x80) and not region.protection & 0x100:
                for chunk in range(start, end, 1024*1024):
                    if cancelled():
                        raise Cancelled("检查已取消。")
                    data = read(chunk, min(end - chunk, 1024*1024))
                    position = data.find(needle)
                    while position >= 0:
                        base = chunk + position - skip
                        if base >= start and base % pointer == 0:
                            fields = object_layout(read(base, shape["size"]), pointer, module[0], module[1])
                            if fields:
                                try:
                                    candidate = SessionKey(string_at(fields["master"]), string_at(fields["operations"]))
                                except ExportError:
                                    pass
                                else:
                                    if candidate not in found:
                                        found.append(candidate)
                        position = data.find(needle, position + pointer)
            if end <= address:
                break
            address = end
    finally:
        k.CloseHandle(h)
    if not found:
        raise ExportError("未找到有效的 V4A 播放参数；请先在 EVPlayer 中正常播放同一课程视频，然后重试。")
    return found

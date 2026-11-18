"""Read-only access to verified EVPlayer builds; never writes session keys."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import os
from pathlib import Path
import struct
from .core import ExportError, SessionKey, Cancelled

ENGINE_NAME = "PlayerLibRender56_vs.dll"

# Exact fingerprints of components that were verified against real recordings.
# A matching version number alone is not enough: support is scoped per SHA-256.
#   pointer      - size of a pointer in the player process (4 = x86, 8 = x64)
#   vtable_rva   - RVA of the V4A (mode 110) session object vtable in the component
#   strings      - offset of the master std::string and the operations std::string
#                  inside the object the session pointer refers to
BUILDS = {
    # EVPlayer 3.4.9.1, 32-bit player component.
    "40285804d2aea4e911c282e6f421d5b90baa8c2338158ddcf8fc6d5a25fb58bb": {
        "version": "3.4.9.1", "machine": 0x014C, "pointer": 4,
        "vtable_rva": 0x81B1BC, "strings": (0x10, 0x28),
    },
    # EVPlayer 3.5.9, 64-bit player component.
    "6a4a481d81ce606b959355265fa27a9db6274bf1978291d04d0c6c19a377a2c3": {
        "version": "3.5.9", "machine": 0x8664, "pointer": 8,
        "vtable_rva": 0x7FB150, "strings": (0x10, 0x30),
    },
}

SUPPORTED_VERSIONS = "、".join(sorted({build["version"] for build in BUILDS.values()}))


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


def check_engine(path: Path):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    build = BUILDS.get(digest)
    if build is None:
        raise ExportError(f"播放器组件尚未适配：仅支持已验证的 EVPlayer {SUPPORTED_VERSIONS} 构建。")
    machine = pe_machine(path)
    if machine is not None and machine != build["machine"]:
        raise ExportError("播放器组件指纹与已验证构建不符，已停止。")
    return {"version": build["version"], "engine": ENGINE_NAME, "sha256": digest,
            "architecture": "x64" if build["pointer"] == 8 else "x86", "supported": True}


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
                module = (entry.base, Path(entry.path))
                break
            ok = k.Module32NextW(h, C.byref(entry))
    finally:
        k.CloseHandle(h)
    if module is None:
        raise ExportError("未找到播放器解码组件，请先打开并正常播放视频。")
    report = check_engine(module[1])
    build = BUILDS[report["sha256"]]
    pointer = build["pointer"]
    packing, limit = ("<I", 0x100000000) if pointer == 4 else ("<Q", 0x7FFFFFFFFFFF)
    # Object layout: vtable, session pointer, mode(int), input buffer, output buffer.
    session_offset = pointer
    mode_offset = 2*pointer
    input_offset = 3*pointer
    output_offset = 4*pointer
    layout_size = output_offset + pointer
    master_offset, operations_offset = build["strings"]
    string_size = 16 + 2*pointer
    h = k.OpenProcess(0x410, False, pid)
    if not h:
        raise failure()

    def read(address, size):
        buffer = C.create_string_buffer(size); count = C.c_size_t()
        if not k.ReadProcessMemory(h, address, buffer, size, C.byref(count)):
            return b""
        return buffer.raw[:count.value]

    def string_at(address):
        header = read(address, string_size)
        if len(header) != string_size:
            return b""
        size, capacity = struct.unpack_from("<II", header, 16) if pointer == 4 else struct.unpack_from("<QQ", header, 16)
        if size > 32 or capacity < size:
            return b""
        value = read(struct.unpack_from(packing, header)[0], size) if capacity >= 16 else header[:size]
        return value if read(address, string_size) == header else b""

    needle = struct.pack(packing, module[0] + build["vtable_rva"])
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
                    data = read(chunk, min(end-chunk, 1024*1024 + layout_size))
                    offset = data.find(needle)
                    while offset >= 0:
                        obj = read(chunk + offset, layout_size)
                        if len(obj) == layout_size:
                            helper = struct.unpack_from(packing, obj, session_offset)[0]
                            mode = struct.unpack_from("<i", obj, mode_offset)[0]
                            input_buffer = struct.unpack_from(packing, obj, input_offset)[0]
                            output_buffer = struct.unpack_from(packing, obj, output_offset)[0]
                            if helper and mode == 110 and input_buffer and output_buffer:
                                try:
                                    candidate = SessionKey(string_at(helper + master_offset), string_at(helper + operations_offset))
                                    if candidate not in found:
                                        found.append(candidate)
                                except ExportError:
                                    pass
                        offset = data.find(needle, offset + pointer)
            if end <= address:
                break
            address = end
    finally:
        k.CloseHandle(h)
    if not found:
        raise ExportError("未找到有效的 V4A 播放参数；请先在 EVPlayer 中正常播放同一课程视频，然后重试。")
    return found

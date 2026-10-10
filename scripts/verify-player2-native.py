"""Execute the original Player2 DLL's AES routines without loading Windows.

Requires research-only dependencies: pefile==2024.8.26, unicorn==2.1.4.
Usage: python scripts/verify-player2-native.py PATH/PlayerLibRender56_vs.dll
No private keys or course files are used or written. DLL is mapped as data into
an emulator, not loaded into the host process. No network or Windows APIs run.
"""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evplayer_unlocker.player2 import ENGINE_SHA256, decrypt_schedule, recover_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    args = parser.parse_args()
    import pefile
    from Crypto.Cipher import AES
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE
    from unicorn.x86_const import (UC_X86_REG_RSP, UC_X86_REG_RIP, UC_X86_REG_RAX,
                                  UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8,
                                  UC_X86_REG_R9)

    data = args.engine.read_bytes()
    if hashlib.sha256(data).hexdigest() != ENGINE_SHA256:
        raise RuntimeError("Engine fingerprint mismatch")
    pe = pefile.PE(data=data)
    base = pe.OPTIONAL_HEADER.ImageBase
    u = Uc(UC_ARCH_X86, UC_MODE_64)
    u.mem_map(base, 0x1400000)
    u.mem_write(base, pe.get_memory_mapped_image())
    stack, heap, sentinel = 0x70000000, 0x71000000, 0x72000000
    u.mem_map(stack, 0x100000)
    u.mem_map(heap, 0x100000)
    u.mem_map(sentinel, 0x1000)

    def return_from_hook(result=0):
        sp = u.reg_read(UC_X86_REG_RSP)
        address = struct.unpack("<Q", u.mem_read(sp, 8))[0]
        u.reg_write(UC_X86_REG_RSP, sp + 8)
        u.reg_write(UC_X86_REG_RAX, result)
        u.reg_write(UC_X86_REG_RIP, address)

    stream_data = b""
    stream_cursor = 0
    stream_stub = sentinel + 0x100

    def hook(_u, address, _size, _user_data):
        nonlocal stream_cursor
        if address == base + 0x7f64b4:
            destination = u.reg_read(UC_X86_REG_RCX)
            source = u.reg_read(UC_X86_REG_RDX)
            length = u.reg_read(UC_X86_REG_R8)
            u.mem_write(destination, bytes(u.mem_read(source, length)))
            return_from_hook(destination)
        elif address == base + 0x7f5110:
            # Stack-cookie helper is not part of the crypto algorithm.
            return_from_hook()
        elif address == stream_stub:
            destination = u.reg_read(UC_X86_REG_RDX)
            requested = u.reg_read(UC_X86_REG_R8) & 0xffffffff
            value = stream_data[stream_cursor:stream_cursor + requested]
            if value:
                u.mem_write(destination, value)
            stream_cursor += len(value)
            return_from_hook(len(value))

    u.hook_add(UC_HOOK_CODE, hook)

    def call(rva, regs, extra=()):
        sp = stack + 0x80008
        u.mem_write(sp, struct.pack("<Q", sentinel))
        for index, value in enumerate(extra):
            u.mem_write(sp + 0x28 + index * 8, struct.pack("<Q", value))
        u.reg_write(UC_X86_REG_RSP, sp)
        for reg, value in regs.items():
            u.reg_write(reg, value)
        u.emu_start(base + rva, sentinel, timeout=30000000, count=30000000)
        if u.reg_read(UC_X86_REG_RIP) != sentinel:
            raise RuntimeError("Native emulation did not return")
        return u.reg_read(UC_X86_REG_RAX)

    vectors = []
    for length in (16, 24, 32):
        for seed in range(5):
            key = hashlib.sha256(f"public test {length} {seed}".encode()).digest()[:length]
            plain = hashlib.sha512(f"public plaintext {seed}".encode()).digest()
            encrypted = AES.new(key, AES.MODE_ECB).encrypt(plain)
            ctx, key_address = heap, heap + 0x1000
            input_address, output_address = heap + 0x2000, heap + 0x3000
            u.mem_write(key_address, key)
            status = call(0x20c90, {UC_X86_REG_RCX: ctx, UC_X86_REG_RDX: key_address,
                                   UC_X86_REG_R8: length * 8, UC_X86_REG_R9: 1})
            if status != 0:
                raise RuntimeError("Native AES init failed")
            exact_schedule = None
            if length == 32:
                schedule = bytes(u.mem_read(ctx, 240))
                exact_schedule = decrypt_schedule(key) == schedule and recover_key(schedule) == key
                if not exact_schedule:
                    raise RuntimeError("Native AES-256 schedule mismatch")
            u.mem_write(input_address, encrypted)
            call(0x20c70, {UC_X86_REG_RCX: ctx, UC_X86_REG_RDX: output_address,
                           UC_X86_REG_R8: input_address, UC_X86_REG_R9: len(encrypted) // 16},
                 extra=(0, 1))
            if bytes(u.mem_read(output_address, len(plain))) != plain:
                raise RuntimeError("Native AES decrypt mismatch")
            vectors.append({"key_bits": length * 8, "vector": seed,
                            "native_decrypt_matches": True,
                            "full_schedule_matches": exact_schedule})

    # Execute the EV5/6/7 reader itself, including its buffering and copy path.
    # The mocked stream has position zero: this does not establish that every
    # real course container exposes ciphertext starting at file offset zero.
    obj, key_address = heap, heap + 0x1000
    reader, vtable = heap + 0x2000, heap + 0x3000
    input_buffer, output_buffer, destination = heap + 0x4000, heap + 0x44000, heap + 0x84000
    key = bytes(range(32))
    plain = bytes(range(256)) * 129
    stream_data = AES.new(key, AES.MODE_ECB).encrypt(plain)
    u.mem_write(obj, bytes(0x368))
    u.mem_write(key_address, key)
    call(0x20c90, {UC_X86_REG_RCX: obj + 8, UC_X86_REG_RDX: key_address,
                   UC_X86_REG_R8: 256, UC_X86_REG_R9: 1})
    u.mem_write(obj + 0x128, struct.pack("<QQ", input_buffer, output_buffer))
    u.mem_write(reader, struct.pack("<Q", vtable))
    u.mem_write(vtable, struct.pack("<Q", stream_stub))
    returned = bytearray()
    counts = []
    while stream_cursor < len(stream_data):
        count = call(0x1acf0, {UC_X86_REG_RCX: obj, UC_X86_REG_RDX: destination,
                              UC_X86_REG_R8: 4096, UC_X86_REG_R9: reader})
        if not 0 < count <= 0x40000:
            raise RuntimeError("Native reader failed")
        returned.extend(u.mem_read(destination, count))
        counts.append(count)
    if returned != plain:
        raise RuntimeError("Native reader byte mismatch")
    print(json.dumps({"engine_sha256": ENGINE_SHA256, "vectors": vectors,
                      "native_reader": {"bytes": len(plain), "chunks": counts,
                                        "byte_identical": True},
                      "scope": "Native AES and reader with public synthetic inputs; no real course or Windows session scan"}, indent=2))


if __name__ == "__main__":
    main()

from pathlib import Path
import struct
import tempfile
import unittest
from Crypto.Cipher import AES
from evplayer_unlocker.core import ExportError, FixedAESKey, choose_session, convert
from evplayer_unlocker.player2 import (recover_key, decrypt_schedule, candidate_session,
                                      mix_columns, collect, check_engine, OBJECT_SIZE)

PUBLIC_KEY = bytes(range(32))
BASE = 0x7ffa00000000


def object_fixture():
    obj = bytearray(OBJECT_SIZE)
    struct.pack_into("<Q", obj, 0, BASE + 0x801108)
    obj[8:0xf8] = decrypt_schedule(PUBLIC_KEY)
    struct.pack_into("<I", obj, 0x118, 14)
    struct.pack_into("<QQQ", obj, 0x120, BASE + 0x20110, 0x100001000, 0x100041000)
    return obj


class Player2Tests(unittest.TestCase):
    def test_fips_aes256_expansion_known_round_one(self):
        # FIPS 197 AES-256 example, second round-zero half is the raw key.
        key = bytes.fromhex("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4")
        schedule = decrypt_schedule(key)
        self.assertEqual(mix_columns(schedule[32:48]).hex(), "9ba354118e6925afa51a8b5f2067fcde")
        self.assertEqual(recover_key(schedule), key)

    def test_mix_inverse(self):
        data = bytes(range(32))
        self.assertEqual(mix_columns(mix_columns(data, inverse=True)), data)

    def test_untouched_second_half_is_not_raw_key(self):
        schedule = decrypt_schedule(PUBLIC_KEY)
        self.assertNotEqual(schedule[:32], PUBLIC_KEY)
        self.assertEqual(recover_key(schedule), PUBLIC_KEY)

    def test_corrupt_schedule_rejected(self):
        data = bytearray(decrypt_schedule(PUBLIC_KEY))
        data[200] ^= 1
        with self.assertRaises(ExportError):
            recover_key(data)

    def test_x64_aslr_object_is_recognized(self):
        candidate = candidate_session(object_fixture(), BASE)
        self.assertEqual(candidate.key, PUBLIC_KEY)
        self.assertEqual(candidate.mode, "EV5")

    def test_ev6_ev7_objects(self):
        for rva, mode in [(0x801190, "EV6"), (0x801200, "EV7")]:
            obj = object_fixture()
            struct.pack_into("<Q", obj, 0, BASE + rva)
            self.assertEqual(candidate_session(obj, BASE).mode, mode)

    def test_false_objects_rejected(self):
        for offset, value in [(0, 0), (0x118, 10), (0x120, 0), (0x128, 0), (0x130, 0), (40, 0)]:
            obj = object_fixture()
            struct.pack_into("<I" if offset == 0x118 else "<Q", obj, offset, value)
            self.assertIsNone(candidate_session(obj, BASE), offset)
        self.assertIsNone(candidate_session(b"short", BASE))

    def test_unknown_build_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "PlayerLibRender56_vs.dll"
            path.write_bytes(b"unknown build")
            with self.assertRaises(ExportError):
                check_engine(path)

    def test_constant_key_multiblock_export_and_source_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def box(name, payload):
                return struct.pack(">I", 8 + len(payload)) + name + payload
            # Deliberately synthetic container; this test does not assert
            # that the payload is a playable movie.
            plain = (box(b"ftyp", b"isom\0\0\0\0isommp42")
                     + box(b"mdat", b"test" * 180000) + box(b"moov", b"metadata"))
            pad = bytes((-len(plain)) % 16)
            ciphertext = AES.new(PUBLIC_KEY, AES.MODE_ECB).encrypt(plain + pad)
            source = root / "示例.ev5"
            output = root / "示例.mp4"
            source.write_bytes(ciphertext)
            session = choose_session(source, [FixedAESKey(bytes(32)), FixedAESKey(PUBLIC_KEY)])
            result = convert(source, output, session)
            self.assertEqual(output.read_bytes(), plain)
            self.assertEqual(source.read_bytes(), ciphertext)
            self.assertTrue(result["container_verified"])

    def test_fixed_key_repr_does_not_expose_material(self):
        self.assertNotIn("key=", repr(FixedAESKey(PUBLIC_KEY)))
        with self.assertRaises(ExportError):
            FixedAESKey(bytes(16))

    def test_collect_case_insensitive_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "TEST.EV5"
            path.write_bytes(b"test")
            (Path(directory) / "unsupported.evs").write_bytes(b"test")
            self.assertEqual(collect([directory, str(path)]), [path.resolve()])


if __name__ == "__main__":
    unittest.main()

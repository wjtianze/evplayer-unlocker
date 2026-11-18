from pathlib import Path
import struct
import tempfile
import unittest
from evplayer_unlocker.core import ExportError
from evplayer_unlocker.windows import BUILDS, check_engine, pe_machine
from evplayer_unlocker.inspect import inspect_video
from evplayer_unlocker.runner import collect, decode_errors


def write_pe(path, machine):
    data = bytearray(0x120)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, 0x84, machine)
    path.write_bytes(bytes(data))
    return path


class InspectionTests(unittest.TestCase):
    def test_unknown_build_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"PlayerLibRender56_vs.dll"
            path.write_bytes(b"not the supported player")
            with self.assertRaises(ExportError) as context:
                check_engine(path)
            self.assertIn("3.4.9.1", str(context.exception))
            self.assertIn("3.5.9", str(context.exception))
    def test_supported_build_fingerprints(self):
        versions = {build["version"] for build in BUILDS.values()}
        self.assertEqual(versions, {"3.4.9.1", "3.5.9"})
        # The 3.5.9 component is 64-bit; the 3.4.9.1 component is 32-bit.
        self.assertEqual({build["pointer"] for build in BUILDS.values()}, {4, 8})
        self.assertEqual({build["machine"] for build in BUILDS.values()}, {0x014C, 0x8664})
    def test_pe_machine_reads_coff_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_pe(Path(directory)/"x64.dll", 0x8664)
            self.assertEqual(pe_machine(path), 0x8664)
            path = write_pe(Path(directory)/"x86.dll", 0x014C)
            self.assertEqual(pe_machine(path), 0x014C)
    def test_pe_machine_rejects_non_pe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"garbage.dll"
            path.write_bytes(b"garbage"*16)
            self.assertIsNone(pe_machine(path))
    def test_extension_does_not_claim_decryption_support(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"test.ev4a"; path.write_bytes(b"anything")
            result = inspect_video(path)
            self.assertTrue(result["ev4a_extension"])
            self.assertFalse(result["ordinary_mp4_header"])
    def test_collect_deduplicates_and_ignores_other_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"test.ev4a"; path.write_bytes(b"anything")
            (Path(directory)/"notes.txt").write_text("test")
            # Windows CI may expose TEMP through an 8.3 short-path alias.
            self.assertEqual(collect([directory, str(path)]), [path.resolve()])
    def test_missing_input_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ExportError): collect([str(Path(directory)/"missing")])
    def test_harmless_muxer_timestamp_warning_is_not_a_decode_error(self):
        text = ("[null @ 0x1] Application provided invalid, non monotonically increasing dts "
                "to muxer in stream 0: 83135 >= 83135\n")
        self.assertEqual(decode_errors(text), [])
    def test_real_decode_error_is_reported(self):
        text = "[h264 @ 0x1] error while decoding MB 12 34\n"
        self.assertEqual(len(decode_errors(text)), 1)


if __name__ == "__main__": unittest.main()

from pathlib import Path
import struct
import tempfile
import unittest
from evplayer_unlocker.core import ExportError
from evplayer_unlocker.windows import BUILDS, MODE_V4A, check_engine, layout, object_layout, pe_machine
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


def make_object(pointer, vtable, mode=110, helper=0x1000, input_buffer=0x2000, output_buffer=0x3000):
    data = bytearray(5*pointer)
    pointer_format = "<I" if pointer == 4 else "<Q"
    struct.pack_into(pointer_format, data, 0, vtable)
    struct.pack_into(pointer_format, data, pointer, helper)
    struct.pack_into("<i", data, 2*pointer, mode)
    struct.pack_into(pointer_format, data, 3*pointer, input_buffer)
    struct.pack_into(pointer_format, data, 4*pointer, output_buffer)
    return bytes(data)


class InspectionTests(unittest.TestCase):
    def test_unknown_build_is_tolerated(self):
        # The tool must not refuse to run just because the component differs.
        with tempfile.TemporaryDirectory() as directory:
            path = write_pe(Path(directory)/"PlayerLibRender56_vs.dll", 0x8664)
            report = check_engine(path)
            self.assertFalse(report["supported"])
            self.assertIsNone(report["version"])
            self.assertEqual(report["architecture"], "x64")
            self.assertEqual(report["pointer"], 8)
    def test_unknown_build_without_pe_is_tolerated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"PlayerLibRender56_vs.dll"
            path.write_bytes(b"not a portable executable")
            report = check_engine(path)
            self.assertFalse(report["supported"])
            self.assertIsNone(report["pointer"])
            self.assertEqual(report["architecture"], "unknown")
    def test_supported_build_fingerprints(self):
        versions = {build["version"] for build in BUILDS.values()}
        self.assertEqual(versions, {"3.4.9.1", "3.5.9"})
        # The 3.5.9 component is 64-bit; the 3.4.9.1 component is 32-bit.
        self.assertEqual({build["pointer"] for build in BUILDS.values()}, {4, 8})
        self.assertEqual({build["machine"] for build in BUILDS.values()}, {0x014C, 0x8664})
    def test_layout_follows_pointer_width(self):
        self.assertEqual(layout(4)["size"], 20)
        self.assertEqual((layout(4)["mode"], layout(4)["master"], layout(4)["operations"]), (8, 0x10, 0x28))
        self.assertEqual(layout(8)["size"], 40)
        self.assertEqual((layout(8)["mode"], layout(8)["master"], layout(8)["operations"]), (16, 0x10, 0x30))
    def test_object_layout_accepts_mode_110_objects(self):
        for pointer, base, vtable in ((8, 0x180000000, 0x180100000), (4, 0x10000000, 0x10800000)):
            fields = object_layout(make_object(pointer, vtable), pointer, base, 0x2000000)
            self.assertIsNotNone(fields)
            self.assertEqual(fields["master"], 0x1000 + 0x10)
            self.assertEqual(fields["operations"], 0x1000 + layout(pointer)["operations"])
    def test_object_layout_rejects_other_modes_and_foreign_vtables(self):
        for pointer, base in ((8, 0x180000000), (4, 0x10000000)):
            self.assertIsNone(object_layout(make_object(pointer, base + 0x1000, mode=111), pointer, base, 0x2000000))
            self.assertIsNone(object_layout(make_object(pointer, base - 0x1000), pointer, base, 0x2000000))
            self.assertIsNone(object_layout(make_object(pointer, base + 0x1000, helper=0), pointer, base, 0x2000000))
            self.assertIsNone(object_layout(make_object(pointer, base + 0x1000, output_buffer=0), pointer, base, 0x2000000))
        self.assertEqual(MODE_V4A, 110)
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

from pathlib import Path
import tempfile
import unittest
from evplayer_unlocker.core import ExportError
from evplayer_unlocker.windows import check_engine
from evplayer_unlocker.inspect import inspect_video
from evplayer_unlocker.runner import collect

class InspectionTests(unittest.TestCase):
    def test_unknown_build_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"PlayerLibRender56_vs.dll"
            path.write_bytes(b"not the supported player")
            with self.assertRaises(ExportError): check_engine(path)
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
            self.assertEqual(collect([directory, str(path)]), [path])
    def test_missing_input_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ExportError): collect([str(Path(directory)/"missing")])

if __name__ == "__main__": unittest.main()

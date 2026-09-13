from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from evplayer_unlocker.core import SessionKey, ExportError, Cancelled, choose_session, convert, block_key
from evplayer_unlocker.selftest import fixture, run, PUBLIC_MASTER

class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.source, self.plain = fixture(self.folder)
        self.session = SessionKey(PUBLIC_MASTER, b"+-*/")
        self.output = self.folder/"out.mp4"
    def tearDown(self):
        self.temp.cleanup()
    def test_known_multiblock_fixture(self):
        run()
    def test_source_preserved_and_unicode_path(self):
        before = self.source.read_bytes()
        result = convert(self.source, self.folder/"中文 文件夹"/"课程.mp4", self.session)
        self.assertEqual(before, self.source.read_bytes())
        self.assertEqual((self.folder/"中文 文件夹"/"课程.mp4").read_bytes(), self.plain)
        self.assertTrue(result["container_verified"])
    def test_wrong_session_rejected(self):
        with self.assertRaises(ExportError):
            choose_session(self.source, [SessionKey(b"a"*32, b"+-*/")])
    def test_existing_output_preserved(self):
        self.output.write_bytes(b"keep me")
        with self.assertRaises(ExportError): convert(self.source, self.output, self.session)
        self.assertEqual(self.output.read_bytes(), b"keep me")
    def test_cancellation_removes_temporary_output(self):
        with self.assertRaises(Cancelled):
            convert(self.source, self.output, self.session, cancelled=lambda: True)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.folder.glob("*.partial")))
    def test_invalid_container_not_published(self):
        self.source.write_bytes(b"x"*1024)
        with self.assertRaises(ExportError): convert(self.source, self.output, self.session)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.folder.glob("*.partial")))
    def test_source_changes_abort_output(self):
        def change(done, total):
            if done < total:
                self.source.touch()
                self.source.write_bytes(b"modified")
        with self.assertRaises(ExportError): convert(self.source, self.output, self.session, progress=change)
        self.assertFalse(self.output.exists())
    def test_secrets_not_in_repr(self):
        self.assertNotIn(PUBLIC_MASTER.decode(), repr(self.session))
        self.assertNotIn("+-*/", repr(self.session))
    def test_unsupported_operations(self):
        with self.assertRaises(ExportError): SessionKey(PUBLIC_MASTER, b"?+")
    def test_division_is_integer_toward_zero(self):
        import hashlib
        session = SessionKey(b"\xff"*32, b"/")
        self.assertEqual(block_key(session, 3), hashlib.md5(b"\xff"*32+b"--6").hexdigest().encode())

if __name__ == "__main__": unittest.main()

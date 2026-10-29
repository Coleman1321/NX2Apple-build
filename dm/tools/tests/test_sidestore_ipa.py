"""Exercise a ZIP64 IPA whose plist follows the ZIP32 entry-count boundary."""
import hashlib
import importlib.util
from pathlib import Path
import plistlib
import stat
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('sidestore_ipa', ROOT / 'scripts/prepare_sidestore_ipa.py')
packer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packer)


class SideStoreIPA(unittest.TestCase):
    def test_zip64_split_preserves_data_and_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / 'Game.ipa'
            game = '0100152000022000'
            root = 'Payload/DmIOS.app/'
            with zipfile.ZipFile(source, 'w') as archive:
                for i in range(66000):
                    archive.writestr(root + f'msl/b-test/{i}.metallib', str(i).encode())
                archive.writestr(root + 'Info.plist', plistlib.dumps({
                    'CFBundleIdentifier': 'org.nxnative.' + game, 'CFBundleExecutable': 'DmIOS'}))
                executable = zipfile.ZipInfo(root + 'DmIOS')
                executable.external_attr = (stat.S_IFREG | 0o755) << 16
                archive.writestr(executable, b'executable')
            digest = hashlib.sha256(source.read_bytes()).digest()
            ipa, shaders = packer.prepare(source, base / 'out', game)
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), digest)
            with zipfile.ZipFile(ipa) as archive:
                self.assertEqual(len(archive.infolist()), 2)
                self.assertEqual(archive.read(root + 'DmIOS'), b'executable')
                self.assertEqual(archive.getinfo(root + 'DmIOS').external_attr >> 16 & 0o777, 0o755)
                self.assertEqual(plistlib.loads(archive.read(root + 'Info.plist'))['CFBundleExecutable'], 'DmIOS')
                self.assertEqual(archive.testzip(), None)
            with zipfile.ZipFile(shaders) as archive:
                self.assertEqual(len(archive.infolist()), 66000)
                for i in range(66000):
                    self.assertEqual(archive.read(f'msl/b-test/{i}.metallib'), str(i).encode())
            with self.assertRaises(ValueError):
                packer.prepare(source, base / 'out', game)
            with self.assertRaises(ValueError):
                packer.prepare(source, base / 'wrong', '0000000000000000')


if __name__ == '__main__':
    unittest.main()

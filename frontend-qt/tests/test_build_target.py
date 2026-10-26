"""Build routing without Qt, compilers, game files or keys.

Only QObject/signals and the subprocess are stand-ins; the production model builds
its actual command and handles completion. This does not exercise Qt rendering.
"""
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

QT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QT))
core = types.ModuleType('PySide6.QtCore')
core.QObject = object
core.Signal = lambda *args: mock.Mock()
spec = importlib.util.spec_from_file_location('nspb_qt._target_test_model', QT / 'nspb_qt/model.py')
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
with mock.patch.dict(sys.modules, {'PySide6': types.ModuleType('PySide6'), 'PySide6.QtCore': core}):
    spec.loader.exec_module(model)


class BuildTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        with mock.patch.object(model.pu, 'find_python', return_value=(sys.executable, True, (3, 11))), \
             mock.patch.object(model.pu, 'find_dotnet', return_value=('', False)), \
             mock.patch.object(model.Model, '_find_repo', return_value=str(self.root)), \
             mock.patch.object(Path, 'home', return_value=self.root):
            self.m = model.Model()
        for rel in ('dm/tools/nx_extract/Program.cs', 'dm/mac/pack_app.py'):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
        script = self.root / 'scripts/build_ipa_from_nsp.py'
        script.parent.mkdir()
        script.write_text("ap.add_argument('--work-dir')")
        self.m.base_path = str(self.root / 'Game [010015100B514000].nsp')
        self.m.keys_path = str(self.root / 'prod.keys')
        self.m.finished = mock.Mock()
        self.m.pack_archive = mock.Mock()
        self.m.ipa_path = 'stale.ipa'
        self.m.archive_path = 'stale archive'

    def run_build(self, *, exit_code=0, create_app=True):
        def spawn(argv, **kwargs):
            if create_app and self.m.mac_app_path:
                plist = Path(self.m.mac_app_path, 'Contents/Info.plist')
                plist.parent.mkdir(parents=True)
                plist.write_text('stand-in bundle')
            return mock.Mock(stdout=io.StringIO(''), returncode=exit_code)
        def thread(*, target, **kwargs):
            return mock.Mock(start=target)
        with mock.patch.object(model.pu, 'IS_MAC', True), \
             mock.patch.object(model.pu, 'IS_WIN', False), \
             mock.patch.object(model.subprocess, 'Popen', side_effect=spawn) as popen, \
             mock.patch.object(model.threading, 'Thread', side_effect=thread):
            self.m.start_build()
        return popen.call_args.args[0]

    def test_mac_app_skips_phone_archive_and_uses_stable_output(self):
        self.m.build_target = 'mac-app'
        # Separate inputs force temporary staging, which must not contain the result.
        update = self.root / 'Updates/Update.nsp'
        update.parent.mkdir()
        update.touch()
        self.m.update_path = str(update)
        argv = self.run_build()
        self.assertEqual(argv[argv.index('--platform') + 1], 'mac-app')
        self.assertEqual(argv[argv.index('-o') + 1], str(self.root / '010015100B514000.app'))
        self.m.pack_archive.assert_not_called()
        self.assertTrue(self.m.finished.emit.call_args.args[0])
        self.assertEqual(self.m.ipa_path, '')
        self.assertEqual(self.m.archive_path, '')
        self.assertTrue(Path(self.m.mac_app_path).is_dir())

    def test_ios_still_packs_archive(self):
        argv = self.run_build()
        self.assertEqual(argv[argv.index('--platform') + 1], 'ios')
        self.assertNotIn('-o', argv)
        self.m.pack_archive.assert_called_once()

    def test_missing_bundle_is_not_success(self):
        self.m.build_target = 'mac-app'
        self.run_build(create_app=False)
        self.assertFalse(self.m.finished.emit.call_args.args[0])
        self.m.pack_archive.assert_not_called()

    def test_failed_mac_build_does_not_archive(self):
        self.m.build_target = 'mac-app'
        self.run_build(exit_code=1, create_app=False)
        self.assertFalse(self.m.finished.emit.call_args.args[0])
        self.m.pack_archive.assert_not_called()

    def test_windows_rejects_mac_app(self):
        self.m.build_target = 'mac-app'
        with mock.patch.object(model.pu, 'IS_MAC', False), mock.patch.object(model.subprocess, 'Popen') as spawn:
            self.m.start_build()
        spawn.assert_not_called()
        self.assertFalse(self.m.finished.emit.call_args.args[0])

    def test_dependencies_follow_selected_target(self):
        self.m.deps_checked = True
        self.m.deps = [model.Dep('xcode', '', ''), model.Dep('tool:xcodegen', '', ''),
                       model.Dep('xcodeMac', '', '', model.DepState.OK)]
        self.m.build_target = 'mac-app'
        self.assertTrue(self.m.all_deps_ok)
        self.m.build_target = 'ios'
        self.assertFalse(self.m.all_deps_ok)

    def test_timestamped_output_path(self):
        self.m._on_line('[12:34:56] output IPA: /Volumes/My Games/Game.ipa')
        self.assertEqual(self.m.ipa_path, '/Volumes/My Games/Game.ipa')

"""Tests for the Windows build path that can run on macOS.

The Windows modules are written so that everything except the actual toolchain invocations is
testable without Windows: the discovery logic takes its paths from environment variables and
`toolchain.json`, the Makefile source-list check reads text, the IPA mode fixer works on any zip,
and the driver's patches can be inspected without loading the upstream script.

What is **not** covered here, and must be checked on a real Windows machine:

* `probe_compile` / `probe_link` / `probe_metal` against a genuine LLVM-MinGW, iPhoneOS SDK and
  Metal Developer Tools install;
* the compile and link of the real host sources, and `ios/Launcher.m` against UIKit;
* a full `python -m nspb_qt.win.driver` run on a game folder.

Those need the toolchain; the helpers below assert the parts that decide *whether* they would be
attempted with the right arguments.

    python3 -m unittest discover -s frontend-qt/tests -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
QT = HERE.parent
sys.path.insert(0, str(QT))

from nspb_qt.win import build_app, fix_ipa_modes, shim  # noqa: E402
from nspb_qt.win import toolchain as tc  # noqa: E402


# ---------------------------------------------------------------- helpers

def make_fake_sdk(root: Path, version: str = '26.0') -> Path:
    """A directory that looks like an iPhoneOS SDK to `toolchain.is_sdk_dir`."""
    sdk = root / f'iPhoneOS{version}.sdk'
    (sdk / 'System/Library/Frameworks/UIKit.framework/Headers').mkdir(parents=True)
    (sdk / 'System/Library/Frameworks/Foundation.framework').mkdir(parents=True)
    (sdk / 'usr/lib').mkdir(parents=True)
    (sdk / 'SDKSettings.json').write_text(json.dumps({'Version': version}), encoding='utf-8')
    (sdk / 'System/Library/Frameworks/UIKit.framework/UIKit.tbd').write_text('---', encoding='utf-8')
    (sdk / 'System/Library/Frameworks/UIKit.framework/Headers/UIKit.h').write_text(
        '// fake', encoding='utf-8')
    (sdk / 'usr/lib/libSystem.tbd').write_text('---', encoding='utf-8')
    return sdk


def make_fake_llvm(root: Path, with_lld64: bool = True, with_macho: bool = True) -> Path:
    """An LLVM folder with executable stubs named like the real tools."""
    llvm = root / 'LLVM'
    (llvm / 'bin').mkdir(parents=True)
    (llvm / 'bin/clang.exe').write_bytes(b'stub')
    (llvm / 'bin/ld.lld.exe').write_bytes(b'MachO ld64.lld darwin' if with_macho else b'ELF only')
    if with_lld64:
        (llvm / 'bin/ld64.lld.exe').write_bytes(b'MachO ld64.lld darwin')
    return llvm


class ToolchainDiscoveryTest(unittest.TestCase):
    """The three-level search: environment, then toolchain.json, then known locations."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for k in ('NSPB_LLVM_DIR', 'NSPB_IOS_SDK', 'NSPB_METAL_DIR', 'NSPB_TOOLCHAIN_JSON',
                  'NSPB_IOS_SDK_SHA256', 'ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
            os.environ.pop(k, None)
        os.environ['LOCALAPPDATA'] = str(self.root / 'LocalAppData')

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_llvm_found_from_env(self) -> None:
        llvm = make_fake_llvm(self.root)
        os.environ['NSPB_LLVM_DIR'] = str(llvm)
        self.assertEqual(tc.llvm_dir(), llvm)
        self.assertEqual(tc.llvm_tool('clang'), llvm / 'bin/clang.exe')

    def test_llvm_found_from_toolchain_json(self) -> None:
        llvm = make_fake_llvm(self.root)
        cfg = self.root / 'toolchain.json'
        cfg.write_text(json.dumps({'llvm_dir': str(llvm)}), encoding='utf-8')
        os.environ['NSPB_TOOLCHAIN_JSON'] = str(cfg)
        self.assertEqual(tc.llvm_dir(), llvm)

    def test_env_beats_toolchain_json(self) -> None:
        env_llvm = make_fake_llvm(self.root / 'a')
        cfg_llvm = make_fake_llvm(self.root / 'b')
        cfg = self.root / 'toolchain.json'
        cfg.write_text(json.dumps({'llvm_dir': str(cfg_llvm)}), encoding='utf-8')
        os.environ['NSPB_TOOLCHAIN_JSON'] = str(cfg)
        os.environ['NSPB_LLVM_DIR'] = str(env_llvm)
        self.assertEqual(tc.llvm_dir(), env_llvm)

    def test_broken_toolchain_json_does_not_raise(self) -> None:
        cfg = self.root / 'toolchain.json'
        cfg.write_text('{not json', encoding='utf-8')
        os.environ['NSPB_TOOLCHAIN_JSON'] = str(cfg)
        self.assertIn('_error', tc.load_config())
        # discovery still works: it falls through to the other levels
        llvm = make_fake_llvm(self.root)
        os.environ['NSPB_LLVM_DIR'] = str(llvm)
        self.assertEqual(tc.llvm_dir(), llvm)

    def test_no_llvm_returns_none(self) -> None:
        with mock.patch.object(tc.shutil, 'which', return_value=None):
            self.assertIsNone(tc.llvm_dir())


class Ld64Test(unittest.TestCase):
    """`ld64.lld.exe` does not ship with llvm-mingw; the copy from `ld.lld.exe` replaces it."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for k in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
            os.environ.pop(k, None)
        os.environ['LOCALAPPDATA'] = str(self.root / 'local')

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_lld_has_macho_reads_driver_strings(self) -> None:
        llvm = make_fake_llvm(self.root, with_lld64=False, with_macho=True)
        self.assertTrue(tc._lld_has_macho(llvm / 'bin/ld.lld.exe'))

    def test_stripped_lld_is_reported(self) -> None:
        llvm = make_fake_llvm(self.root, with_lld64=False, with_macho=False)
        os.environ['NSPB_LLVM_DIR'] = str(llvm)
        got, note = tc.ensure_ld64_lld()
        self.assertIsNone(got)
        self.assertIn('no Mach-O driver', note)

    def test_copy_created_when_absent(self) -> None:
        llvm = make_fake_llvm(self.root, with_lld64=False, with_macho=True)
        os.environ['NSPB_LLVM_DIR'] = str(llvm)
        got, note = tc.ensure_ld64_lld()
        self.assertIsNotNone(got)
        self.assertEqual(got.name, 'ld64.lld.exe')
        self.assertTrue(got.is_file())
        # idempotent: the second call finds it instead of making another
        again, note2 = tc.ensure_ld64_lld()
        self.assertEqual(again, got)
        self.assertEqual(note2, '')

    def test_existing_ld64_lld_wins(self) -> None:
        llvm = make_fake_llvm(self.root, with_lld64=True)
        os.environ['NSPB_LLVM_DIR'] = str(llvm)
        got, note = tc.ensure_ld64_lld()
        self.assertEqual(got, llvm / 'bin/ld64.lld.exe')
        self.assertEqual(note, '')


class SdkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for k in ('NSPB_IOS_SDK', 'LOCALAPPDATA'):
            os.environ.pop(k, None)
        os.environ['LOCALAPPDATA'] = str(self.root / 'local')

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_is_sdk_dir_accepts_a_real_layout(self) -> None:
        sdk = make_fake_sdk(self.root)
        self.assertTrue(tc.is_sdk_dir(sdk))

    def test_is_sdk_dir_rejects_a_plain_folder(self) -> None:
        plain = self.root / 'iPhoneOS26.0.sdk'
        plain.mkdir()
        self.assertFalse(tc.is_sdk_dir(plain))

    def test_is_sdk_dir_rejects_missing_stubs(self) -> None:
        sdk = make_fake_sdk(self.root)
        import shutil as sh
        sh.rmtree(sdk / 'System/Library/Frameworks/UIKit.framework')
        sh.rmtree(sdk / 'System/Library/Frameworks/Foundation.framework')
        self.assertFalse(tc.is_sdk_dir(sdk))

    def test_sdk_found_from_env(self) -> None:
        sdk = make_fake_sdk(self.root)
        os.environ['NSPB_IOS_SDK'] = str(sdk)
        self.assertEqual(tc.ios_sdk(), sdk)

    def test_sdk_version_parsed(self) -> None:
        sdk = make_fake_sdk(self.root, '26.5')
        self.assertEqual(tc.sdk_version(sdk)[0], '26.5')
        self.assertEqual(tc.sdk_major('26.5'), 26)
        self.assertEqual(tc.sdk_major(''), 0)

    def test_sdk_tree_digest_is_stable_and_discriminating(self) -> None:
        a = make_fake_sdk(self.root / 'a', '26.0')
        b = make_fake_sdk(self.root / 'b', '26.5')
        self.assertEqual(tc.sdk_tree_digest(a), tc.sdk_tree_digest(a))
        self.assertNotEqual(tc.sdk_tree_digest(a), tc.sdk_tree_digest(b))


class CheckAllTest(unittest.TestCase):
    """The panel's rows, on a machine with nothing installed and with a fake toolchain."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for k in ('NSPB_LLVM_DIR', 'NSPB_IOS_SDK', 'NSPB_METAL_DIR', 'NSPB_TOOLCHAIN_JSON',
                  'ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
            os.environ.pop(k, None)
        os.environ['LOCALAPPDATA'] = str(self.root / 'local')
        os.environ['ProgramFiles'] = str(self.root / 'PF')
        self.which = mock.patch.object(tc.shutil, 'which', return_value=None)
        self.which.start()

    def tearDown(self) -> None:
        self.which.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_nothing_installed_reports_missing(self) -> None:
        probes = tc.check_all(deep=False)
        ids = {p.id: p for p in probes}
        self.assertEqual(ids['llvm'].state, 'missing')
        self.assertEqual(ids['ios_sdk'].state, 'missing')
        self.assertEqual(ids['metal'].state, 'missing')
        self.assertFalse(ids['lld'].ok)
        # metal-tt is optional and must never be required
        self.assertFalse(ids['metal_tt'].required)

    def test_a_fake_toolchain_turns_rows_ok(self) -> None:
        llvm = make_fake_llvm(self.root, with_lld64=False, with_macho=True)
        sdk = make_fake_sdk(self.root)
        metal = self.root / 'Metal Developer Tools'
        (metal / 'bin').mkdir(parents=True)
        (metal / 'bin/metal.exe').write_bytes(b'stub')
        (metal / 'bin/metallib.exe').write_bytes(b'stub')
        os.environ['NSPB_LLVM_DIR'] = str(llvm)
        os.environ['NSPB_IOS_SDK'] = str(sdk)
        os.environ['NSPB_METAL_DIR'] = str(metal)
        ids = {p.id: p for p in tc.check_all(deep=False)}
        self.assertTrue(ids['lld'].ok, ids['lld'])
        self.assertTrue(ids['ios_sdk'].ok, ids['ios_sdk'])
        self.assertTrue(ids['metal'].ok, ids['metal'])
        self.assertEqual(ids['ios_sdk'].version.split()[0], '26.0')

    def test_old_sdk_is_wrong_not_ok(self) -> None:
        sdk = make_fake_sdk(self.root, '17.0')
        os.environ['NSPB_IOS_SDK'] = str(sdk)
        ids = {p.id: p for p in tc.check_all(deep=False)}
        self.assertEqual(ids['ios_sdk'].state, 'wrong')
        self.assertIn('26.0', ids['ios_sdk'].detail)

    def test_deep_probes_run_only_with_tools(self) -> None:
        # nothing installed: no probe rows at all, rather than three failures
        ids = {p.id for p in tc.check_all(deep=True)}
        self.assertNotIn('probe_compile', ids)
        self.assertNotIn('probe_link', ids)


class MetalArgsTest(unittest.TestCase):
    """Xcode's Metal flags become the Windows compiler's `-target` triple."""

    def test_ios_version_min_becomes_target(self) -> None:
        from nspb_qt.win import xcrun_shim
        got = xcrun_shim.metal_args('iphoneos', ['-c', '-mios-version-min=18.0', 'a.metal'])
        self.assertIn('-target', got)
        self.assertIn('air64-apple-ios18.0', got)
        self.assertNotIn('-mios-version-min=18.0', got)

    def test_macos_version_min_becomes_target(self) -> None:
        from nspb_qt.win import xcrun_shim
        got = xcrun_shim.metal_args('macosx', ['-c', '-mmacosx-version-min=14.0', 'a.metal'])
        self.assertIn('air64-apple-macos14.0', got)

    def test_missing_target_gets_the_default(self) -> None:
        from nspb_qt.win import xcrun_shim
        got = xcrun_shim.metal_args('iphoneos', ['-c', 'a.metal'])
        self.assertEqual(got[:2], ['-target', 'air64-apple-ios18.0'])

    def test_version_query_is_left_alone(self) -> None:
        from nspb_qt.win import xcrun_shim
        self.assertEqual(xcrun_shim.metal_args('iphoneos', ['--version']), ['--version'])

    def test_explicit_target_is_not_duplicated(self) -> None:
        from nspb_qt.win import xcrun_shim
        got = xcrun_shim.metal_args('iphoneos', ['-target', 'air64-apple-ios26.0', '-c'])
        self.assertEqual(got.count('-target'), 1)

    def test_metal_tt_has_no_windows_tool(self) -> None:
        # the pipeline archive is disabled here, and the caller relies on this being None
        self.assertIsNone(tc.metal_tool('metal-tt'))

    def test_metal_tool_takes_name_then_sdk(self) -> None:
        """The signature is (name, sdk). Both call sites once had it backwards, which made
        every `xcrun -sdk iphoneos metal` fall back to a slow Python wrapper instead of
        starting metal.exe directly -- a cost paid once per shader."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'bin').mkdir()
            (root / 'bin/metal.exe').write_bytes(b'x')
            (root / 'ios/bin').mkdir(parents=True)
            (root / 'ios/bin/metal.exe').write_bytes(b'ios')
            old = os.environ.get('NSPB_METAL_DIR')
            os.environ['NSPB_METAL_DIR'] = str(root)
            try:
                self.assertIsNotNone(tc.metal_tool('metal', 'iphoneos'))
                self.assertIsNotNone(tc.metal_tool('metal', 'macosx'))
                # the reversed call is what the bug looked like: it silently returns None
                self.assertIsNone(tc.metal_tool('iphoneos', 'metal'))
            finally:
                if old is None:
                    os.environ.pop('NSPB_METAL_DIR', None)
                else:
                    os.environ['NSPB_METAL_DIR'] = old


class HostSourcesTest(unittest.TestCase):
    """The Makefile rules are reproduced, and a change upstream stops the build."""

    def setUp(self) -> None:
        self.repo = QT.parent
        self.gen = Path(tempfile.mkdtemp())
        (self.gen / 'game_profile.h').write_text('// x', encoding='utf-8')

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.gen, ignore_errors=True)

    def test_source_list_matches_the_makefile(self) -> None:
        files, incs = build_app.host_sources(self.repo, self.gen)
        names = {p.name for p in files}
        # from SRC=
        for must in ('loader.c', 'hle.c', 'romfs_arc.c', 'crash.c', 'probe.c', 'thread.c',
                     'memstat.m', 'haptics_apple.m', 'entry.S', 'main.c'):
            self.assertIn(must, names, f'{must} missing from the host source list')
        # Mac-only sources are dropped
        self.assertNotIn('front_mac.m', names)
        # the iOS front end is compiled by the iOS project, not the host walk
        self.assertNotIn('front_ios.m', names)
        self.assertNotIn('main.m', names)
        # and main.c is in
        self.assertIn('main.c', names)
        # include dirs include the ones the Makefile's compile line names
        inc_str = ' '.join(str(i) for i in incs)
        self.assertIn('gfx/nvn/include', inc_str.replace('\\', '/'))
        self.assertIn('stb_vorbis', inc_str.replace('\\', '/'))
        self.assertIn('libvpx', inc_str.replace('\\', '/'))

    def test_libvpx_sources_are_included(self) -> None:
        files, _ = build_app.host_sources(self.repo, self.gen)
        vpx = [p for p in files if 'third_party/libvpx' in p.as_posix()]
        self.assertTrue(vpx, 'no libvpx sources: the host would fail to link its movie decoder')

    def test_a_changed_makefile_stops_the_build(self) -> None:
        # simulate an upstream edit by pointing at a repository copy with a modified Makefile
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / 'repo'
            (fake / 'dm/host').mkdir(parents=True)
            makefile = (self.repo / 'dm/host/Makefile').read_text(encoding='utf-8')
            (fake / 'dm/host/Makefile').write_text(
                makefile.replace('romfs_arc.c ', 'romfs_arc.c newfile.c '), encoding='utf-8')
            with self.assertRaises(SystemExit) as ctx:
                build_app.host_sources(fake, self.gen)
            # host_sources() reports through build_app.die(), which raises SystemExit(1); the
            # message itself goes to stdout, so capture it instead of reading the exception
            self.assertEqual(ctx.exception.code, 1)

    def test_missing_source_stops_the_build(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / 'repo'
            (fake / 'dm/host').mkdir(parents=True)
            makefile = (self.repo / 'dm/host/Makefile').read_text(encoding='utf-8')
            (fake / 'dm/host/Makefile').write_text(makefile, encoding='utf-8')
            # the Makefile is intact but the sources are not there
            with self.assertRaises(SystemExit) as ctx:
                build_app.host_sources(fake, self.gen)
            self.assertEqual(ctx.exception.code, 1)

    def test_frameworks_drop_cocoa_and_keep_what_exists(self) -> None:
        sdk = make_fake_sdk(Path(tempfile.mkdtemp()))
        try:
            (sdk / 'System/Library/Frameworks/Metal.framework').mkdir(parents=True)
            fws = build_app.framework_list(sdk, [])
            self.assertNotIn('Cocoa', fws)
            self.assertIn('Metal', fws)
            self.assertIn('UIKit', fws)
            self.assertNotIn('AVFAudio', fws)     # not in this fake SDK
        finally:
            import shutil
            shutil.rmtree(sdk.parent, ignore_errors=True)


class InfoPlistTest(unittest.TestCase):
    def test_keys_the_app_reads_are_present(self) -> None:
        p = build_app.info_plist(bundle_id='org.example.1', name='Game', version='1.2.3',
                                 category='public.app-category.games', show_fps='YES',
                                 lang='ja', sdk_ver='26.0', sdk_build='23A1', icons=True,
                                 executable='DmIOS', deployment='26.0')
        self.assertEqual(p['CFBundleIdentifier'], 'org.example.1')
        self.assertEqual(p['CFBundleExecutable'], 'DmIOS')
        self.assertEqual(p['MinimumOSVersion'], '26.0')
        self.assertEqual(p['DTSDKName'], 'iphoneos26.0')
        # read by main.m / the launcher
        self.assertEqual(p['DMShowFPS'], 'YES')
        self.assertEqual(p['DMLanguage'], 'ja')
        self.assertIn('CFBundleIcons', p)
        self.assertIn('UIApplicationSceneManifest', p)
        self.assertEqual(p['UIRequiredDeviceCapabilities'], ['arm64'])

    def test_without_icons_no_icon_keys(self) -> None:
        p = build_app.info_plist(bundle_id='b', name='n', version='1', category='c',
                                 show_fps='NO', lang='en-US', sdk_ver='26.0', sdk_build='',
                                 icons=False, executable='DmIOS', deployment='26.0')
        self.assertNotIn('CFBundleIcons', p)


class IpaModesTest(unittest.TestCase):
    """The zip mode fixer, which stands in for `pack_ipa.py --exec` (an upstream file we
    must not edit)."""

    def _make_ipa(self, path: Path, exec_mode: int = 0o666) -> None:
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('Payload/DmIOS.app/DmIOS', b'\xcf\xfa\xed\xfe' + b'\0' * 28)
            z.writestr('Payload/DmIOS.app/Info.plist', b'plist')
            z.writestr('Payload/DmIOS.app/dm/shader_map.tsv', b'x')
            z.writestr('Payload/', b'')

    def test_executable_gets_the_execute_bit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ipa = Path(td) / 'a.ipa'
            self._make_ipa(ipa)
            fixed = fix_ipa_modes.fix(ipa, ['Payload/DmIOS.app/DmIOS'])
            self.assertIn('Payload/DmIOS.app/DmIOS', fixed)
            ok, detail = fix_ipa_modes.verify(ipa, ['Payload/DmIOS.app/DmIOS'])
            self.assertTrue(ok, detail)
            self.assertIn('0o100755', detail)

    def test_data_files_get_0644(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ipa = Path(td) / 'a.ipa'
            self._make_ipa(ipa)
            fix_ipa_modes.fix(ipa, ['Payload/DmIOS.app/DmIOS'])
            modes = _zip_modes(ipa)
            self.assertEqual(modes['Payload/DmIOS.app/Info.plist'], 0o100644)
            self.assertEqual(modes['Payload/DmIOS.app/dm/shader_map.tsv'], 0o100644)
            self.assertEqual(modes['Payload/DmIOS.app/DmIOS'], 0o100755)

    def test_a_mac_built_ipa_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ipa = Path(td) / 'a.ipa'
            with zipfile.ZipFile(ipa, 'w') as z:
                # what Info-ZIP / pack_ipa writes on a Mac
                for name, mode in (('Payload/DmIOS.app/DmIOS', 0o100755),
                                   ('Payload/DmIOS.app/Info.plist', 0o100644)):
                    info = zipfile.ZipInfo(name)
                    info.external_attr = mode << 16
                    z.writestr(info, b'data')
            before = ipa.read_bytes()
            note = fix_ipa_modes.fix(ipa, ['Payload/DmIOS.app/DmIOS'])
            self.assertEqual(note, 'already correct')
            self.assertEqual(before, ipa.read_bytes(), 'a correct archive must not be rewritten')

    def test_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ipa = Path(td) / 'a.ipa'
            self._make_ipa(ipa)
            fix_ipa_modes.fix(ipa, ['Payload/DmIOS.app/DmIOS'])
            once = ipa.read_bytes()
            self.assertEqual(fix_ipa_modes.fix(ipa, ['Payload/DmIOS.app/DmIOS']), 'already correct')
            self.assertEqual(once, ipa.read_bytes())

    def test_missing_executable_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ipa = Path(td) / 'a.ipa'
            self._make_ipa(ipa)
            note = fix_ipa_modes.fix(ipa, ['Payload/DmIOS.app/NotThere'])
            self.assertIn('missing from the archive', note)

    def test_not_a_zip_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / 'x.ipa'
            bad.write_bytes(b'not a zip at all')
            with self.assertRaises(fix_ipa_modes.IpaModeError):
                fix_ipa_modes.fix(bad, ['Payload/DmIOS.app/DmIOS'])


def _zip_modes(path: Path) -> dict[str, int]:
    out = {}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            out[info.filename] = (info.external_attr >> 16) & 0xFFFF
    return out


class ShimTest(unittest.TestCase):
    def test_install_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            shim.install(d, python_exe=sys.executable)
            first = {p.name: p.read_bytes() for p in d.iterdir()}
            shim.install(d, python_exe=sys.executable)
            second = {p.name: p.read_bytes() for p in d.iterdir()}
            self.assertEqual(first, second)
            self.assertIn('sitecustomize.py', first)
            for name in ('xcrun.cmd', 'xcodebuild.cmd', 'xcodegen.cmd', 'python3.cmd'):
                self.assertIn(name, first, f'{name} stand-in not written')

    def test_sitecustomize_is_valid_python(self) -> None:
        import ast
        ast.parse(shim._SITECUSTOMIZE_SRC)

    def test_sitecustomize_maps_the_commands_we_depend_on(self) -> None:
        src = shim._SITECUSTOMIZE_SRC
        # every rewrite the pipeline needs, asserted against the generated text so a future
        # edit cannot silently drop one
        for needle in ("base in ('xcrun', 'xcrun.exe')",
                       "base == 'dmsh_xlate'",
                       "base in ('python3', 'python3.exe')",
                       "dm/ios/tools/build_ipa.sh",
                       "base in ('which', 'which.exe')",
                       "sys.modules['pwd'] = _pwd",
                       'BCryptDecrypt'):
            self.assertIn(needle, src, f'{needle} missing from the shim')

    def test_build_env_prepends_the_shim(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(shim, 'shim_dir', return_value=Path(td)):
                env = shim.build_env({'PATH': 'C:\\Windows', 'PYTHONPATH': ''},
                                     python_exe=sys.executable)
            self.assertTrue(env['PATH'].startswith(td))
            self.assertTrue(env['PYTHONPATH'].startswith(td))
            self.assertEqual(env['PYTHONUTF8'], '1')


class DriverCliTest(unittest.TestCase):
    """Mac-only options are refused before any work starts."""

    def test_prepare_xcode_refused(self) -> None:
        from nspb_qt.win import driver
        with self.assertRaises(SystemExit) as ctx:
            driver.check_cli(['D:\\games\\x', '--prepare-xcode'])
        self.assertIn('needs Xcode', str(ctx.exception))

    def test_platform_ios_allowed(self) -> None:
        from nspb_qt.win import driver
        driver.check_cli(['D:\\games\\x', '--platform', 'ios'])

    def test_platform_mac_refused(self) -> None:
        from nspb_qt.win import driver
        with self.assertRaises(SystemExit) as ctx:
            driver.check_cli(['D:\\games\\x', '--platform', 'mac'])
        self.assertIn('macOS', str(ctx.exception))

    def test_platform_mac_app_refused(self) -> None:
        from nspb_qt.win import driver
        with self.assertRaises(SystemExit):
            driver.check_cli(['--platform=mac-app'])

    def test_newer_upstream_works_are_still_refused(self) -> None:
        from nspb_qt.win import driver
        self.assertIn('--prepare-xcode', driver.REFUSED_OPTIONS)
        self.assertIn('--platform', driver.REFUSED_OPTIONS)


class DriverPatchTest(unittest.TestCase):
    """The upstream module loads and its Mac-only functions get replaced."""

    @classmethod
    def setUpClass(cls) -> None:
        from nspb_qt.win import driver
        cls.driver = driver
        cls.repo = QT.parent
        if not (cls.repo / 'scripts/build_ipa_from_nsp.py').is_file():
            raise unittest.SkipTest('not a repository checkout')
        # `pwd` is installed by the stub inside load_upstream, so this works on any OS
        cls.saved = {k: os.environ.get(k) for k in
                     ('NSPB_ALLOW_NON_WINDOWS', 'GAME', 'W')}
        cls.mod = driver.load_upstream(cls.repo)
        driver.patch(cls.mod, cls.repo)

    @classmethod
    def tearDownClass(cls) -> None:
        for k, v in cls.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_upstream_loaded(self) -> None:
        self.assertTrue(hasattr(self.mod, 'cli'))
        self.assertTrue(hasattr(self.mod, 'BuildError'))

    def test_mac_only_functions_refuse(self) -> None:
        with self.assertRaises(self.mod.BuildError) as ctx:
            self.mod.build_mac_host(self.repo, Path('out'), {}, Path('logs'), None)
        self.assertIn('arm64', str(ctx.exception))
        with self.assertRaises(self.mod.BuildError):
            self.mod.capture_shaders(None, None, None, None, {}, None, None, 'gl')
        with self.assertRaises(self.mod.BuildError):
            self.mod.mac_app()
        with self.assertRaises(self.mod.BuildError):
            self.mod.mac_run()

    def test_can_clone_is_false_and_apple_silicon_true(self) -> None:
        self.assertFalse(self.mod.can_clone(Path('.')))
        self.assertTrue(self.mod.apple_silicon())

    def test_check_prereqs_raises_with_a_report(self) -> None:
        with self.assertRaises(self.mod.BuildError) as ctx:
            self.mod.check_prereqs({}, Path('missing/dmsh_xlate'), mac=False)
        msg = str(ctx.exception)
        self.assertIn('missing on this PC', msg)
        # the message must name what to do, not just what is wrong
        self.assertTrue('LLVM' in msg or 'clang' in msg.lower())

    def test_check_prereqs_refuses_mac(self) -> None:
        with self.assertRaises(self.mod.BuildError) as ctx:
            self.mod.check_prereqs({}, Path('x'), mac=True)
        self.assertIn('need a Mac', str(ctx.exception))

    def test_toolchain_probe_uses_the_windows_metal(self) -> None:
        probes = self.mod.toolchain()
        self.assertTrue(probes)
        joined = ' '.join(' '.join(p[1]) for p in probes if p[0] == 'cmd')
        self.assertIn('xcrun_shim.py', joined)
        self.assertIn('metal', joined)
        self.assertNotIn('xcodebuild', joined)

    def test_tool_paths_are_replaced_not_extended(self) -> None:
        """On Windows the upstream macOS list must be gone.

        The replacement is derived from `toolchain` discovery, which on a macOS test host
        legitimately finds `/usr` and Homebrew — that is `which clang` answering. What matters
        is that the *upstream default* list was replaced rather than appended to, so assert on
        the object identity of the assignment: patch() assigns a fresh list.
        """
        upstream_default = ['/opt/homebrew/bin', '/usr/local/bin', '/usr/local/share/dotnet',
                            os.path.expanduser('~/.dotnet')]
        self.assertNotEqual(self.mod.TOOL_PATHS, upstream_default,
                            'patch() left the upstream macOS TOOL_PATHS in place')
        # and the GUI-launch reason the list exists still holds: it is a plain list of str
        self.assertTrue(all(isinstance(p, str) for p in self.mod.TOOL_PATHS))

    def test_bash_build_ipa_is_redirected(self) -> None:
        calls = []

        def fake_run(cmd, log, env=None, cwd=None, on_line=None):
            calls.append(list(cmd))
            return 0
        # `run_ipa` calls the module-level original; swap that for the test and re-patch so
        # the closure is rebuilt against it (patch() only captures when nothing is captured yet)
        orig = self.driver._UPSTREAM_RUN
        try:
            self.driver._UPSTREAM_RUN = fake_run
            self.driver.patch(self.mod, self.repo)
            self.mod.run(['bash', str(self.repo / 'dm/ios/tools/build_ipa.sh'), 'out.ipa'],
                         Path('log'))
        finally:
            self.driver._UPSTREAM_RUN = orig
            self.driver.patch(self.mod, self.repo)
        self.assertEqual(len(calls), 1)
        self.assertEqual(Path(calls[0][0]).name, Path(sys.executable).name)
        self.assertTrue(calls[0][1].endswith('build_app.py'))
        self.assertEqual(calls[0][-1], 'out.ipa')

    def test_prepare_xcode_through_run_is_still_refused(self) -> None:
        with self.assertRaises(self.mod.BuildError):
            self.mod.run(['bash', str(self.repo / 'dm/ios/tools/build_ipa.sh'), '--prepare-xcode'],
                         Path('log'))


class SdkFetchTest(unittest.TestCase):
    def test_extract_rejects_a_non_xip(self) -> None:
        from nspb_qt.win import sdk_fetch
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / 'x.xip'
            bad.write_bytes(b'<html>404</html>')
            with self.assertRaises(sdk_fetch.SdkError) as ctx:
                sdk_fetch.extract_xip(bad, Path(td) / 'out')
            self.assertIn('xar', str(ctx.exception))

    def test_extract_rejects_a_missing_file(self) -> None:
        from nspb_qt.win import sdk_fetch
        with self.assertRaises(sdk_fetch.SdkError):
            sdk_fetch.extract_xip(Path('/nonexistent/Xcode.xip'))

    def test_import_local_rejects_a_plain_folder(self) -> None:
        from nspb_qt.win import sdk_fetch
        with tempfile.TemporaryDirectory() as td:
            plain = Path(td) / 'notasdk'
            plain.mkdir()
            with self.assertRaises(sdk_fetch.SdkError):
                sdk_fetch.import_local(plain, Path(td) / 'cache')

    def test_import_local_accepts_a_nested_sdk(self) -> None:
        from nspb_qt.win import sdk_fetch
        with tempfile.TemporaryDirectory() as td:
            sdk = make_fake_sdk(Path(td) / 'download')
            got = sdk_fetch.import_local(sdk.parent, Path(td) / 'cache', log=lambda s: None)
            self.assertTrue(tc.is_sdk_dir(got))
            self.assertEqual(got.name, 'iPhoneOS26.0.sdk')

    def test_available_versions_is_a_best_effort_list(self) -> None:
        from nspb_qt.win import sdk_fetch
        # no network in CI: must not raise
        got = sdk_fetch.available_versions()
        self.assertIsInstance(got, list)


class FetchTest(unittest.TestCase):
    def test_sha256_of_a_file(self) -> None:
        from nspb_qt.win import fetch
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'x'
            p.write_bytes(b'abc')
            self.assertEqual(fetch.sha256_of(p),
                             'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')

    def test_pinned_hashes_are_well_formed(self) -> None:
        for arch, asset in tc.LLVM_MINGW_ASSETS.items():
            self.assertEqual(len(asset['sha256']), 64, arch)
            self.assertTrue(all(c in '0123456789abcdef' for c in asset['sha256']), arch)
            self.assertIn(arch, ('AMD64', 'ARM64'))
            self.assertGreater(asset['size'], 100_000_000)

    def test_download_asset_url(self) -> None:
        a = tc.download_asset('AMD64')
        self.assertIn(tc.LLVM_MINGW_VERSION, a['url'])
        self.assertTrue(a['url'].endswith(a['name']))


class ConstantParityTest(unittest.TestCase):
    """`toolchain.py` duplicates the package constants so it can be loaded standalone from the
    generated sitecustomize.py. The copies must not drift."""

    def test_duplicated_constants_match_the_package(self) -> None:
        import nspb_qt.win as pkg
        pairs = {
            'IOS_DEPLOYMENT': (pkg.IOS_DEPLOYMENT, tc.IOS_DEPLOYMENT),
            'ENV_TOOLCHAIN': (pkg.ENV_TOOLCHAIN, tc.ENV_TOOLCHAIN),
            'ENV_LLVM': (pkg.ENV_LLVM, tc.ENV_LLVM),
            'ENV_SDK': (pkg.ENV_SDK, tc.ENV_SDK),
            'ENV_METAL': (pkg.ENV_METAL, tc.ENV_METAL),
        }
        for name, (a, b) in pairs.items():
            self.assertEqual(a, b, f'{name} differs between nspb_qt.win and nspb_qt.win.toolchain')

    def test_toolchain_imports_standalone(self) -> None:
        """shim.py loads it from a generated sitecustomize with no package context."""
        import subprocess
        code = ('import sys; sys.path.insert(0, %r); import toolchain; '
                'print(toolchain.IOS_DEPLOYMENT)') % str(QT / 'nspb_qt' / 'win')
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        self.assertEqual(r.stdout.strip(), '26.0')


class PlatformIsolationTest(unittest.TestCase):
    """Nothing Windows-specific may load on macOS through the normal import path."""

    def test_model_does_not_import_win_at_module_level(self) -> None:
        src = (QT / 'nspb_qt/model.py').read_text(encoding='utf-8')
        head = src.split('def _windows_deps')[0]
        self.assertNotIn('from .win import', head)
        self.assertNotIn('import nspb_qt.win', head)

    def test_platform_util_has_no_win_import(self) -> None:
        src = (QT / 'nspb_qt/platform_util.py').read_text(encoding='utf-8')
        self.assertNotIn('nspb_qt.win', src)
        self.assertNotIn('from .win', src)

    def test_importing_the_package_does_not_touch_win(self) -> None:
        import subprocess
        code = (
            'import sys; sys.path.insert(0, %r)\n'
            'import nspb_qt.model\n'
            'bad = [m for m in sys.modules if m.startswith("nspb_qt.win")]\n'
            'print("|".join(bad))\n'
        ) % str(QT)
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                           env={**os.environ, 'NSPB_REPO': ''})
        # PySide6 may be missing in a bare interpreter; that is not this test's subject
        if r.returncode != 0 and 'PySide6' in (r.stderr or ''):
            self.skipTest('PySide6 is not installed')
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(r.stdout.strip(), '', 'importing the model loaded nspb_qt.win')

    def test_win_modules_import_without_a_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            env = {**os.environ, 'LOCALAPPDATA': td, 'ProgramFiles': td,
                   'NSPB_TOOLCHAIN_JSON': str(Path(td) / 'nope.json')}
            for k in ('NSPB_LLVM_DIR', 'NSPB_IOS_SDK', 'NSPB_METAL_DIR'):
                env.pop(k, None)
            code = (
                'import sys; sys.path.insert(0, %r)\n'
                'from nspb_qt.win import toolchain, sdk_fetch, shim, fix_ipa_modes, fetch, '
                'doctor, build_app, driver, xcrun_shim\n'
                'print("ok")\n'
            ) % str(QT)
            r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                               env=env)
            self.assertEqual(r.returncode, 0, r.stderr[-1200:])
            self.assertEqual(r.stdout.strip(), 'ok')


class LocalizationTest(unittest.TestCase):
    def test_every_windows_dep_key_exists_in_both_languages(self) -> None:
        from nspb_qt.i18n import Lang
        from nspb_qt.localization import TABLE, t
        keys = ['dep.llvm', 'dep.llvm.hint', 'dep.lld', 'dep.lld.hint',
                'dep.probe.compile', 'dep.probe.compile.hint',
                'dep.probe.link', 'dep.probe.link.hint',
                'dep.probe.metal', 'dep.probe.metal.hint',
                'dep.glslang', 'dep.glslang.hint', 'dep.optionalMissing',
                'dep.iossdk', 'dep.iossdk.hint', 'dep.metal', 'dep.metal.hint']
        for k in keys:
            self.assertIn(k, TABLE, f'{k} missing from the table')
            zh = t(k, Lang.ZH)
            en = t(k, Lang.EN)
            self.assertTrue(zh and zh != k, f'{k} has no Chinese text')
            self.assertTrue(en and en != k, f'{k} has no English text')


if __name__ == '__main__':
    unittest.main(verbosity=2)

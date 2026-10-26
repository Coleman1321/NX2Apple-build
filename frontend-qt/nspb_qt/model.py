"""State, dependency detection and the build runner. No UI here: the window connects to signals."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import platform_util as pu
from .i18n import Lang
from .localization import t


# ---------------------------------------------------------------- dependency rows

class DepState(Enum):
    OK = 'ok'
    MISSING = 'missing'
    OLD = 'old'          # present but unusable (a too-old interpreter, a stub launcher)


@dataclass
class Dep:
    id: str
    title_key: str
    hint_key: str
    state: DepState = DepState.MISSING
    detail: str = ''            # a path, or a localisation key, or "key:arg"
    install: list[str] = field(default_factory=list)   # command that fixes it, empty = manual
    installing: bool = False

    @property
    def ok(self) -> bool:
        return self.state is DepState.OK


# ---------------------------------------------------------------- build stages

@dataclass
class Stage:
    name: str
    state: str = 'pending'      # pending | running | done | failed
    detail: str = ''
    percent: float = 0.0


# ---------------------------------------------------------------- the model

class Model(QObject):
    """Everything the window reads, and every action it can take.

    Long work runs on a thread and reports through signals, so the window never blocks: Qt
    requires UI updates on the main thread, and a build takes minutes.
    """

    depsChanged = Signal()
    stagesChanged = Signal()
    logAppended = Signal(str)
    repoChanged = Signal()
    runningChanged = Signal(bool)
    finished = Signal(bool, str)          # ok, note
    appUpdateFound = Signal(str, str)     # tag, url

    def __init__(self) -> None:
        super().__init__()
        self.lang = Lang.initial()
        self.repo_path = self._find_repo()
        self.python_path, self.python_ok, self.python_ver = pu.find_python()
        self.dotnet_path, self.dotnet_ok = pu.find_dotnet()
        self.deps: list[Dep] = []
        self.deps_checked = False
        self.stages: list[Stage] = []
        self.running = False
        self.log_tail = ''
        self.game_dir = ''
        self.base_path = ''
        self.update_path = ''
        self.dlc_paths: list[str] = []
        self.keys_path = ''
        self.out_dir = ''
        self.ipa_path = ''
        self.archive_path = ''
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._line_buf = ''

    # ---- strings

    def t(self, key: str, *args: object) -> str:
        return t(key, self.lang, *args)

    def toggle_lang(self) -> None:
        self.lang = self.lang.other
        self.repoChanged.emit()
        self.depsChanged.emit()

    # ---- repository

    @staticmethod
    def is_repo(d: str) -> bool:
        return bool(d) and Path(d, 'dm', 'tools', 'nx_extract', 'Program.cs').is_file()

    def _find_repo(self) -> str:
        saved = os.environ.get('NSPB_REPO', '')
        if self.is_repo(saved):
            return saved
        seeds = [Path.cwd(), Path(__file__).resolve().parents[2], Path.home()]
        for base in ('Documents', 'Desktop', ''):
            seeds.append(Path.home() / base / 'NX2Apple' if base else Path.home() / 'NX2Apple')
        for s in seeds:
            d = Path(s)
            for _ in range(4):
                if self.is_repo(str(d)):
                    return str(d)
                if d.parent == d:
                    break
                d = d.parent
        return ''

    @property
    def repo_ok(self) -> bool:
        return self.is_repo(self.repo_path)

    @property
    def repo_is_git(self) -> bool:
        return bool(self.repo_path) and Path(self.repo_path, '.git').exists()

    def supports_work_dir(self) -> bool:
        """Whether the checkout's build script declares --work-dir (an upstream checkout or an
        old ZIP does not; passing it there stops at argparse — issue #5)."""
        f = Path(self.repo_path, 'scripts', 'build_ipa_from_nsp.py')
        try:
            text = f.read_text(encoding='utf-8', errors='replace')
        except OSError:
            return False
        return "'--work-dir'" in text or '"--work-dir"' in text

    # ---- dependencies

    def check_deps(self) -> None:
        self.deps_checked = False
        threading.Thread(target=self._check_deps_worker, daemon=True).start()

    def _check_deps_worker(self) -> None:
        deps: list[Dep] = []

        # Python + packages
        py, py_ok, py_ver = pu.find_python()
        if py_ok:
            deps.append(Dep('python', 'dep.python', 'dep.python.hint', DepState.OK, py))
        elif py_ver and pu._ver_tuple(py_ver) >= (3, 9):
            deps.append(Dep('python', 'dep.python', 'dep.python.hint', DepState.MISSING,
                            f'dep.python.missing:{py} ({py_ver})',
                            install=[py, '-m', 'pip', 'install', 'lz4', 'capstone', 'fonttools',
                                     'backports.zstd', 'nsz']))
        else:
            deps.append(Dep('python', 'dep.python', 'dep.python.hint', DepState.OLD,
                            f'dep.python.old:{py_ver or "?"}:3.9'))

        # .NET
        dn, dn_ok = pu.find_dotnet()
        deps.append(Dep('dotnet', 'dep.dotnet', 'dep.dotnet.hint',
                        DepState.OK if dn_ok else DepState.MISSING,
                        dn if dn_ok else 'dep.dotnet.missing'))

        # Xcode (macOS) or the cross toolchain (Windows)
        if pu.IS_WIN:
            sdk = pu.ios_sdk_ok()
            deps.append(Dep('ios_sdk', 'dep.iossdk', 'dep.iossdk.hint',
                            DepState.OK if sdk else DepState.MISSING,
                            os.environ.get('IPHONEOS_SDK_DIR', '') if sdk else ''))
            mtl = pu.metal_toolchain_ok()
            deps.append(Dep('metal', 'dep.metal', 'dep.metal.hint',
                            DepState.OK if mtl else DepState.MISSING,
                            pu.find_tool('metal') or ''))
        else:
            xc = pu.xcode_ok()
            sdk = xc and pu.ios_sdk_ok()
            deps.append(Dep('xcode', 'dep.xcode', 'dep.xcode.hint',
                            DepState.OK if sdk else DepState.MISSING,
                            '' if sdk else ('dep.xcode.noSDK' if xc else ''),
                            install=[] if sdk else (['/usr/bin/xcodebuild', '-downloadPlatform', 'iOS'] if xc else [])))
            mtl = pu.metal_toolchain_ok()
            deps.append(Dep('metal', 'dep.metal', 'dep.metal.hint',
                            DepState.OK if mtl else DepState.MISSING,
                            '' if mtl else 'dep.metal.missing',
                            install=[] if mtl else ['/usr/bin/xcodebuild', '-downloadComponent', 'MetalToolchain']))

        # the remaining command-line tools
        for tool, key in (('xcodegen', 'dep.xcodegen'), ('zstd', 'dep.zstd'), ('spirv-cross', 'dep.spirv')):
            found = pu.find_tool(tool)
            deps.append(Dep('tool:' + tool, key, key + '.hint',
                            DepState.OK if found else DepState.MISSING, found or ''))

        self.deps = deps
        self.python_path, self.python_ok, self.python_ver = py, py_ok, py_ver
        self.dotnet_path, self.dotnet_ok = dn, dn_ok
        self.deps_checked = True
        self.depsChanged.emit()

    @property
    def all_deps_ok(self) -> bool:
        return self.deps_checked and all(d.ok for d in self.deps)

    def install_dep(self, dep: Dep) -> None:
        """Run a dependency's fix on a thread, streaming its output to the log."""
        if not dep.install:
            return
        dep.installing = True
        self.depsChanged.emit()

        def work() -> None:
            ok = True
            if dep.id == 'python':
                ok = self._make_venv(self.python_path)
            else:
                self.logAppended.emit('$ ' + ' '.join(dep.install) + '\n')
                try:
                    p = subprocess.Popen(dep.install, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True,
                                         errors='replace', env=pu.child_env(),
                                         **pu.no_window_kwargs())
                    assert p.stdout is not None
                    for line in p.stdout:
                        self.logAppended.emit(line)
                    p.wait()
                    ok = p.returncode == 0
                except OSError as e:
                    self.logAppended.emit(f'{e}\n')
                    ok = False
            dep.installing = False
            self.depsChanged.emit()
            self.check_deps()

        threading.Thread(target=work, daemon=True).start()

    def _make_venv(self, base: str) -> bool:
        vpy = pu.venv_python()
        if not Path(vpy).is_file():
            vdir = pu.venv_dir()
            vdir.parent.mkdir(parents=True, exist_ok=True)
            self.logAppended.emit(f'$ {base} -m venv {vdir}\n')
            if not pu._runs(base, ['-m', 'venv', str(vdir)]):
                self.logAppended.emit('venv creation failed\n')
                return False
        ver = pu._ver_tuple(pu._python_version(vpy))
        pkgs = ['lz4', 'capstone', 'fonttools', 'nsz']
        if ver < (3, 14):
            pkgs.insert(3, 'backports.zstd')
        self.logAppended.emit(f'$ {vpy} -m pip install {" ".join(pkgs)}\n')
        try:
            p = subprocess.Popen([vpy, '-m', 'pip', 'install'] + pkgs, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, errors='replace',
                                 env=pu.child_env(), **pu.no_window_kwargs())
            assert p.stdout is not None
            for line in p.stdout:
                self.logAppended.emit(line)
            p.wait()
            return p.returncode == 0
        except OSError as e:
            self.logAppended.emit(f'{e}\n')
            return False

    # ---- inputs

    def scan_game_dir(self, d: str) -> None:
        """Pick the four inputs out of a folder (and its subfolders, one level): a base NSP,
        an update, DLCs and prod.keys, by the naming the dumps use."""
        self.game_dir = d
        root = Path(d)
        if not root.is_dir():
            return
        files: list[Path] = []
        for p in sorted(root.iterdir()):
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files += [q for q in sorted(p.iterdir()) if q.is_file()]
        self.keys_path = next((str(f) for f in files if f.name.lower() == 'prod.keys'), self.keys_path)
        nsps = [f for f in files if f.suffix.lower() in ('.nsp', '.xci', '.nsz', '.xcz')]
        updates = [f for f in nsps if '[upd]' in f.name.lower() or 'update' in f.name.lower()]
        dlcs = [f for f in nsps if '[dlc]' in f.name.lower() or 'addon' in f.name.lower()]
        bases = [f for f in nsps if f not in updates and f not in dlcs]
        self.base_path = str(bases[0]) if bases else ''
        self.update_path = str(updates[0]) if updates else ''
        self.dlc_paths = [str(f) for f in dlcs]
        self.repoChanged.emit()

    @property
    def can_build(self) -> bool:
        return (self.repo_ok and bool(self.base_path) and bool(self.keys_path)
                and self.all_deps_ok and not self.running)

    # ---- build

    def start_build(self) -> None:
        if self.running:
            return
        if not self.repo_ok:
            self.finished.emit(False, self.t('msg.repoInvalidEmpty'))
            return
        py = self.python_path or ('python' if pu.IS_WIN else '/usr/bin/python3')
        base_dir = str(Path(self.base_path).parent)
        all_files = [self.base_path, self.update_path] + self.dlc_paths
        dirs = {str(Path(f).parent) for f in all_files if f}

        staging: str | None = None
        input_dir = base_dir
        if len(dirs) > 1:
            # files from different folders: a staging folder of links so the script sees one folder
            staging = tempfile.mkdtemp(prefix='nspb-stage-')
            linked = 0
            for f in all_files:
                if not f:
                    continue
                dst = Path(staging, Path(f).name)
                try:
                    os.link(f, dst) if not pu.IS_WIN else shutil.copy2(f, dst)
                    linked += 1
                except OSError:
                    try:
                        shutil.copy2(f, dst)
                        linked += 1
                    except OSError:
                        pass
            if linked == 0:
                self.finished.emit(False, self.t('msg.stagingFailed'))
                return
            input_dir = staging

        tid = self._title_id(self.base_path)
        tid_hex = f'{tid:016X}' if tid else 'game'
        work_dir = str(Path(self.out_dir or base_dir, f'{tid_hex}_build'))

        compressed = any(Path(f).suffix.lower() in ('.nsz', '.xcz')
                         for f in all_files if f)
        if compressed and not pu._runs(py, ['-c', 'import nsz']):
            self.logAppended.emit(self.t('msg.installingNsz') + '\n')
            if not pu._runs(py, ['-m', 'pip', 'install', 'nsz']):
                self.finished.emit(False, self.t('msg.nszFailed', py))
                return

        args = [str(Path(self.repo_path, 'scripts', 'build_ipa_from_nsp.py')),
                input_dir, '-k', self.keys_path, '--progress', 'lines']
        has_work_dir = self.supports_work_dir()
        if has_work_dir:
            args += ['--work-dir', work_dir]
        else:
            self.logAppended.emit(self.t('msg.noWorkDir') + '\n')
        if self.out_dir:
            args += ['-o', str(Path(self.out_dir, f'{tid_hex}.ipa'))]
        self.effective_work_dir = work_dir if has_work_dir else str(Path(input_dir, f'{tid_hex}_build'))

        self.running = True
        self.runningChanged.emit(True)
        self.stages = []
        self.log_tail = ''
        self.stagesChanged.emit()
        self.logAppended.emit(self.t('msg.running', py + ' ' + ' '.join(args)) + '\n')

        env = pu.child_env()
        droot = pu.dotnet_root(self.dotnet_path) if self.dotnet_ok else None
        if droot:
            env['DOTNET_ROOT'] = droot
            env['DOTNET_ROOT_ARM64'] = droot

        def work() -> None:
            ok = False
            try:
                self._proc = subprocess.Popen([py] + args, cwd=self.repo_path,
                                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                              text=True, errors='replace', bufsize=1, env=env,
                                              **pu.no_window_kwargs())
                assert self._proc.stdout is not None
                for line in self._proc.stdout:
                    self._on_line(line.rstrip('\n'))
                self._proc.wait()
                ok = self._proc.returncode == 0
            except OSError as e:
                self.logAppended.emit(f'{e}\n')
            finally:
                self._proc = None
            self._flush_lines()
            self.running = False
            self.runningChanged.emit(False)
            if ok:
                self.pack_archive()
            else:
                if self.stages:
                    self.stages[-1].state = 'failed'
                    self.stagesChanged.emit()
                self.finished.emit(False, self.t('msg.buildFailed'))
            if staging:
                shutil.rmtree(staging, ignore_errors=True)

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    def cancel_build(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    # ---- the script's own progress lines

    def _on_line(self, line: str) -> None:
        """Feed one line of the build's output: stage lines move the stage list, everything
        else goes to the log (which is what the window shows)."""
        self.logAppended.emit(line + '\n')
        if line.startswith('output IPA:'):
            self.ipa_path = line.split(':', 1)[1].strip()
        low = line.lower()
        for st in self.stages:
            if st.state == 'running':
                st.detail = line[:120]
                break
        if '[' in line and ']' in line:
            head = line[:line.find(']') + 1]
            if '/' in head:
                name = line[line.find(']') + 1:].strip()
                if name:
                    if self.stages and self.stages[-1].state == 'running':
                        self.stages[-1].state = 'done'
                    self.stages.append(Stage(name=name, state='running'))
                    self.stagesChanged.emit()
        del low

    def _flush_lines(self) -> None:
        self._line_buf = ''

    # ---- the archive step (what makes a 16 GB game installable)

    def pack_archive(self) -> None:
        work = getattr(self, 'effective_work_dir', '')
        extract = Path(work, 'extract')
        versions = []
        if extract.is_dir():
            for d in sorted(extract.iterdir()):
                if d.is_dir() and d.name.startswith('v') and (d / 'RomFS').is_dir():
                    try:
                        versions.append((int(d.name[1:]), d))
                    except ValueError:
                        pass
        if not versions:
            self.finished.emit(True, self.t('msg.archiveSkipped', str(extract)))
            return
        romfs = str(versions[-1][1] / 'RomFS')
        dest = str(Path(self.out_dir or Path(self.base_path).parent, 'romfs'))
        self.stages.append(Stage(name=self.t('prog.archiveShort'), state='running'))
        self.stagesChanged.emit()

        def work_() -> None:
            args = [self.python_path, str(Path(self.repo_path, 'dm', 'tools', 'romfs_arc.py')),
                    'pack', romfs, str(Path(dest, 'romfs')), '--shard-mib', '200']
            env = pu.child_env({'PYTHONPATH': str(Path(self.repo_path, 'dm', 'tools'))})
            ok = True
            try:
                p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, errors='replace', env=env,
                                     **pu.no_window_kwargs())
                assert p.stdout is not None
                for line in p.stdout:
                    self.logAppended.emit(line)
                p.wait()
                ok = p.returncode == 0
            except OSError as e:
                self.logAppended.emit(f'{e}\n')
                ok = False
            if self.stages:
                self.stages[-1].state = 'done' if ok else 'failed'
            self.archive_path = dest if ok else ''
            self.stagesChanged.emit()
            self.finished.emit(ok, '' if ok else self.t('msg.archiveFailed'))

        threading.Thread(target=work_, daemon=True).start()

    @staticmethod
    def _title_id(nsp: str) -> int | None:
        """The title ID from a dump's file name: the 16 hex digits in [0100…], which every
        dumper puts there."""
        import re
        m = re.search(r'\[([0-9A-Fa-f]{16})\]', Path(nsp).name)
        if not m:
            return None
        try:
            return int(m.group(1), 16)
        except ValueError:
            return None

"""Windows toolchain discovery for the iOS cross build.

Every Apple tool the upstream pipeline calls has a Windows stand-in; this module finds them,
checks that they are the version we pinned, and proves they actually work by compiling
something and reading the Mach-O magic back. Nothing here trusts a path simply because it
exists: `probe_*` functions run the tool and inspect its output.

Search order for every component is the same three levels, so a user can always fix a bad
auto-detection without editing code:

1. an environment variable (`NSPB_LLVM_DIR`, `NSPB_IOS_SDK`, `NSPB_METAL_DIR`, ...)
2. `toolchain.json` inside the app's data folder (`%LOCALAPPDATA%\\NS Port Builder\\`)
3. well-known install locations

The pinned versions below are the ones the Windows port was validated against. A different
version is accepted (toolchains move fast) but reported as `warn`, never silently: `check_all`
turns a mismatch into a message that names the pinned number.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# The package constants are duplicated rather than imported: `shim.py` loads this module from a
# generated `sitecustomize.py`, where there is no package context, and a relative import would
# fail there. `tests/test_win.py` asserts the two copies stay equal.
IOS_DEPLOYMENT = '26.0'
ENV_TOOLCHAIN = 'NSPB_TOOLCHAIN_JSON'
ENV_LLVM = 'NSPB_LLVM_DIR'
ENV_SDK = 'NSPB_IOS_SDK'
ENV_METAL = 'NSPB_METAL_DIR'

# ---------------------------------------------------------------- pinned versions

#: LLVM-MinGW release the port was validated with (LLVM 23.1.4). x86-64 only: Windows-on-ARM
#: devices are rare enough that a second 186 MB download (and the packaging that goes with it)
#: is not worth carrying. The target is iOS arm64 either way — this is the host architecture.
LLVM_MINGW_VERSION = '20261020'
LLVM_MINGW_LLVM = '23.1.4'
LLVM_MINGW_ASSETS = {
    'AMD64': {
        'name': f'llvm-mingw-{LLVM_MINGW_VERSION}-ucrt-x86_64.zip',
        'sha256': 'fd5462b7f5d93b2ff981fcd3f9c7e427e47f3203c64ea91c27bcc444eebd74cd',
        'size': 190612575,
    },
}
LLVM_MINGW_RELEASE_URL = ('https://github.com/mstorsjo/llvm-mingw/releases/download/'
                          + LLVM_MINGW_VERSION)

#: PortableGit, for a machine with no git at all. This is not a build requirement — the build
#: only needs it to fetch the repository — but a Windows user who has never installed git should
#: not have to leave the app. The .7z.exe is a self-extracting archive: running it with
#: -o<dir> -y unpacks without an installer and without administrator rights. Sizes and hashes are
#: pinned; a mismatch stops rather than unpacking a partial tree.
GIT_VERSION = '2.56.0.4'
GIT_ASSETS = {
    'AMD64': {
        'name': f'PortableGit-{GIT_VERSION}-64-bit.7z.exe',
        'sha256': 'b1f3e52216e2ed6882d1bebfd4d3fdf319bec40d2edbbf9fd26ec4fd3fce7ed1',
        'size': 60087472,   # measured from the published asset; a guess here fails the length check
    },
}
# The tag is v<version>.windows.<n>, and GIT_VERSION already carries the patch number after the
# last dot, so the tag is v2.56.0.windows.4 for GIT_VERSION 2.56.0.4 — spelled out here because
# deriving it from GIT_VERSION would need to know which part is the Windows build number.
GIT_RELEASE_TAG = 'v2.56.0.windows.4'
GIT_RELEASE_URL = f'https://github.com/git-for-windows/git/releases/download/{GIT_RELEASE_TAG}'


def bundled_tools_dir() -> Path:
    """Where the app keeps tools it downloaded for itself.

    A frozen build runs from a directory PyInstaller made; `sys._MEIPASS` is that directory
    (`<app>/_internal` on Windows). A source run uses the frontend-qt folder. Either way this is
    the same base that fetch.install_llvm unpacks into, which is what keeps the installer and the
    detector looking at one place.
    """
    base = getattr(sys, '_MEIPASS', None)
    if base:
        return Path(base) / '.tools'
    return Path(__file__).resolve().parents[2] / '.tools'


def git_dir() -> Path:
    """Where the app keeps its own PortableGit, if it downloaded one."""
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / \
        'NS Port Builder' / 'git'


def git_exe() -> Path | None:
    """The git to use: the app's own PortableGit first, then a system install."""
    local = git_dir() / 'cmd' / 'git.exe'
    if local.is_file():
        return local
    for c in (Path(r'C:\Program Files\Git\cmd\git.exe'),
              Path(r'C:\Program Files\Git\bin\git.exe'),
              Path(r'C:\Program Files (x86)\Git\cmd\git.exe')):
        if c.is_file():
            return c
    found = shutil.which('git')
    return Path(found) if found else None

#: The iPhoneOS SDK we pin. `xybp888/iOS-SDKs` is a plain git repository of SDK trees, so a
#: shallow clone is enough and the commit SHA pins the content. 26.0 is what `dm/ios/project.yml`
#: targets; 26.5 is accepted too, since a newer SDK still compiles against 26.0.
SDK_REPO = 'https://github.com/xybp888/iOS-SDKs'
SDK_PINNED = 'iPhoneOS26.0.sdk'
SDK_ACCEPTED = ('iPhoneOS26.0.sdk', 'iPhoneOS26.1.sdk', 'iPhoneOS26.2.sdk', 'iPhoneOS26.3.sdk',
                'iPhoneOS26.4.sdk', 'iPhoneOS26.4.1.sdk', 'iPhoneOS26.5.sdk')
#: Commit of `xybp888/iOS-SDKs` the pinned SDK was read from. Informational: the SDK tree is
#: verified by its own layout and a caller-supplied hash, not by trusting this number.
SDK_PINNED_COMMIT = '17eb9152ba9779b27427016472758824a8fcd6a7'

#: Metal Developer Tools for Windows, which Apple ships as a separate download (free Apple ID).
METAL_TOOLS_URL = 'https://developer.apple.com/download/all/?q=metal%20developer%20tools'
#: Version the port was validated with. The tool prints its own version, so this is a hint only.
METAL_TOOLS_VERSION = '6.2'

#: Environment variable carrying an expected SDK digest, for users who verify downloads.
ENV_SDK_SHA = 'NSPB_IOS_SDK_SHA256'

MACHO_MAGIC_64 = 0xFEEDFACF
MH_EXECUTE = 2
CPU_TYPE_ARM64 = 0x0100000C
PLATFORM_IOS = 2


# ---------------------------------------------------------------- results

@dataclass
class Probe:
    """One component's verdict, in the shape the dependency panel wants.

    `state` is `ok` / `missing` / `wrong`: `wrong` means found but unusable (a stripped LLD with
    no Mach-O driver, an SDK without stubs), which needs a different message than "not found".
    """
    id: str
    name: str
    state: str
    detail: str = ''
    hint: str = ''
    path: str = ''
    version: str = ''
    pinned: str = ''
    required: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.state == 'ok'


# ---------------------------------------------------------------- configuration

def config_path() -> Path:
    """`toolchain.json` in the app's data folder (shared with the venv location)."""
    base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    return base / 'NS Port Builder' / 'toolchain.json'


def load_config() -> dict:
    """The user's `toolchain.json`; an unreadable one is reported, never fatal.

    A broken config file must not stop the doctor from telling the user what is wrong, so a
    parse error comes back as `_error` and every lookup falls through to auto-detection.
    """
    p = Path(os.environ.get(ENV_TOOLCHAIN) or config_path())
    try:
        text = p.read_text(encoding='utf-8')
    except FileNotFoundError:
        return {}
    except OSError as e:
        return {'_error': f'{p}: {e}'}
    try:
        data = json.loads(text)
    except ValueError as e:
        return {'_error': f'{p}: {e}'}
    return data if isinstance(data, dict) else {'_error': f'{p}: not a JSON object'}


def setting(key: str, default: str | None = None) -> str | None:
    """A configured value: `NSPB_<KEY>` in the environment, else `toolchain.json`, else default."""
    v = os.environ.get('NSPB_' + key.upper())
    if v:
        return v
    v = load_config().get(key)
    return v if isinstance(v, str) and v else default


def _first_existing(cands: list[os.PathLike | str | None]) -> Path | None:
    for c in cands:
        if not c:
            continue
        p = Path(c)
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------- LLVM

def llvm_dir() -> Path | None:
    """The LLVM-MinGW root (the folder holding `bin/clang.exe`).

    A plain `LLVM-*-win64.exe` install works too: LLVM's own packaging keeps `bin/` in the same
    place. Both are accepted because the CMake-provided installer is what most people already
    have, and the only thing we need from it is clang plus a Mach-O-capable lld.
    """
    cands: list[Path | str | None] = [setting('llvm_dir'), os.environ.get(ENV_LLVM)]
    for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
        if not base:
            continue
        cands += sorted(glob.glob(os.path.join(base, 'LLVM')), reverse=True)
        cands += sorted(glob.glob(os.path.join(base, 'llvm-mingw*')), reverse=True)
    for base in (os.environ.get('LOCALAPPDATA'),):
        if base:
            cands += sorted(glob.glob(os.path.join(base, 'Programs', 'LLVM')), reverse=True)
            cands += sorted(glob.glob(os.path.join(base, 'llvm-mingw*')), reverse=True)
    # the app's own download location first: install_llvm() unpacks under
    # <app>/_internal/.tools, and without this the freshly installed toolchain was invisible to
    # the next dependency check (the report: "installed, then Check again changed nothing").
    cands.insert(0, bundled_tools_dir() / f'llvm-mingw-{LLVM_MINGW_VERSION}')
    # a clang already on PATH, if it came from a toolchain with lld beside it
    if w := shutil.which('clang'):
        cands.append(Path(w).parent.parent)
    root = _first_existing(cands)
    if root and (root / 'bin' / 'clang.exe').is_file():
        return root
    if root and (root / 'bin').is_dir():
        return root          # let the probe decide: a root without clang reports `wrong`
    return None


def llvm_tool(name: str) -> Path | None:
    """One tool from the LLVM bin folder, with the `.exe` the Windows builds use."""
    root = llvm_dir()
    if root:
        for n in (f'{name}.exe', name):
            p = root / 'bin' / n
            if p.is_file():
                return p
    if w := shutil.which(name):
        return Path(w)
    if w := shutil.which(f'{name}.exe'):
        return Path(w)
    return None


def ld64_lld() -> Path | None:
    """The Mach-O linker, `ld64.lld`.

    **This is the one real gap in llvm-mingw.** Its release zip runs `strip-llvm.sh`, which
    deletes `ld64.lld*` (see the upstream script, line 57: the `for i in ... ld64.lld* ...`
    removal list). What remains is `ld.lld.exe`, and that single binary contains every LLD
    driver, selecting one from `argv[0]` — so a copy named `ld64.lld.exe` *is* the Mach-O
    linker. `ensure_ld64_lld` makes that copy; if the environment already has a real
    `ld64.lld.exe` (LLVM's own installer ships one) it is used as is.
    """
    root = llvm_dir()
    for base in ([root / 'bin'] if root else []) + [Path(p) for p in os.environ.get('PATH', '').split(os.pathsep) if p]:
        for n in ('ld64.lld.exe', 'ld64.lld'):
            p = base / n
            if p.is_file():
                return p
    return None


def ensure_ld64_lld() -> tuple[Path | None, str]:
    """Find or create `ld64.lld.exe`; returns (path, note).

    On Windows a hard link or copy is enough because LLD picks its driver from the file name.
    The copy is only made when `ld.lld.exe` reports Mach-O support, so a stripped build fails
    here with a message instead of at link time with undefined symbols.
    """
    if p := ld64_lld():
        return p, ''
    src = llvm_tool('ld.lld')
    if not src:
        return None, ('neither ld64.lld.exe nor ld.lld.exe is in the LLVM folder: '
                      'install LLVM-MinGW (it ships ld.lld.exe, which becomes the Mach-O linker)')
    if not _lld_has_macho(src):
        return None, (f'{src} has no Mach-O driver (it was stripped down to ELF): install '
                      'LLVM-MinGW 20261020 or the official LLVM Windows build')
    dst = src.with_name('ld64.lld.exe')
    try:
        if not dst.exists():
            try:
                os.link(src, dst)       # same volume, no extra space
            except OSError:
                shutil.copy2(src, dst)  # different volume or a filesystem without hard links
    except OSError as e:
        return None, f'cannot create {dst} from {src}: {e}'
    return dst, f'created {dst.name} from {src.name} (LLD selects the Mach-O driver by file name)'


def _lld_has_macho(exe: Path) -> bool:
    """Whether this LLD binary carries the Mach-O driver.

    A stripped `ld.lld.exe` is still a working ELF linker, so running it proves nothing. The
    driver table's strings are the only cheap signal, and the reference implementation relied
    on the same property (every LLD build always contains all drivers unless stripped).
    """
    try:
        data = exe.read_bytes()
    except OSError:
        return False
    return b'MachO' in data and b'ld64.lld' in data


def llvm_version(clang: Path) -> str:
    """clang's version line, or '' when it does not run."""
    try:
        r = subprocess.run([str(clang), '--version'], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ''
    if r.returncode != 0:
        return ''
    m = re.search(r'clang version (\d+\.\d+\.\d+)', r.stdout)
    return m.group(1) if m else (r.stdout.splitlines() or [''])[0].strip()


# ---------------------------------------------------------------- iPhoneOS SDK

def _sdk_candidates() -> list[Path]:
    cands: list[Path] = []
    for raw in (setting('ios_sdk'), os.environ.get(ENV_SDK)):
        if raw:
            cands.append(Path(raw))
    # what sdk_fetch.py downloads into
    cache = sdk_cache_dir()
    for name in SDK_ACCEPTED:
        cands.append(cache / name)
    if cache.is_dir():
        cands += sorted((p for p in cache.glob('iPhoneOS*.sdk') if p.is_dir()), reverse=True)
    # a folder the user pointed at by hand, holding the .sdk one level down
    for raw in (setting('ios_sdk'), os.environ.get(ENV_SDK)):
        if raw and Path(raw).is_dir():
            cands += sorted((p for p in Path(raw).glob('iPhoneOS*.sdk') if p.is_dir()), reverse=True)
    return cands


def sdk_cache_dir() -> Path:
    base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    return base / 'NS Port Builder' / 'sdks'


def ios_sdk() -> Path | None:
    """The `iPhoneOS<ver>.sdk` folder: a directory with `SDKSettings.json` and stub libraries.

    Accepting only a folder that looks like an SDK keeps a stale or half-extracted download from
    being reported as `ok` and then failing deep inside the build.
    """
    for p in _sdk_candidates():
        if is_sdk_dir(p):
            return p
    return None


def is_sdk_dir(p: os.PathLike | str) -> bool:
    """Whether `p` is an iPhoneOS SDK root we can compile and link against."""
    d = Path(p)
    try:
        if not d.is_dir():
            return False
        if not (d / 'SDKSettings.json').is_file() and not (d / 'SDKSettings.plist').is_file():
            return False
        # the SDK must carry at least the UIKit stub: without stubs nothing links
        fw = d / 'System' / 'Library' / 'Frameworks'
        if not fw.is_dir():
            return False
        return any((fw / n).exists() for n in ('UIKit.framework', 'Foundation.framework'))
    except OSError:
        return False


def sdk_version(sdk: Path) -> tuple[str, str]:
    """(version, build) of an SDK folder, from SDKSettings and the SystemVersion plist."""
    ver = build = ''
    js = Path(sdk) / 'SDKSettings.json'
    if js.is_file():
        try:
            ver = str(json.loads(js.read_text(encoding='utf-8')).get('Version') or '')
        except (OSError, ValueError):
            pass
    if not ver:
        pl = Path(sdk) / 'SDKSettings.plist'
        if pl.is_file():
            try:
                import plistlib
                with open(pl, 'rb') as f:
                    ver = str(plistlib.load(f).get('Version') or '')
            except Exception:
                pass
    sv = Path(sdk) / 'System' / 'Library' / 'CoreServices' / 'SystemVersion.plist'
    if sv.is_file():
        try:
            import plistlib
            with open(sv, 'rb') as f:
                build = str(plistlib.load(f).get('ProductBuildVersion') or '')
        except Exception:
            pass
    return ver, build


def sdk_major(ver: str) -> int:
    try:
        return int(str(ver).split('.')[0])
    except (TypeError, ValueError):
        return 0


def sdk_tree_digest(sdk: Path, limit: int = 4_000_000) -> str:
    """A stable digest of an SDK's identity: its version plus the headers' and stubs' sizes.

    A full SHA-256 over a 2 GB tree takes minutes and would run on every app start, so this
    digests the metadata that actually changes between SDK releases. It is meant to tell two
    SDKs apart (26.0 vs 26.5), not to prove byte equality of a download.
    """
    h = hashlib.sha256()
    ver, build = sdk_version(sdk)
    h.update(f'{ver}\0{build}\0'.encode())
    n = 0
    for root, dirs, files in os.walk(sdk):
        dirs.sort()
        for f in sorted(files):
            if not f.endswith(('.tbd', '.h', '.modulemap', '.json', '.plist')):
                continue
            p = Path(root) / f
            try:
                st = p.stat()
            except OSError:
                continue
            h.update(f'{p.relative_to(sdk).as_posix()}\0{st.st_size}\0'.encode())
            n += 1
            if n >= limit:
                return h.hexdigest()
    return h.hexdigest()


# ---------------------------------------------------------------- Metal

def metal_dir() -> Path | None:
    """Metal Developer Tools for Windows root (it holds `bin/metal.exe`, or `ios/` + `macos/`)."""
    cands: list[Path | str | None] = [setting('metal_dir'), os.environ.get(ENV_METAL)]
    for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
        if base:
            cands += sorted(glob.glob(os.path.join(base, 'Metal Developer Tools*')), reverse=True)
    root = _first_existing(cands)
    if root is None:
        return None
    # 4.x shipped one toolchain per OS in ios/ and macos/; 5.x and 6.x ship one bin/ for every
    # target. Point at whichever folder actually holds metal.exe.
    if (root / 'bin' / 'metal.exe').is_file() or (root / 'ios' / 'bin' / 'metal.exe').is_file():
        return root
    return root


def metal_tool(name: str, sdk: str = 'iphoneos') -> Path | None:
    """`metal.exe` / `metallib.exe` for one SDK family.

    `metal-tt` is deliberately **not** looked up: the Windows tools do not ship it, so the
    pipeline's offline pipeline archive (`pso_offline.py`) cannot run here. `metal_tool` returning
    None for it is what makes `driver.py` switch that step off with a clear message.
    """
    root = metal_dir()
    if root is None:
        return None
    sub = 'ios' if sdk.startswith('iphone') else 'macos'
    pats = (f'{sub}/bin/{name}.exe', f'{sub}/**/bin/{name}.exe', f'**/{sub}/**/{name}.exe',
            f'bin/{name}.exe', f'**/bin/{name}.exe')
    for pat in pats:
        hits = sorted(glob.glob(str(root / pat), recursive=True))
        if hits:
            return Path(hits[0])
    return None


def metal_version() -> str:
    m = metal_tool('metal')
    if not m:
        return ''
    try:
        r = subprocess.run([str(m), '--version'], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ''
    text = (r.stdout or '') + (r.stderr or '')
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), '')
    return line


# ---------------------------------------------------------------- cross-platform tools

def find_exe(name: str) -> Path | None:
    """A Windows build of a cross-platform tool (spirv-cross, zstd, glslangValidator).

    `toolchain.json` may name the folder (`spirv_cross_dir`), because the Vulkan SDK does not
    put its `Bin` on PATH by default.
    """
    d = setting(name.replace('-', '_') + '_dir')
    if d:
        for cand in (Path(d) / f'{name}.exe', Path(d) / 'Bin' / f'{name}.exe', Path(d) / name):
            if cand.is_file():
                return cand
    for cand in (f'{name}.exe', name):
        if w := shutil.which(cand):
            return Path(w)
    return None


def python_exe() -> str:
    return sys.executable


def std_font() -> Path | None:
    """A TTF with broad Unicode coverage, for the shared-font stand-in (`standard.ttf`).

    Upstream copies macOS's Arial Unicode. On Windows the closest system font is Arial Unicode
    MS when Office installed it, else Arial; both are accepted, and a game whose text needs
    CJK glyphs looks noticeably worse with plain Arial (documented in the README).
    """
    fonts = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
    return _first_existing([setting('std_font'), fonts / 'ARIALUNI.TTF', fonts / 'arialuni.ttf',
                            fonts / 'msyh.ttc', fonts / 'arial.ttf'])


def letter_font() -> Path | None:
    """A bold face used to draw the button icons (`nintendo_ext.ttf`)."""
    fonts = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
    return _first_existing([setting('letter_font'), fonts / 'ARLRDBD.TTF',
                            fonts / 'arialbd.ttf', fonts / 'arial.ttf'])


# ---------------------------------------------------------------- the real probes

def probe_compile(sdk: Path, clang: Path | None = None) -> tuple[bool, str]:
    """Compile a trivial ObjC file for the device and check the object is arm64 Mach-O.

    This is the check that makes the dependency panel trustworthy: a folder that merely looks
    like an SDK, or a clang without the AArch64 backend, fails here instead of twenty minutes
    into a build.
    """
    clang = clang or llvm_tool('clang')
    if not clang:
        return False, 'no clang.exe'
    src = '#import <Foundation/Foundation.h>\nint dm_probe(void) { return 42; }\n'
    with tempfile.TemporaryDirectory(prefix='nspb-probe-') as td:
        c = Path(td) / 'probe.m'
        o = Path(td) / 'probe.o'
        c.write_text(src, encoding='utf-8')
        cmd = [str(clang), '-target', f'arm64-apple-ios{IOS_DEPLOYMENT}', '-isysroot', str(sdk),
               '-fobjc-arc', '-c', str(c), '-o', str(o)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            return False, 'clang timed out on the probe'
        except OSError as e:
            return False, f'cannot run {clang}: {e}'
        if r.returncode != 0:
            tail = ((r.stderr or r.stdout or '').strip().splitlines() or ['no output'])[-1]
            return False, f'clang refused the probe: {tail[:300]}'
        try:
            head = o.read_bytes()[:32]
        except OSError as e:
            return False, f'clang wrote no object: {e}'
        if len(head) < 32:
            return False, 'clang wrote a truncated object'
        magic, cputype, _sub, filetype = struct.unpack_from('<IIII', head, 0)
        if magic != MACHO_MAGIC_64:
            return False, f'object magic 0x{magic:08x} is not 64-bit Mach-O (0xfeedfacf)'
        if cputype != CPU_TYPE_ARM64:
            return False, f'object cputype 0x{cputype:08x} is not arm64'
        if filetype != 1:   # MH_OBJECT
            return False, f'object filetype {filetype} is not MH_OBJECT'
        return True, f'arm64 Mach-O object, {o.stat().st_size} bytes'


def probe_metal(sdk: Path) -> tuple[bool, str]:
    """Compile a trivial MSL shader to AIR and then to a .metallib with the Windows tools."""
    metal = metal_tool('metal')
    metallib = metal_tool('metallib')
    if not metal or not metallib:
        return False, 'metal.exe and metallib.exe are not both present'
    src = ('#include <metal_stdlib>\nusing namespace metal;\n'
           'vertex float4 dm_probe_v(uint vid [[vertex_id]]) { return float4(0, 0, 0, 1); }\n')
    with tempfile.TemporaryDirectory(prefix='nspb-metal-') as td:
        m = Path(td) / 'probe.metal'
        a = Path(td) / 'probe.air'
        lib = Path(td) / 'probe.metallib'
        m.write_text(src, encoding='utf-8')
        tgt = f'air64-apple-ios{sdk_major(sdk_version(sdk)[0]) or IOS_DEPLOYMENT.split(".")[0]}.0'
        for cmd, what in (([str(metal), '-target', tgt, '-c', str(m), '-o', str(a)], 'metal'),
                          ([str(metallib), str(a), '-o', str(lib)], 'metallib')):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                                   cwd=td)
            except subprocess.TimeoutExpired:
                return False, f'{what} timed out'
            except OSError as e:
                return False, f'cannot run {cmd[0]}: {e}'
            if r.returncode != 0:
                tail = ((r.stderr or r.stdout or '').strip().splitlines() or ['no output'])[-1]
                return False, f'{what} failed: {tail[:300]}'
        if not lib.is_file() or lib.stat().st_size == 0:
            return False, 'metallib wrote no output (empty library)'
        return True, f'{lib.stat().st_size} byte metallib for {tgt}'


def probe_link(sdk: Path) -> tuple[bool, str]:
    """Link a tiny executable for iOS and check it is an arm64 MH_EXECUTE with an iOS platform.

    Only the linker and the SDK's stubs are exercised, not the game's own code: an undefined
    symbol deep in a huge embed section would be a real bug, not a toolchain check.
    """
    clang = llvm_tool('clang')
    lld, note = ensure_ld64_lld()
    if not clang:
        return False, 'no clang.exe'
    if not lld:
        return False, note or 'no ld64.lld'
    src = '#include <stdio.h>\nint main(void) { puts("probe"); return 0; }\n'
    with tempfile.TemporaryDirectory(prefix='nspb-link-') as td:
        c = Path(td) / 'probe.c'
        out = Path(td) / 'probe'
        c.write_text(src, encoding='utf-8')
        cmd = [str(clang), '-target', f'arm64-apple-ios{IOS_DEPLOYMENT}', '-isysroot', str(sdk),
               '-fuse-ld=lld', '-o', str(out), str(c)]
        # clang finds ld64.lld by name; give it the folder we created the copy in
        env = dict(os.environ)
        env['PATH'] = str(lld.parent) + os.pathsep + env.get('PATH', '')
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
        except subprocess.TimeoutExpired:
            return False, 'link timed out'
        except OSError as e:
            return False, f'cannot run clang: {e}'
        if r.returncode != 0:
            tail = ((r.stderr or r.stdout or '').strip().splitlines() or ['no output'])[-1]
            return False, f'link failed: {tail[:300]}'
        try:
            data = out.read_bytes()
        except OSError as e:
            return False, f'no executable written: {e}'
        if len(data) < 32:
            return False, 'linker wrote a truncated file'
        magic, cputype, _sub, filetype = struct.unpack_from('<IIII', data, 0)
        if magic != MACHO_MAGIC_64 or cputype != CPU_TYPE_ARM64:
            return False, f'not an arm64 Mach-O executable (magic 0x{magic:08x})'
        if filetype != MH_EXECUTE:
            return False, f'filetype {filetype} is not MH_EXECUTE'
        plat = macho_platform(data)
        if plat is not None and plat != PLATFORM_IOS:
            return False, f'platform {plat} is not iOS ({PLATFORM_IOS})'
        return True, f'arm64 MH_EXECUTE{"" if plat is None else f", platform {plat}"}, {len(data)} bytes'


def macho_platform(data: bytes) -> int | None:
    """`LC_BUILD_VERSION`'s platform, or None when the binary has no such load command."""
    try:
        ncmds, _sizeofcmds = struct.unpack_from('<II', data, 16)
    except struct.error:
        return None
    off = 32
    for _ in range(ncmds):
        try:
            cmd, size = struct.unpack_from('<II', data, off)
        except struct.error:
            return None
        if cmd == 0x32:   # LC_BUILD_VERSION
            try:
                return struct.unpack_from('<I', data, off + 8)[0]
            except struct.error:
                return None
        if size < 8:
            return None
        off += size
    return None


# ---------------------------------------------------------------- the whole picture

def check_all(deep: bool = False) -> list[Probe]:
    """Every component, in the order the dependency panel shows them.

    `deep` adds the compile / link / Metal probes. They take a few seconds, so the panel runs
    them on a background thread; a shallow check is enough to say "not found" fast.
    """
    out: list[Probe] = []
    cfg = load_config()
    if '_error' in cfg:
        out.append(Probe('toolchain_json', 'toolchain.json', 'wrong', cfg['_error'],
                         'fix the JSON, or delete the file to fall back to auto-detection',
                         pinned='', required=False))

    # ---- LLVM
    root = llvm_dir()
    clang = llvm_tool('clang')
    if not root or not clang:
        out.append(Probe(
            'llvm', f'LLVM (clang {LLVM_MINGW_LLVM})', 'missing',
            'clang.exe not found', pinned=LLVM_MINGW_ASSETS['AMD64']['name'],
            extra={'download': LLVM_MINGW_ASSETS.get(_arch(), LLVM_MINGW_ASSETS['AMD64'])}))
    else:
        ver = llvm_version(clang)
        if ver:
            out.append(Probe('llvm', 'LLVM (clang)', 'ok', str(clang), path=str(root), version=ver,
                             pinned=LLVM_MINGW_LLVM))
        else:
            out.append(Probe('llvm', 'LLVM (clang)', 'wrong',
                             f'{clang} does not run (a partial or 32-bit install?)',
                             pinned=LLVM_MINGW_LLVM, path=str(root)))

    # ---- the Mach-O linker, which llvm-mingw does not ship under its own name
    lld, lld_note = ensure_ld64_lld()
    if lld:
        out.append(Probe('lld', 'ld64.lld (Mach-O linker)', 'ok', str(lld), hint=lld_note))
    else:
        out.append(Probe('lld', 'ld64.lld (Mach-O linker)', 'missing', lld_note or 'not found',
                         pinned='ships with LLVM as ld.lld.exe; renamed automatically'))

    # ---- the SDK
    sdk = ios_sdk()
    if not sdk:
        out.append(Probe('ios_sdk', f'iPhoneOS SDK {SDK_PINNED[:-4]}', 'missing',
                         'no iPhoneOS*.sdk folder',
                         hint='Download it in the app, or point toolchain.json "ios_sdk" at one',
                         pinned=SDK_PINNED))
    else:
        ver, build = sdk_version(sdk)
        maj = sdk_major(ver)
        if maj >= 26:
            out.append(Probe('ios_sdk', 'iPhoneOS SDK', 'ok', str(sdk), path=str(sdk),
                             version=f'{ver} {build}'.strip(), pinned=SDK_PINNED))
        else:
            out.append(Probe('ios_sdk', 'iPhoneOS SDK', 'wrong',
                             f'{sdk} is iOS {ver or "?"}; the app needs 26.0 or later (Metal 4)',
                             pinned=SDK_PINNED, path=str(sdk), version=ver))
        want = os.environ.get(ENV_SDK_SHA)
        if want:
            got = sdk_tree_digest(sdk)
            out.append(Probe('ios_sdk_sha', 'iPhoneOS SDK digest', 'ok' if got == want.lower() else 'wrong',
                             got if got == want.lower() else f'{got} (expected {want.lower()})',
                             required=False))

    # ---- Metal
    mroot = metal_dir()
    mv = metal_version() if mroot else ''
    metal_ok = bool(metal_tool('metal') and metal_tool('metallib'))
    if metal_ok:
        out.append(Probe('metal', 'Metal Developer Tools', 'ok', str(mroot), path=str(mroot),
                         version=mv, pinned=METAL_TOOLS_VERSION))
    else:
        out.append(Probe('metal', 'Metal Developer Tools', 'missing',
                         f'not found under {mroot}' if mroot else 'metal.exe / metallib.exe not found',
                         hint=METAL_TOOLS_URL, pinned=METAL_TOOLS_VERSION))
    # metal-tt is Apple-internal-only: report it so nobody expects the pipeline archive here
    out.append(Probe('metal_tt', 'metal-tt (pipeline archive)', 'ok' if metal_tool('metal-tt') else 'missing',
                     'available' if metal_tool('metal-tt') else
                     'not in the Windows Metal tools: the offline pipeline archive is disabled here',
                     required=False))

    # ---- the rest of the toolchain
    for name, label, hint, req in (
            ('spirv-cross', 'spirv-cross', 'Vulkan SDK for Windows (vulkan.lunarg.com), or a GitHub release', True),
            ('zstd', 'zstd', 'github.com/facebook/zstd/releases (zstd-*-win64.zip)', True),
            ('glslangValidator', 'glslangValidator', 'only OpenGL games need it (Vulkan SDK ships it)', False)):
        p = find_exe(name)
        out.append(Probe(name, label, 'ok' if p else 'missing', str(p or 'not found'),
                         hint=hint, required=req, path=str(p or '')))

    # ---- fonts
    f = std_font()
    out.append(Probe('std_font', 'standard font (STD_FONT)', 'ok' if f else 'missing', str(f or ''),
                     hint='any TTF with wide Unicode coverage', required=False, path=str(f or '')))

    if deep:
        if sdk and clang:
            ok, detail = probe_compile(sdk, clang)
            out.append(Probe('probe_compile', 'cross-compile probe', 'ok' if ok else 'wrong', detail))
            ok2, detail2 = probe_link(sdk)
            out.append(Probe('probe_link', 'cross-link probe', 'ok' if ok2 else 'wrong', detail2))
        if sdk and metal_ok:
            ok3, detail3 = probe_metal(sdk)
            out.append(Probe('probe_metal', 'Metal compile probe', 'ok' if ok3 else 'wrong', detail3))
    return out


def missing_required(probes: list[Probe]) -> list[Probe]:
    return [p for p in probes if p.required and not p.ok]


def _arch() -> str:
    """The llvm-mingw archive to use. Only x86-64 is published by this app.

    A Windows-on-ARM machine runs the x86-64 tools under emulation, which works but is slower;
    there is no ARM64 archive here on purpose (the device population is too small to justify a
    second 186 MB download). host_arch_note() says so in the dependency panel.
    """
    return 'AMD64'


def host_arch_note() -> str | None:
    """A line to show when the host is ARM64 and will run the x86-64 tools emulated."""
    if os.environ.get('PROCESSOR_ARCHITECTURE', '').upper() in ('ARM64', 'AARCH64'):
        return 'Windows on ARM: running the x86-64 toolchain under emulation (slower, works)'
    return None


def download_asset(arch: str | None = None) -> dict:
    a = LLVM_MINGW_ASSETS.get(arch or _arch(), LLVM_MINGW_ASSETS['AMD64'])
    return dict(a, url=f'https://github.com/mstorsjo/llvm-mingw/releases/download/'
                       f'{LLVM_MINGW_VERSION}/{a["name"]}')


def summary() -> str:
    """One line for the log: what was found, in the order it matters."""
    parts = []
    for p in check_all():
        if not p.required:
            continue
        mark = 'ok' if p.ok else p.state
        parts.append(f'{p.name}: {mark}{"" if not p.version else f" {p.version}"}')
    return '; '.join(parts)

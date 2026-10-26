"""Per-OS paths, tool discovery and process launching.

Everything the UI needs that differs between Windows and macOS lives here, so the model and
the window never branch on sys.platform themselves.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform.startswith('win')
IS_MAC = sys.platform == 'darwin'


# ---------------------------------------------------------------- tool discovery

def _which(name: str, extra: list[str] | None = None) -> str | None:
    """shutil.which plus a list of absolute candidates (a GUI launch does not inherit the
    shell's PATH on either OS, so the usual install locations are probed by hand)."""
    if found := shutil.which(name):
        return found
    for c in extra or []:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def find_python() -> tuple[str, bool, str]:
    """The interpreter to build with: (path, has_packages, version_or_empty).

    The build scripts need lz4, capstone, fontTools, zstd and (for compressed dumps) nsz. A
    system interpreter rarely has them, so the venv the app manages is checked first, then
    every python on the machine.
    """
    probe = (
        "import lz4, capstone, fontTools\n"
        "try:\n"
        "    from compression import zstd\n"
        "except ImportError:\n"
        "    from backports import zstd\n"
    )
    cands: list[str] = [venv_python()]
    if IS_WIN:
        cands += [
            os.path.expandvars(r'%LOCALAPPDATA%\Programs\Python\Python312\python.exe'),
            os.path.expandvars(r'%LOCALAPPDATA%\Programs\Python\Python311\python.exe'),
            os.path.expandvars(r'%ProgramFiles%\Python312\python.exe'),
        ]
    else:
        fw = '/Library/Frameworks/Python.framework/Versions'
        if Path(fw).is_dir():
            for v in sorted(os.listdir(fw), reverse=True):
                cands.append(f'{fw}/{v}/bin/python3')
        cands += ['/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/usr/bin/python3']
    if w := _which('python3' if not IS_WIN else 'python'):
        cands.append(w)

    fallback: tuple[str, str] | None = None
    seen: set[str] = set()
    for c in cands:
        if not c or c in seen or not Path(c).is_file():
            continue
        seen.add(c)
        ver = _python_version(c)
        if not ver or _ver_tuple(ver) < (3, 9):
            continue
        if _runs(c, ['-c', probe]):
            return (c, True, ver)
        if fallback is None:
            fallback = (c, ver)
    if fallback:
        return (fallback[0], False, fallback[1])
    return ('python' if IS_WIN else '/usr/bin/python3', False, '')


def _python_version(py: str) -> str:
    try:
        r = subprocess.run([py, '-c', 'import sys;print("%d.%d"%sys.version_info[:2])'],
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def _ver_tuple(v: str) -> tuple[int, int]:
    parts = v.split('.')
    try:
        return (int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):
        return (0, 0)


def _runs(exe: str, args: list[str]) -> bool:
    try:
        return subprocess.run([exe] + args, capture_output=True, timeout=120).returncode == 0
    except Exception:
        return False


def venv_dir() -> Path:
    if IS_WIN:
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    else:
        base = Path.home() / 'Library' / 'Application Support'
    return base / 'NS Port Builder' / 'venv'


def venv_python() -> str:
    v = venv_dir()
    return str(v / ('Scripts/python.exe' if IS_WIN else 'bin/python3'))


# ---------------------------------------------------------------- dotnet

def find_dotnet() -> tuple[str, bool]:
    cands = []
    if IS_WIN:
        cands += [r'C:\Program Files\dotnet\dotnet.exe',
                  os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\dotnet\dotnet.exe')]
    else:
        cands += [str(Path.home() / '.dotnet' / 'dotnet'),
                  '/usr/local/share/dotnet/dotnet',
                  '/opt/homebrew/bin/dotnet']
    path = _which('dotnet', cands) or ('dotnet.exe' if IS_WIN else 'dotnet')
    ok = _runs(path, ['--list-sdks'])
    return (path, ok)


def dotnet_root(dotnet: str) -> str | None:
    """The runtime root the apphost looks for, from `dotnet --list-runtimes`.

    A set-but-wrong DOTNET_ROOT is worse than none (the apphost stops searching), so this
    returns None when the derivation does not answer and the caller leaves the variable out —
    the build script derives and verifies its own in that case.
    """
    try:
        r = subprocess.run([dotnet, '--list-runtimes'], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return None
    except Exception:
        return None
    for ln in r.stdout.splitlines():
        if not ln.startswith('Microsoft.NETCore.App'):
            continue
        if '[' in ln and ']' in ln:
            p = ln[ln.rfind('[') + 1:ln.rfind(']')]
        else:
            continue
        suffix = os.sep + os.path.join('shared', 'Microsoft.NETCore.App')
        if p.endswith(suffix):
            return p[:-len(suffix)]
        if p:
            return p
    return None


# ---------------------------------------------------------------- external tools

def find_tool(name: str) -> str | None:
    """xcodegen / zstd / spirv-cross / metal, by the usual locations per OS."""
    if IS_WIN:
        extra = [rf'C:\Program Files\{name}\{name}.exe',
                 rf'C:\ProgramData\chocolatey\bin\{name}.exe']
        return _which(name + '.exe', extra)
    return _which(name, [f'/opt/homebrew/bin/{name}', f'/usr/local/bin/{name}'])


def metal_toolchain_ok() -> bool:
    """Whether a Metal compiler answers. On Windows that is Apple's Metal Developer Tools
    (metal.exe + metallib.exe); on macOS it is xcrun's."""
    if IS_WIN:
        return find_tool('metal') is not None and find_tool('metallib') is not None
    return _runs('/usr/bin/xcrun', ['-sdk', 'macosx', 'metal', '--version'])


def ios_sdk_ok() -> bool:
    if IS_WIN:
        # The Windows path uses an iPhoneOS SDK extracted from an archive, located by the
        # caller (the WebUI does the same); presence of the directory is the check.
        return bool(os.environ.get('IPHONEOS_SDK_DIR') and Path(os.environ['IPHONEOS_SDK_DIR']).is_dir())
    return _runs('/usr/bin/xcrun', ['--sdk', 'iphoneos', '--show-sdk-version'])


def xcode_ok() -> bool:
    if IS_WIN:
        return False        # Xcode is macOS-only; Windows uses the cross toolchain instead
    return Path('/Applications/Xcode.app').is_dir() and Path('/usr/bin/xcodebuild').is_file()


# ---------------------------------------------------------------- process helpers

def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment every child process gets: a PATH with the usual tool directories,
    HOME/USER present (a GUI launch can strip them), and DOTNET_CLI_HOME so .NET's first-run
    state has somewhere to go."""
    env = dict(os.environ)
    dirs = [env.get('PATH', '')]
    if IS_WIN:
        dirs += [r'C:\Program Files\dotnet', os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\dotnet')]
        sep = ';'
    else:
        dirs += ['/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin']
        sep = ':'
    env['PATH'] = sep.join(d for d in dirs if d)
    if not env.get('HOME') or not Path(env['HOME']).is_dir():
        env['HOME'] = str(Path.home())
    env.setdefault('USER', os.environ.get('USERNAME') or os.environ.get('USER') or 'user')
    env.setdefault('DOTNET_CLI_HOME', env['HOME'])
    if extra:
        env.update(extra)
    return env


def short_path(p: str) -> str:
    """Home shown as ~ (keeps the account name out of screenshots)."""
    home = str(Path.home())
    return '~' + p[len(home):] if p.startswith(home) else p


def no_window_kwargs() -> dict:
    """Hide the console window a child process would otherwise flash on Windows."""
    if IS_WIN:
        return {'creationflags': subprocess.CREATE_NO_WINDOW}
    return {}

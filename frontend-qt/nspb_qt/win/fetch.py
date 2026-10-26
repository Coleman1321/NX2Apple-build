"""Download the pinned Windows toolchain artefacts, verifying their SHA-256.

Only the LLVM-MinGW archive is fetched here. The iPhoneOS SDK is *not* downloaded as a binary
blob: `xybp888/iOS-SDKs` is a git repository, so `sdk_fetch.clone_sdk` uses git's own transfer
with integrity checks, and Apple's `Xcode.xip` route needs an Apple ID login that cannot be
scripted. `Metal Developer Tools for Windows` likewise needs an Apple ID, so it is a link the
app shows rather than a silent download of something Apple does not publish for redirect.

Every download is checked against a hash pinned in `toolchain.py`. A mismatch is a hard stop:
the archive is deleted rather than unpacked, because a partially-correct toolchain produces
build failures that look like source bugs.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

if __package__:
    from . import toolchain as tc
else:                                       # pragma: no cover - script mode
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from nspb_qt.win import toolchain as tc


class DownloadError(Exception):
    """A user-facing download failure with an actionable message."""


def download(url: str, dest: Path, sha256: str, size: int | None = None,
             log: Callable[[str], None] | None = None,
             progress: Callable[[int, int], None] | None = None) -> Path:
    """Fetch `url` into `dest`, verifying length and SHA-256.

    Downloads to a `.part` file and renames on success, so an interrupted download never looks
    like a usable archive on the next start.
    """
    log = log or (lambda s: None)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        got = sha256_of(dest)
        if got == sha256.lower():
            log(f'cached: {dest.name} ({got[:16]}…)')
            return dest
        log(f'{dest.name} has the wrong hash ({got[:16]}…): downloading again')
        dest.unlink()
    part = dest.with_suffix(dest.suffix + '.part')
    part.unlink(missing_ok=True)
    log(f'downloading {url}')
    h = hashlib.sha256()
    total = 0
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'NS-Port-Builder'})
        with urllib.request.urlopen(req, timeout=120) as r, open(part, 'wb') as f:
            expected = int(r.headers.get('Content-Length') or 0) or (size or 0)
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                total += len(chunk)
                if progress:
                    progress(total, expected)
                elif expected and total % (32 << 20) < (1 << 20):
                    log(f'  {total / 2**20:.0f} / {expected / 2**20:.0f} MiB'
                        f' ({100 * total / expected:.0f}%)')
    except urllib.error.HTTPError as e:
        part.unlink(missing_ok=True)
        raise DownloadError(f'HTTP {e.code} for {url}: the release may have moved; check '
                            'github.com/mstorsjo/llvm-mingw/releases') from e
    except (urllib.error.URLError, OSError) as e:
        part.unlink(missing_ok=True)
        raise DownloadError(f'cannot download {url}: {e}') from e
    got = h.hexdigest()
    if got != sha256.lower():
        part.unlink(missing_ok=True)
        raise DownloadError(
            f'the downloaded {dest.name} does not match the pinned SHA-256:\n'
            f'  expected {sha256.lower()}\n  got      {got}\n'
            'The download was deleted. If this repeats, the release was replaced upstream: '
            'set "llvm_dir" in toolchain.json to an existing install instead.')
    if size and total != size:
        part.unlink(missing_ok=True)
        raise DownloadError(f'{dest.name} is {total} bytes, expected {size}')
    part.replace(dest)
    log(f'downloaded {dest.name} ({total / 2**20:.0f} MiB in {time.time() - t0:.0f} s, '
        f'sha256 {got[:16]}…)')
    return dest


def sha256_of(path: Path, limit: int | None = None) -> str:
    h = hashlib.sha256()
    left = limit
    with open(path, 'rb') as f:
        while True:
            n = 1 << 20 if left is None else min(1 << 20, left)
            if n <= 0:
                break
            b = f.read(n)
            if not b:
                break
            h.update(b)
            if left is not None:
                left -= len(b)
    return h.hexdigest()


def _strip_root(member: str) -> str:
    """The zip's members all sit under one top-level folder; return the path below it."""
    parts = member.split('/', 1)
    return parts[1] if len(parts) > 1 else ''


def install_llvm(arch: str | None = None, dest: Path | None = None,
                 log: Callable[[str], None] | None = None,
                 progress: Callable[[int, int], None] | None = None) -> Path:
    """Download and unpack LLVM-MinGW, then make the Mach-O linker available.

    After unpacking, `ld64.lld.exe` is created from `ld.lld.exe`: llvm-mingw's release script
    removes the named Mach-O driver, but LLD selects its driver from `argv[0]`, so the same
    binary under that name links Mach-O. `toolchain.ensure_ld64_lld` performs that step and is
    called here so the folder is complete the moment the download finishes.
    """
    log = log or (lambda s: None)
    asset = tc.download_asset(arch)
    base = Path(dest or (Path(__file__).resolve().parents[2]))
    target = base / '.tools' / f'llvm-mingw-{tc.LLVM_MINGW_VERSION}'
    if (target / 'bin' / 'clang.exe').is_file():
        log(f'LLVM-MinGW already installed: {target}')
    else:
        cache = base / '.tools' / 'downloads'
        zpath = download(asset['url'], cache / asset['name'], asset['sha256'], asset['size'],
                         log=log, progress=progress)
        log(f'unpacking {zpath.name} → {target} (about 1 GiB on disk)')
        staging = base / '.tools' / f'.unpack-{tc.LLVM_MINGW_VERSION}'
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            with zipfile.ZipFile(zpath) as z:
                bad = z.testzip()
                if bad:
                    raise DownloadError(f'{zpath.name} is corrupt (first bad member: {bad})')
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    rel = _strip_root(info.filename)
                    if not rel:
                        continue
                    out = staging / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, open(out, 'wb') as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
                    # the zip stores no Unix modes: mark everything in bin/ executable
                    if out.parent.name == 'bin':
                        try:
                            out.chmod(0o755)
                        except OSError:
                            pass
        except zipfile.BadZipFile as e:
            shutil.rmtree(staging, ignore_errors=True)
            raise DownloadError(f'{zpath.name} is not a valid zip: {e}') from e
        # the archive's single top folder becomes our versioned folder
        inner = [p for p in staging.iterdir()]
        if len(inner) == 1 and inner[0].is_dir():
            staging = inner[0]
        shutil.rmtree(target, ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(target)
        log(f'LLVM-MinGW {tc.LLVM_MINGW_VERSION} installed: {target}')
    # make the Mach-O linker available in this brand-new folder
    old = {k: os.environ.get(k) for k in ('NSPB_LLVM_DIR',)}
    os.environ['NSPB_LLVM_DIR'] = str(target)
    try:
        lld, note = tc.ensure_ld64_lld()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    if not lld:
        raise DownloadError(f'LLVM-MinGW unpacked but has no usable Mach-O linker: {note}')
    log(note or f'Mach-O linker: {lld}')
    return target


def metal_tools_hint() -> str:
    return (f'Apple "Metal Developer Tools for Windows" {tc.METAL_TOOLS_VERSION}: '
            f'{tc.METAL_TOOLS_URL}')


def sdk_hint() -> str:
    return (f'the app downloads {tc.SDK_PINNED} from {tc.SDK_REPO}, or use your own '
            'Xcode .xip (needs a free Apple ID)')


def install_git(arch: str | None = None, dest: Path | None = None,
                log: Callable[[str], None] | None = None,
                progress: Callable[[int, int], None] | None = None) -> Path:
    """Download PortableGit and unpack it, returning the git.exe to use.

    PortableGit's .7z.exe is a self-extracting 7-Zip archive: `-o<dir> -y -Install` unpacks it
    without an installer and without administrator rights, which is what makes this work from a
    normal user account. After unpacking, `cmd/git.exe` sits in the target folder.

    The archive hash is checked when one is pinned; an empty hash means the release was not
    pinned yet, and the download is accepted with a note in the log rather than failing.
    """
    log = log or (lambda s: None)
    key = arch or (_arch_key())
    asset = tc.GIT_ASSETS.get(key) or tc.GIT_ASSETS['AMD64']
    target = Path(dest or tc.git_dir())
    exe = target / 'cmd' / 'git.exe'
    if exe.is_file():
        log(f'git is already installed: {exe}')
        return exe
    base = Path(__file__).resolve().parents[2]
    cache = base / '.tools' / 'downloads'
    cache.mkdir(parents=True, exist_ok=True)
    url = f'{tc.GIT_RELEASE_URL}/{asset["name"]}'
    log(f'downloading {asset["name"]} ({asset["size"] // 1048576 if asset["size"] else "~57"} MB)')
    if asset['sha256']:
        zpath = download(url, cache / asset['name'], asset['sha256'], asset['size'] or None,
                         log=log, progress=progress)
    else:
        zpath = _download_unverified(url, cache / asset['name'], log, progress)
    log(f'unpacking {zpath.name} → {target}')
    target.mkdir(parents=True, exist_ok=True)
    # The self-extractor writes the tree directly into -o<dir>; -y answers any prompt, -Install
    # skips the integration step (no registry, no PATH changes).
    r = subprocess.run([str(zpath), f'-o{target}', '-y', '-Install'],
                       capture_output=True, text=True, errors='replace')
    if r.returncode != 0 or not exe.is_file():
        raise DownloadError(
            f'PortableGit unpacking failed (exit {r.returncode}). '
            f'Unpack {zpath} into {target} by hand, or install git from git-scm.com.'
            + (f'\n{r.stderr[:300]}' if r.stderr else ''))
    log(f'git installed: {exe}')
    return exe


def _arch_key() -> str:
    """Always AMD64: this app publishes only the x86-64 host tools (see toolchain._arch)."""
    return 'AMD64'


def _download_unverified(url: str, dest: Path, log: Callable[[str], None],
                         progress: Callable[[int, int], None] | None) -> Path:
    """Fetch a file whose hash is not pinned yet (used only for PortableGit until pinned)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        log(f'already downloaded: {dest.name}')
        return dest
    tmp = dest.with_suffix(dest.suffix + '.part')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'NS-Port-Builder'})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, 'wb') as f:
            total = int(r.headers.get('Content-Length') or 0)
            done = 0
            last = 0.0
            while True:
                b = r.read(1 << 16)
                if not b:
                    break
                f.write(b)
                done += len(b)
                if progress and total:
                    now = time.time()
                    if now - last > 0.3:
                        progress(done, total)
                        last = now
        if progress and total:
            progress(total, total)
        tmp.replace(dest)
        return dest
    except (urllib.error.URLError, OSError) as e:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f'download failed: {url}: {e}') from e

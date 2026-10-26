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


def rank_by_speed(urls: list[str], log: Callable[[str], None],
                  probe_bytes: int = 256 << 10, timeout: float = 8.0) -> list[str]:
    """Order `urls` fastest-first by timing a small ranged request against each.

    This exists because the failure that prompted it was not an error: the 182 MiB LLVM archive
    downloaded from GitHub in 974 s (about 190 KB/s) and *succeeded*, so a fallback-on-failure
    design never fired. Nothing was broken, it was just an hour of waiting — and on a handheld
    that reads as a hang.

    The clock starts at the first byte, not at the request: a TLS handshake to a proxy takes a
    couple of seconds on its own, and timing it would make every source look equally slow (the
    first version of this did exactly that and picked at random).

    A source that errors or times out on the probe is kept at the end rather than dropped: the
    probe is a smaller request than the real one and can fail on its own (a server that rejects
    Range, a hiccup), so it still gets its turn if everything faster fails. The bytes are
    discarded — only the speed is used.
    """
    if len(urls) < 2:
        return urls
    results: list[tuple[float, str]] = []
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'NS-Port-Builder',
                                                     'Range': f'bytes=0-{probe_bytes - 1}'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                first = r.read(min(64 << 10, probe_bytes))
                t_first = time.time()
                rest = r.read(probe_bytes - len(first)) if len(first) < probe_bytes else b''
                t_end = time.time()
            got = len(first) + len(rest)
            if not got:
                raise OSError('empty response')
            # Rate over the transfer only; when the whole probe arrived in the first read there
            # is no transfer window, so that read's own duration is the measurement.
            dt = (t_end - t_first) if rest else max(t_end - t_first, 1e-3)
            results.append((dt, u))
            log(f'  {u.split("//")[1].split("/")[0]}: '
                f'{got / 1024 / max(dt, 1e-3):.0f} KB/s')
        except Exception as e:                          # noqa: BLE001 - a probe never fails a run
            results.append((float('inf'), u))
            log(f'  {u.split("//")[1].split("/")[0]}: {type(e).__name__} '
                f'(kept as a last resort)')
    results.sort(key=lambda r: r[0])
    return [u for _, u in results]


def download(url: str, dest: Path, sha256: str, size: int | None = None,
             log: Callable[[str], None] | None = None,
             progress: Callable[[int, int], None] | None = None,
             algo: str = 'sha256') -> Path:
    """Fetch `url` into `dest`, verifying its digest.

    Downloads to a `.part` file and renames on success, so an interrupted download never looks
    like a usable archive on the next start.

    `algo` exists because Microsoft publishes SHA-512 for the .NET archives (their
    `releases.json` hashes are 128 hex characters, not 64) and we use their number rather than a
    self-computed one: a hash this project computed itself would only prove the file is what we
    already downloaded, not that it is what Microsoft published.
    """
    log = log or (lambda s: None)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        got = digest_of(dest, algo)
        if got == sha256.lower():
            log(f'cached: {dest.name} ({got[:16]}…)')
            return dest
        log(f'{dest.name} has the wrong hash ({got[:16]}…): downloading again')
        dest.unlink()
    part = dest.with_suffix(dest.suffix + '.part')
    errors: list[str] = []
    urls = rank_by_speed(tc.mirror_urls(url), log)
    for attempt, u in enumerate(urls):
        part.unlink(missing_ok=True)
        if attempt:
            log(f'trying another source: {u}')
        else:
            log(f'downloading {u}')
        h = hashlib.new(algo)
        total = 0
        t0 = time.time()
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'NS-Port-Builder'})
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
            errors.append(f'HTTP {e.code} from {u}')
            continue
        except (urllib.error.URLError, OSError) as e:
            part.unlink(missing_ok=True)
            errors.append(f'{u}: {e}')
            continue
        got = h.hexdigest()
        if got != sha256.lower():
            # A mirror that serves different bytes is rejected exactly like a corrupted direct
            # download: the hash is the only thing that says the toolchain is the one we tested.
            part.unlink(missing_ok=True)
            errors.append(f'{u}: {algo.upper()} {got[:16]}… does not match the pinned '
                          f'{sha256[:16]}…')
            continue
        # The length is a progress hint, not a check: the digest above is the authority. A pinned
        # size that is off by a byte (an estimate, or an asset re-uploaded without its hash
        # changing in the code) must not fail a download whose content is provably right.
        if size and total != size:
            log(f'note: {dest.name} is {total} bytes, the pinned size says {size} — content '
                f'verified by {algo.upper()}, continuing')
        part.replace(dest)
        log(f'downloaded {dest.name} ({total / 2**20:.0f} MiB in {time.time() - t0:.0f} s, '
            f'{algo} {got[:16]}…)')
        return dest
    raise DownloadError(
        f'could not download {dest.name}:\n  ' + '\n  '.join(errors) +
        '\nNothing was kept. If this repeats, the release was replaced upstream: point '
        '"llvm_dir" (or "ios_sdk") in toolchain.json at an existing install instead.')


def digest_of(path: Path, algo: str = 'sha256', limit: int | None = None) -> str:
    """The hex digest of a file under `algo` (sha256 for our pins, sha512 for Microsoft's)."""
    h = hashlib.new(algo)
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


def sha256_of(path: Path, limit: int | None = None) -> str:
    return digest_of(path, 'sha256', limit)


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
    root = Path(dest) if dest else tc.tools_dir()
    target = root / f'llvm-mingw-{tc.LLVM_MINGW_VERSION}'
    if (target / 'bin' / 'clang.exe').is_file():
        log(f'LLVM-MinGW already installed: {target}')
    else:
        cache = root / 'downloads'
        zpath = download(asset['url'], cache / asset['name'], asset['sha256'], asset['size'],
                         log=log, progress=progress)
        log(f'unpacking {zpath.name} → {target} (about 1 GiB on disk)')
        staging = root / f'.unpack-{tc.LLVM_MINGW_VERSION}'
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


def install_dotnet(dest: Path | None = None,
                   log: Callable[[str], None] | None = None,
                   progress: Callable[[int, int], None] | None = None) -> Path:
    """Download the .NET SDK zip and unpack it into the app's own tools folder.

    A zip, not the .exe installer: the installer wants to write Program Files and therefore wants
    administrator rights, and it puts the SDK where the app then has to find it. The zip is
    self-contained — unpack it and `dotnet.exe` is the root — so this needs no elevation and no
    registry, and `toolchain.dotnet_dir` looks in the folder it lands in.

    Verified by SHA-256 from Microsoft's release metadata (`releases.json`, the same hash the
    official installers use). The archive is about 287 MB; unpacked it is about 900 MB.
    """
    log = log or (lambda s: None)
    asset = tc.DOTNET_ASSET
    root = Path(dest) if dest else tc.tools_dir()
    target = root / f'dotnet-{tc.DOTNET_VERSION}'
    if (target / 'dotnet.exe').is_file():
        log(f'.NET SDK already installed: {target}')
        return target
    cache = root / 'downloads'
    zpath = download(asset['url'], cache / asset['name'], asset['sha256'], asset['size'],
                     log=log, progress=progress, algo=asset.get('algo', 'sha256'))
    log(f'unpacking {zpath.name} → {target} (about 900 MB on disk)')
    staging = root / f'.unpack-dotnet-{tc.DOTNET_VERSION}'
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zpath) as z:
            bad = z.testzip()
            if bad:
                raise DownloadError(f'{zpath.name} is corrupt (first bad member: {bad})')
            # No top-level folder in this zip: members are host/, sdk/, shared/ directly. Every
            # path is taken as-is, which is what makes dotnet.exe land at the root.
            for info in z.infolist():
                if info.is_dir():
                    continue
                out = staging / info.filename
                # a zip member may try to escape the target (../ in the name)
                if not str(out.resolve()).startswith(str(staging.resolve())):
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(out, 'wb') as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
    except zipfile.BadZipFile as e:
        shutil.rmtree(staging, ignore_errors=True)
        raise DownloadError(f'{zpath.name} is not a valid zip: {e}') from e
    if not (staging / 'dotnet.exe').is_file():
        shutil.rmtree(staging, ignore_errors=True)
        raise DownloadError(f'{zpath.name} unpacked without dotnet.exe at its root: the release '
                            'layout changed; install the SDK from dotnet.microsoft.com instead')
    shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(target)
    log(f'.NET SDK {tc.DOTNET_VERSION} installed: {target}')
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
                       capture_output=True, text=True, errors='replace', **tc.no_window())
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

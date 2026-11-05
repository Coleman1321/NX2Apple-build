#!/usr/bin/env python3
"""Run the official Windows driver with a pinned, already prepared Ocarina engine."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--builder', type=Path, required=True)
    ap.add_argument('--engine', type=Path, required=True)
    ap.add_argument('--nup', type=Path, required=True)
    ap.add_argument('--work-dir', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--spirv-cross', type=Path, required=True)
    ap.add_argument('--wait-for-metal', type=int, default=0, help='seconds to wait for the official Apple ZIP in Downloads')
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    status_path = args.out / 'build-status.json'
    def status(state, **extra):
        status_path.write_text(json.dumps(dict(state=state, updated=time.strftime('%Y-%m-%dT%H:%M:%S%z'), **extra), indent=2), encoding='utf-8')
    sys.path.insert(0, str(args.builder / 'frontend-qt'))
    from nspb_qt.win import fetch, toolchain as tc
    end = time.monotonic() + args.wait_for_metal
    while not (tc.metal_tool('metal') and tc.metal_tool('metallib')):
        status('waiting_for_apple_metal_tools', download=tc.METAL_TOOLS_URL)
        for archive in (Path.home() / 'Downloads').glob('*.zip'):
            if 'metal' not in archive.name.lower():
                continue
            try:
                with zipfile.ZipFile(archive) as z:
                    names = [n.lower() for n in z.namelist()]
                    valid = any(n.endswith('/metal.exe') for n in names) and any(n.endswith('/metallib.exe') for n in names)
                if valid:
                    installed = fetch.install_metal_from_zip(archive, log=print)
                    tc.save_config('metal_dir', str(installed))
                    break
            except (OSError, zipfile.BadZipFile):
                continue
        if tc.metal_tool('metal') and tc.metal_tool('metallib'):
            break
        if time.monotonic() >= end:
            print('Waiting for Metal Developer Tools for Windows from Apple; download its ZIP into Downloads.', flush=True)
            return 2
        time.sleep(5)
    env = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1',
               PYTHONPATH=str(args.builder / 'frontend-qt'), NSPB_REPO=str(args.engine),
               NSPB_SPIRV_CROSS=str(args.spirv_cross), J='6')
    status('checking_toolchain')
    with (args.out / 'toolchain-report.json').open('w', encoding='utf-8') as f:
        result = subprocess.run([sys.executable, '-m', 'nspb_qt.win.doctor', '--json'], env=env, stdout=f)
    if result.returncode:
        status('toolchain_failed', report='toolchain-report.json')
        return result.returncode
    ipa = args.out / 'ZeldaOcarinaOfTime-SideStore.ipa'
    cmd = [sys.executable, '-m', 'nspb_qt.win.driver', str(args.nup), '--romfs', 'separate',
           '--work-dir', str(args.work_dir), '--no-heap-check', '--app-name', 'Zelda Ocarina of Time',
           '--progress', 'lines', '-o', str(ipa)]
    status('building', command=cmd)
    with (args.out / 'build-console.log').open('a', encoding='utf-8') as log:
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        for line in proc.stdout:
            print(line, end='', flush=True)
            log.write(line); log.flush()
        code = proc.wait()
    if code:
        status('build_failed', exit_code=code, log='build-console.log')
        return code
    checker = Path(__file__).with_name('check_ipa_sdk.py')
    code = subprocess.call([sys.executable, str(checker), str(ipa), '--minimum', '27.1', '--report', str(args.out / 'sdk-verification.json')])
    if code:
        status('sdk_verification_failed'); return code
    with zipfile.ZipFile(ipa) as z:
        if len(z.infolist()) >= 65535 or z.testzip():
            status('ipa_verification_failed'); return 1
    with ipa.open('rb') as f:
        h = hashlib.file_digest(f, 'sha256').hexdigest()
    status('complete', ipa=str(ipa), sha256=h, romfs=str(args.work_dir / 'extract/v131072/RomFS.img'), device_tested=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

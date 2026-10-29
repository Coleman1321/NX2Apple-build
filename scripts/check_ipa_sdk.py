#!/usr/bin/env python3
"""Check the main executable's actual iOS SDK in an unsigned arm64 IPA."""
import argparse
import json
import plistlib
import struct
import zipfile
from pathlib import Path


def version(value):
    return f'{value >> 16}.{(value >> 8) & 255}.{value & 255}'


def version_tuple(value):
    parts = tuple(map(int, value.split('.')))
    if not 1 <= len(parts) <= 3 or any(n < 0 or n > 65535 for n in parts):
        raise ValueError(f'invalid version: {value}')
    return parts + (0,) * (3 - len(parts))


def inspect_ipa(path, minimum):
    with zipfile.ZipFile(path) as archive:
        plists = [n for n in archive.namelist()
                  if n.startswith('Payload/') and n.count('/') == 2
                  and n.endswith('.app/Info.plist')]
        if len(plists) != 1:
            raise ValueError('expected one top-level app Info.plist')
        info = plistlib.loads(archive.read(plists[0]))
        executable = info['CFBundleExecutable']
        if not isinstance(executable, str) or '/' in executable or '\\' in executable:
            raise ValueError('invalid CFBundleExecutable')
        data = archive.read(plists[0].rsplit('/', 1)[0] + '/' + executable)
    if len(data) < 32:
        raise ValueError('truncated Mach-O header')
    magic, cpu, _, filetype, ncmds, sizeofcmds, _, _ = struct.unpack_from('<8I', data)
    if (magic, cpu, filetype) != (0xFEEDFACF, 0x0100000C, 2):
        raise ValueError('expected a thin arm64 Mach-O executable')
    end = 32 + sizeofcmds
    if end > len(data):
        raise ValueError('truncated Mach-O load commands')
    offset = 32
    builds = []
    for _ in range(ncmds):
        if offset + 8 > end:
            raise ValueError('truncated load command')
        command, size = struct.unpack_from('<2I', data, offset)
        if size < 8 or size % 8 or offset + size > end:
            raise ValueError('invalid load command size')
        if command == 0x32:  # LC_BUILD_VERSION; platform 2 is iOS, 7 is simulator
            if size < 24:
                raise ValueError('truncated LC_BUILD_VERSION')
            platform, minos, sdk, ntools = struct.unpack_from('<4I', data, offset + 8)
            if size != 24 + ntools * 8 or platform != 2:
                raise ValueError('expected a valid device-iOS LC_BUILD_VERSION')
            builds.append((version(minos), version(sdk)))
        offset += size
    if offset != end or len(builds) != 1:
        raise ValueError('expected exactly one LC_BUILD_VERSION')
    minos, sdk = builds[0]
    if version_tuple(sdk) < version_tuple(minimum):
        raise ValueError(f'executable SDK {sdk} is below required {minimum}')
    return {'ipa': Path(path).name, 'bundle_id': info.get('CFBundleIdentifier'),
            'executable': executable, 'platform': 'iOS', 'architecture': 'arm64',
            'minimum_os': minos, 'linked_sdk': sdk, 'required_sdk': minimum,
            'plist_sdk': info.get('DTSDKName'), 'passed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ipa', type=Path)
    parser.add_argument('--minimum', default='27.1')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        result = inspect_ipa(args.ipa, args.minimum)
    except (ValueError, KeyError, OSError, EOFError, struct.error, zipfile.BadZipFile,
            plistlib.InvalidFileException) as exc:
        parser.exit(1, f'IPA SDK verification failed: {exc}\n')
    report = json.dumps(result, indent=2) + '\n'
    print(report, end='')
    if args.report:
        args.report.write_text(report, encoding='utf-8')


if __name__ == '__main__':
    main()

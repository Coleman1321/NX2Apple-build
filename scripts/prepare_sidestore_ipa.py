#!/usr/bin/env python3
"""Split an existing IPA into a ZIP32 IPA and external shader data, without rebuilding.

SideSign's ZIP reader uses a 16-bit entry count. Work around that platform
limit by using main.m's existing Documents/games/<id>/msl lookup. No shaders
are discarded. The source IPA is never modified.
"""
import argparse
import copy
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import zipfile


def transfer(source, target, entry, name=None):
    info = copy.copy(entry)
    if name is not None:
        info.filename = name
    with source.open(entry) as src, target.open(info, 'w') as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)


def prepare(source, output, game):
    source, output = Path(source), Path(output)
    if not re.fullmatch(r'[0-9A-Fa-f]{16}', game):
        raise ValueError('game must be a 16-digit base title ID')
    game = game.upper()
    ipa = output / (source.stem + '-SideStore.ipa')
    shaders = output / (source.stem + '-shaders.zip')
    guide = output / 'INSTALL-SideStore.txt'
    if any(p.resolve() == source.resolve() or p.exists() for p in (ipa, shaders, guide)):
        raise ValueError('output files already exist; choose a fresh output folder')
    output.mkdir(parents=True, exist_ok=True)
    # Validate before creating output. Read by ZipInfo so duplicate names cannot
    # silently select a different plist or executable.
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        if len(set(names)) != len(names):
            raise ValueError('duplicate paths in source IPA')
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or '\\' in name:
                raise ValueError('unsafe archive path: ' + name)
        plists = [e for e in entries if re.fullmatch(r'Payload/[^/]+\.app/Info\.plist', e.filename)]
        if len(plists) != 1:
            raise ValueError('expected exactly one Payload/*.app/Info.plist')
        plist = plistlib.loads(archive.read(plists[0]))
        root = plists[0].filename.rsplit('/', 1)[0] + '/'
        if plist.get('CFBundleIdentifier', '').lower() != 'org.nxnative.' + game.lower():
            raise ValueError('game ID does not match the IPA bundle identifier')
        executable = plist.get('CFBundleExecutable')
        if not executable or root + executable not in names:
            raise ValueError('app executable is missing')
        prefix = root + 'msl/'
        shader_entries = [e for e in entries if e.filename.startswith(prefix)]
        core = [e for e in entries if not e.filename.startswith(prefix)]
        if not any(not e.is_dir() for e in shader_entries):
            raise ValueError('no bundled shader files found')
        # Leave room for provisioning/signing files inserted by the sideloader.
        if len(core) >= 60000:
            raise ValueError('too many non-shader entries for a SideStore IPA')
        try:
            with zipfile.ZipFile(ipa, 'w', allowZip64=False) as target:
                for entry in core:
                    transfer(archive, target, entry)
            with zipfile.ZipFile(shaders, 'w') as target:
                for entry in shader_entries:
                    name = 'msl/' + entry.filename[len(prefix):]
                    transfer(archive, target, entry, name)
            for path in (ipa, shaders):
                with zipfile.ZipFile(path) as check:
                    bad = check.testzip()
                    if bad:
                        raise ValueError('CRC failure: ' + bad)
            guide.write_text(
                f'Install {ipa.name} with SideStore. The original IPA is unchanged.\n\n'
                f'Unzip {shaders.name} on Windows; it contains the msl folder.\n'
                'Use Apple Devices/iTunes File Sharing to copy folders into the installed\n'
                "Mario Kart/game app's Documents, or use the iPhone Files app.\n"
                f'Create games/{game}/ inside that app folder. Put BOTH folders there:\n'
                f'  games/{game}/msl/<shader-chain-folder>/*.metallib\n'
                f'  games/{game}/romfs/romfs.idx\n'
                f'  games/{game}/romfs/romfs.00 (and ALL other romfs shards)\n\n'
                'Move your existing RomFS folder here if it was at Documents/romfs.\n'
                'The app selects external shaders only when RomFS uses this per-game layout.\n'
                'Copy any existing save/temp folders into the same game folder before playing\n'
                'to keep existing progress when switching to this layout. Keep a backup.\n'
                'Do not install the shaders ZIP as an IPA. Do not remove any shader files.\n'
                'After all transfers finish, close and reopen the game.\n', encoding='utf-8')
        except BaseException:
            for path in (ipa, shaders, guide):
                path.unlink(missing_ok=True)
            raise
    print(f'IPA: {ipa} ({len(core)} entries; ZIP64 disabled)')
    print(f'Shaders: {shaders} ({len(shader_entries)} entries; all retained)')
    print(f'Instructions: {guide}')
    return ipa, shaders


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ipa', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--game', required=True)
    args = parser.parse_args()
    try:
        prepare(args.ipa, args.out, args.game)
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile, plistlib.InvalidFileException) as exc:
        parser.exit(1, f'[RED] {exc}\n')


if __name__ == '__main__':
    main()

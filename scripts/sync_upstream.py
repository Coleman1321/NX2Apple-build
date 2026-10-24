#!/usr/bin/env python3
"""Sync this fork with upstream seedds/nxnative.

The fork was started as a fresh repository (no shared git history), so GitHub's own
"Sync fork" does not apply. The sync is a mechanical procedure — take upstream's tree,
re-apply the fork's features, verify the result builds — and this script is that
procedure, so a scheduled CI job can run it unattended.

What it does:
  1. diffs the two upstream refs over the vendored paths (dm/ scripts/ docs/ AGENTS.md ref/)
  2. applies adds and modifications file by file, and deletions — except the fork's own
     files (the RomFS archive layer), which upstream must not delete
  3. re-applies the fork's patches to the four files that carry them
     (hle_fs.c, the host Makefile, build_ipa.sh, the NSP script); every patch is
     anchor-based and idempotent, and one that no longer fits fails the run loudly
     rather than producing a silently broken tree
  4. verifies: every .py parses on the Python this fork supports as its floor (3.9),
     the iOS build script survives bash -n, the archive reader test passes, and the
     macOS host builds for a real profile (skippable with --skip-build)

On success the caller commits and pushes; on failure nothing is written outside the
working tree, so CI can open an issue with the log instead.

Usage: sync_upstream.py --old <upstream sha> --new <upstream sha> [--skip-build]
"""
import argparse, os, subprocess, sys, shutil, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENDORED = ('dm', 'scripts', 'docs', 'AGENTS.md', 'ref')
# The fork's own files, inside vendored paths: upstream deletes and rewrites must not touch them.
OURS = {'dm/host/romfs_arc.c', 'dm/host/romfs_arc.h', 'dm/tools/romfs_arc.py',
        'dm/host/tests/t_romfs_arc.c', 'docs/ROMFS_ARCHIVE.md',
        'dm/games/0100A00019DE0000/game.fork.tsv'}
# Vendored files that carry fork patches: taken fresh from upstream, then patched below.
PATCHED = ('dm/host/hle_fs.c', 'dm/host/Makefile', 'dm/ios/tools/build_ipa.sh',
           'scripts/build_ipa_from_nsp.py', 'dm/gfx/tools/shader_split.py',
           'dm/ios/Sources/main.m', 'dm/gfx/nvn/nvn_mtl.m')

def git(*a):
    r = subprocess.run(['git', *a], cwd=REPO, capture_output=True, text=True)
    if r.returncode: sys.exit(f'git {" ".join(a)} failed: {r.stderr.strip()}')
    return r.stdout

def blob(rev, path):
    r = subprocess.run(['git', 'cat-file', 'blob', f'{rev}:{path}'], cwd=REPO, capture_output=True)
    return r.stdout if r.returncode == 0 else None

def upstream_changes(old, new):
    """(kind, path) for every vendored file that differs, kind in AM D."""
    out = git('diff', '--name-status', old, new, '--', *VENDORED).splitlines()
    changes = []
    for line in out:
        parts = line.split('\t')
        kind, path = parts[0][0], parts[-1]
        changes.append((kind, path))
    return changes

# ---- the fork's patches. Each is (name, already-marker, [(old, new), ...]); a patch whose
# marker is present is skipped, one whose old text is absent fails the run. ----

HLE = 'dm/host/hle_fs.c'
def patch_hle_fs(t):
    P = []
    P.append(('include', '#include "romfs_arc.h"', [(
        '#include "hle.h"\n#include <mach/mach.h>\n#include "front.h"\n',
        '#include "hle.h"\n#include <mach/mach.h>\n#include "front.h"\n#include "romfs_arc.h"\n')]))
    P.append(('synthetic path', 'ROMFSARC_SYNTH_PREFIX "%s"', [(
        '        if (g_mnt[i].overlay[0] && !create) return rom_overlay_path(&g_mnt[i], rest, out, n);',
        '''        if (g_mnt[i].overlay[0] && !create) return rom_overlay_path(&g_mnt[i], rest, out, n);
        // Archive mount: the RomFS tree lives inside a ROMFSARC archive, so the host path is a
        // synthetic "@romfsarc:<guest path>" that the file calls below route to romfs_arc.c. Matched
        // by the mount directory (romfsarc_open recorded the base it actually opened), because the
        // mount name differs between games (rom, content).
        if (romfsarc_active() && g_mnt[i].ro && !create && g_mnt[i].dir[0] && !strcmp(g_mnt[i].dir, g_arc_base)) {
            if (snprintf(out, n, ROMFSARC_SYNTH_PREFIX "%s", rest) >= (int)n) { errno = ENAMETOOLONG; return 0; }
            return 1;
        }''')]))
    P.append(('MountRom', 'romfsarc_open(dir, &h)', [(
        '''HLE_FORCE("_ZN2nn2fs8MountRomEPKcPvm", "fsp-srv; rom → host RomFS directory", Result, h_fs_MountRom, const char *name, void *cache, size_t sz) {
    (void)cache; (void)sz; char b[1024];
    Result r = mount(name, envdir("DM_ROMFS", "romfs", b, sizeof b), 1);''',
        '''HLE_FORCE("_ZN2nn2fs8MountRomEPKcPvm", "fsp-srv; rom → host RomFS directory (or a ROMFSARC archive)", Result, h_fs_MountRom, const char *name, void *cache, size_t sz) {
    (void)cache; (void)sz; char b[1024];
    const char *dir = envdir("DM_ROMFS", "romfs", b, sizeof b);
    // Archive mount: romfsarc_open tries <dir>.idx, <dir>/romfs.idx and <dir>/romfs/romfs.idx, so the
    // player may copy the shards either beside the folder or into Documents/romfs/ itself.
    romfsarc_hdr h;
    if (romfsarc_open(dir, &h) == 0) {
        // Mount the resolved archive base (romfsarc_open recorded the one that worked in g_arc_base).
        // host_path_ex compares the mount directory against it.
        Result r = mount(name, g_arc_base, 1);
        if (r != RES_OK) { romfsarc_close(); return r; }
        LOG("fs rom: archive %s (%llu files, %llu dirs, %u shards, tree hash %016llx)", g_arc_base,
            (unsigned long long)h.file_count, (unsigned long long)h.dir_count, h.shard_count, (unsigned long long)h.tree_hash);
        return RES_OK;
    }
    Result r = mount(name, dir, 1);''')]))
    P.append(('archive handles', 'static uint64_t arc_new', [(
        'HLE_FORCE("_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci", "fsp-srv → open(2)", Result, h_fs_OpenFile, uint64_t *out, const char *path, int mode) {',
        '''// ---------- Archive-backed file handles ----------
// An archive file has no host fd. It gets a handle number from a private table, and every operation
// on it (ReadFile, GetFileSize, CloseFile) checks the table first. Handle numbers are distinct from
// fds: real handles are fds (>= 3 in practice), archive handles are tagged by index into g_arc[].
typedef struct { uint32_t shard; uint64_t off, size; int used; } archandle;
#define MAX_ARCH 4096
static archandle g_arc[MAX_ARCH];
static uint64_t g_arch_gen;   // bumped on open/close so a stale handle never hits a recycled slot
static uint64_t arc_new(uint32_t shard, uint64_t off, uint64_t size) {
    for (int i = 0; i < MAX_ARCH; i++) if (!g_arc[i].used) {
        g_arc[i].used = 1; g_arc[i].shard = shard; g_arc[i].off = off; g_arc[i].size = size;
        return ((uint64_t)1 << 63) | ((g_arch_gen & 0x7fffffff) << 32) | (uint32_t)i;
    }
    return 0;
}
static int arc_get(uint64_t h, archandle **out) {
    if (!(h >> 63)) return 0;
    uint32_t i = (uint32_t)h;
    if (i >= MAX_ARCH || !g_arc[i].used) return 0;
    if ((uint32_t)((h >> 32) & 0x7fffffff) != (uint32_t)(g_arch_gen & 0x7fffffff)) return 0;
    *out = &g_arc[i]; return 1;
}
static void arc_free(uint64_t h) {
    archandle *a; if (arc_get(h, &a)) a->used = 0;
}
static const char *arc_rel(const char *hp) {
    const char *rel = ROMFSARC_SYNTH_REL(hp);
    while (*rel == '/') rel++;
    return rel;
}
static int arc_file(const char *hp, uint32_t *shard, uint64_t *off, uint64_t *size) {
    return romfsarc_stat_file(arc_rel(hp), shard, off, size);
}
static int arc_dir(const char *hp) { return romfsarc_is_dir(arc_rel(hp)); }
static void arc_norm(const char *hp, char *rel, size_t n) { strlcpy(rel, arc_rel(hp), n); }
HLE_FORCE("_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci", "fsp-srv → open(2)", Result, h_fs_OpenFile, uint64_t *out, const char *path, int mode) {''')]))
    P.append(('OpenFile', 'arc_new(shard, off, size)', [(
        '''    HP(path);
    if (mode & (MODE_WRITE | MODE_APPEND)) RW();
    int fd = open(hp, (mode & (MODE_WRITE | MODE_APPEND)) ? ((mode & MODE_READ) ? O_RDWR : O_WRONLY) : O_RDONLY);''',
        '''    HP(path);
    if (mode & (MODE_WRITE | MODE_APPEND)) RW();
    if (ROMFSARC_IS_SYNTH(hp)) {   // archive entry: no fd, the handle carries shard/offset/size
        uint32_t shard; uint64_t off, size;
        if (!arc_file(hp, &shard, &off, &size)) { errno = ENOENT; return err_res("open", hp); }
        uint64_t ah = arc_new(shard, off, size);
        if (!ah) { errno = EMFILE; return err_res("open", hp); }
        *out = ah;
        if (g_flag.fs) LOG("fs open %s mode=%d → archive handle (shard %u off %llu size %llu)", path, mode, shard, (unsigned long long)off, (unsigned long long)size);
        return RES_OK;
    }
    int fd = open(hp, (mode & (MODE_WRITE | MODE_APPEND)) ? ((mode & MODE_READ) ? O_RDWR : O_WRONLY) : O_RDONLY);''')]))
    P.append(('ReadFile', 'romfsarc_pread(ah->shard', [(
        '''    size_t got = 0; int reprep = 0;
    dm_guest_write_prepare(buf, sz);   // The destination may be a texture pool page write-protected by the graphics layer: a kernel write to a read-only page returns EFAULT instead of page-faulting, so unprotect and mark dirty first
    while (got < sz) {''',
        '''    size_t got = 0; int reprep = 0;
    dm_guest_write_prepare(buf, sz);   // The destination may be a texture pool page write-protected by the graphics layer: a kernel write to a read-only page returns EFAULT instead of page-faulting, so unprotect and mark dirty first
    archandle *ah;
    if (arc_get(h, &ah)) {   // archive entry: clamp to the file, read from its shard
        if (off < 0) { *out = 0; return RES_FAIL; }
        uint64_t avail = (uint64_t)off < ah->size ? ah->size - (uint64_t)off : 0;
        size_t want = sz < avail ? sz : (size_t)avail;
        if (want) { ssize_t r = romfsarc_pread(ah->shard, ah->off + (uint64_t)off, buf, want);
            if (r < 0) return err_res("pread (archive)", "handle"); got = (size_t)r; }
        *out = got;
        if (g_flag.fs) { static uint64_t n, bytes, next_b = 64 << 20; static pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
            pthread_mutex_lock(&m); n++; bytes += got;
            if (bytes >= next_b || n % 1000 == 0) { LOG("fs read total: %llu reads %.1f MiB (this one: archive offset %lld length %#zx)", n, bytes / 1048576.0, (long long)off, got); if (bytes >= next_b) next_b += 64 << 20; }
            pthread_mutex_unlock(&m); }
        return RES_OK;
    }
    while (got < sz) {''')]))
    P.append(('GetFileSize', 'ah->size; return RES_OK', [(
        '''HLE_FORCE("_ZN2nn2fs11GetFileSizeEPlNS0_10FileHandleE", "fsp-srv → fstat(2)", Result, h_fs_GetFileSize, int64_t *out, uint64_t h) {
    if (!h) return RES_FAIL;''',
        '''HLE_FORCE("_ZN2nn2fs11GetFileSizeEPlNS0_10FileHandleE", "fsp-srv → fstat(2)", Result, h_fs_GetFileSize, int64_t *out, uint64_t h) {
    if (!h) return RES_FAIL;
    archandle *ah; if (arc_get(h, &ah)) { *out = (int64_t)ah->size; return RES_OK; }''')]))
    P.append(('CloseFile', 'arc_free(h)', [(
        '''HLE_FORCE("_ZN2nn2fs9CloseFileENS0_10FileHandleE", "fsp-srv → close(2)", void, h_fs_CloseFile, uint64_t h) {
    if (!h) return;   // the null handle after a failed open (see ReadFile): do not touch fd 0''',
        '''HLE_FORCE("_ZN2nn2fs9CloseFileENS0_10FileHandleE", "fsp-srv → close(2)", void, h_fs_CloseFile, uint64_t h) {
    if (!h) return;   // the null handle after a failed open (see ReadFile): do not touch fd 0
    if (h >> 63) { arc_free(h); return; }   // archive entry: nothing to close''')]))
    P.append(('GetEntryType', 'romfsarc_stat_file(rel', [(
        '''HLE_FORCE("_ZN2nn2fs12GetEntryTypeEPNS0_18DirectoryEntryTypeEPKc", "fsp-srv → stat(2)", Result, h_fs_GetEntryType, int32_t *out, const char *path) {
    HP(path); struct stat st;''',
        '''HLE_FORCE("_ZN2nn2fs12GetEntryTypeEPNS0_18DirectoryEntryTypeEPKc", "fsp-srv → stat(2)", Result, h_fs_GetEntryType, int32_t *out, const char *path) {
    HP(path); struct stat st;
    if (ROMFSARC_IS_SYNTH(hp)) {   // archive entry or directory, from the index
        const char *rel = ROMFSARC_SYNTH_REL(hp);
        uint32_t sh; uint64_t of, szf;
        if (romfsarc_stat_file(rel, &sh, &of, &szf)) { *out = ENT_FILE; return RES_OK; }
        if (romfsarc_is_dir(rel)) { *out = ENT_DIR; return RES_OK; }
        errno = ENOENT; return err_res("stat", hp);
    }''')]))
    P.append(('snapshot helper', 'static void arc_snapshot', []))   # inserted below, needs dirh_t
    P.append(('OpenDirectory', 'arc_snapshot(ah, hp)', [(
        '''HLE_FORCE("_ZN2nn2fs13OpenDirectoryEPNS0_15DirectoryHandleEPKci", "fsp-srv → opendir(3)", Result, h_fs_OpenDirectory, uint64_t *out, const char *path, int mode) {
    HP(path); DIR *d = opendir(hp);''',
        '''HLE_FORCE("_ZN2nn2fs13OpenDirectoryEPNS0_15DirectoryHandleEPKci", "fsp-srv → opendir(3)", Result, h_fs_OpenDirectory, uint64_t *out, const char *path, int mode) {
    HP(path);
    if (ROMFSARC_IS_SYNTH(hp)) {   // archive directory: no host DIR, only the snapshot
        if (!arc_dir(hp)) { errno = ENOTDIR; return err_res("opendir", hp); }
        dirh_t *ah = calloc(1, sizeof *ah); if (!ah) die("directory handle allocation failed");
        strlcpy(ah->path, hp, sizeof ah->path); ah->mode = mode;
        arc_snapshot(ah, hp);
        *out = (uint64_t)ah; return RES_OK;
    }
    DIR *d = opendir(hp);''')]))
    P.append(('ReadDirectory guard', "an archive directory that turned out empty", [(
        '''    int dfd = dirfd(h->d);''',
        '''    if (!h->d) { *count = 0; return RES_OK; }   // an archive directory that turned out empty (no snapshot, no host DIR)
    int dfd = dirfd(h->d);''')]))
    P.append(('CloseDirectory guard', 'if (h->d) closedir(h->d)', [(
        '''    dirh_t *h = (dirh_t *)hh; closedir(h->d); if (h->od) closedir(h->od); free(h->snap); free(h);''',
        '''    dirh_t *h = (dirh_t *)hh; if (h->d) closedir(h->d); if (h->od) closedir(h->od); free(h->snap); free(h);''')]))

    for name, marker, pairs in P:
        if marker in t:
            skip(f'hle_fs.c {name} (already patched)'); continue
        for old, new in pairs:
            if old not in t: fail(f'{HLE}: patch "{name}" anchor missing: {old[:70]!r}')
            t = t.replace(old, new, 1)
        done(f'hle_fs.c {name}')
    # arc_snapshot goes right after the dirh_t typedef: it names the type
    if 'static void arc_snapshot' not in t:
        import re
        m = re.search(r'typedef struct \{ DIR \*d;.*?\} dirh_t;\n', t, re.S)
        if not m: fail(f'{HLE}: dirh_t typedef not found')
        t = t[:m.end()] + SNAPSHOT + t[m.end():]
        done('hle_fs.c arc_snapshot')
    return t

SNAPSHOT = '''
// An archive directory has no host DIR: its entries come from the index, copied into the same
// snapshot list the overlay mount uses, so ReadDirectory has one path for both.
static void arc_snapshot(dirh_t *h, const char *hp) {
    char rel[1024]; arc_norm(hp, rel, sizeof rel);
    int n = romfsarc_count(rel);
    if (n <= 0) return;
    romfsarc_ent *ents = malloc((size_t)n * sizeof *ents);
    if (!ents) die("archive directory snapshot allocation failed");
    int got = romfsarc_list(rel, ents, n);
    if (got <= 0) { free(ents); return; }
    h->snap = calloc((size_t)got, sizeof *h->snap); h->nsnap = got;
    if (!h->snap) die("archive directory snapshot allocation failed");
    for (int i = 0; i < got; i++) {
        strlcpy(h->snap[i].name, ents[i].name, sizeof h->snap[i].name);
        h->snap[i].type = ents[i].is_dir ? ENT_DIR : ENT_FILE;
        h->snap[i].size = ents[i].is_dir ? 0 : ents[i].size;
    }
    free(ents);
}
'''

def patch_makefile(t):
    if 'romfs_arc.c' in t: return skip('Makefile (already patched)')
    old = 'SRC=main.c loader.c hle.c crash.c probe.c thread.c memstat.m $(sort $(wildcard hle_*.c)) front_mac.m entry.S'
    if old not in t: fail('dm/host/Makefile: SRC anchor missing (upstream changed the source list)')
    return done('Makefile SRC', t.replace(old, 'SRC=main.c loader.c hle.c romfs_arc.c crash.c probe.c thread.c memstat.m $(sort $(wildcard hle_*.c)) front_mac.m entry.S', 1))

ENT = '''# The unsigned IPA: an unsigned binary has no signature for a sideloader to read entitlements from,
# so the request would be lost (AltStore reads the signature it replaces). Sign ad-hoc with the
# entitlement first; the sideloader strips this signature and carries the entitlement over.
if [ "$PREPARE_XCODE" != YES ] && [ -n "${DM_ENTITLEMENTS-default}" ]; then
  if [ -n "${DM_ENTITLEMENTS:-}" ]; then cp "$DM_ENTITLEMENTS" "$APP/DmIOS.entitlements" || die "copy DM_ENTITLEMENTS"
  else printf '%s\\n' '<?xml version="1.0" encoding="UTF-8"?>' '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \\
    '<plist version="1.0"><dict><key>com.apple.developer.kernel.increased-memory-limit</key><true/></dict></plist>' > "$APP/DmIOS.entitlements" || die "entitlements"; fi
  codesign --force --sign - --entitlements "$APP/DmIOS.entitlements" "$APP" || die "ad-hoc sign with entitlements (the sideloader re-signs; this only carries the request)"
  codesign -d --entitlements :- "$APP" 2>/dev/null | grep -q increased-memory-limit || die "entitlements did not make it into the placeholder signature"
  t "entitlements: increased-memory-limit embedded in the placeholder signature"
fi
'''

def patch_build_ipa(t):
    if 'placeholder signature' in t: return skip('build_ipa.sh entitlements (already patched)')
    old = '''APP=$DD/Build/Products/Release-iphoneos/DmIOS.app
[ -n "$APP" ] && [ -d "$APP" ] || die "no built app"; t "app: $APP"
'''
    if old not in t: fail('dm/ios/tools/build_ipa.sh: APP anchor missing (upstream moved the app definition)')
    t = t.replace(old, old + ENT, 1)
    old2 = '''MAPS+=("$P/romfs=$ROMFS")
t "pack IPA (already-compressed game files stored, everything else deflated)"'''
    if old2 not in t: fail('dm/ios/tools/build_ipa.sh: pack anchor missing')
    return done('build_ipa.sh slim + entitlements', t.replace(old2, '''# DM_FULL_ROMFS=1 packs the RomFS into the package (upstream behaviour; only sensible for small
# games — a full package of a large game is many GB and iOS refuses to install it with
# PackageExtractionFailed). The default is the slim package: the app reads the game files from
# Documents/romfs (a directory tree, or a ROMFSARC archive: romfs.idx + romfs.NN shards).
if [ -n "${DM_FULL_ROMFS:-}" ]; then
  MAPS+=("$P/romfs=$ROMFS")
  t "pack full IPA with RomFS (already-compressed game files stored, everything else deflated)"
else
  t "pack slim IPA without RomFS (game files come from Documents/romfs; DM_FULL_ROMFS=1 packs them)"
fi''', 1))

def patch_nsp(t):
    P = []
    P.append(('work-dir arg', '--work-dir', [(
        "    ap.add_argument('--env-file', help='environment switches for a diagnostic build (one KEY=VALUE per line)')",
        "    ap.add_argument('--work-dir', help='where the build folder goes (default: <NSP folder>/<title ID>_build); the extracted files, shader cache and temporary files all live there')\n"
        "    ap.add_argument('--env-file', help='environment switches for a diagnostic build (one KEY=VALUE per line)')")]))
    P.append(('work-dir paths', 'args.work_dir', [(
        "    out_ipa = Path(os.path.expanduser(args.out or OUT_IPA)).resolve() if (args.out or OUT_IPA) else nsp_dir / g.get('ipa')   # by default in the NSP folder, next to the NSPs and <id>_build/\n"
        "    if shadowed and not (args.out or OUT_IPA): out_ipa = out_ipa.with_name(out_ipa.stem + '-provisional.ipa')   # never over the IPA of the game's real profile\n"
        "    work = nsp_dir / f'{g.id}_build'",
        "    work = Path(os.path.expanduser(args.work_dir)).resolve() if args.work_dir else nsp_dir / f'{g.id}_build'   # the folder holding the NSPs by default; --work-dir puts the build elsewhere\n"
        "    out_ipa = Path(os.path.expanduser(args.out or OUT_IPA)).resolve() if (args.out or OUT_IPA) else work.parent / g.get('ipa')   # by default next to the NSPs and <id>_build/\n"
        "    if shadowed and not (args.out or OUT_IPA): out_ipa = out_ipa.with_name(out_ipa.stem + '-provisional.ipa')   # never over the IPA of the game's real profile")]))
    P.append(('DOTNET_ROOT', 'list-runtimes', [(
        "    env.setdefault('USER', getpass.getuser())   # xcodegen fails without USER (Couldn't find current username)",
        """    env.setdefault('USER', getpass.getuser())   # xcodegen fails without USER (Couldn't find current username)
    # nx_extract is a framework-dependent app: without DOTNET_ROOT the host refuses to start it even
    # when dotnet is on PATH (~/.dotnet is not a registered install location). The root is parsed from
    # `dotnet --list-runtimes`, not assumed to be the binary's directory: Homebrew's
    # /opt/homebrew/bin/dotnet is a symlink into Cellar and its runtime lives in …/libexec, so dirname
    # gave …/bin and the apphost failed to find its runtime. Also into os.environ: some steps run
    # without env= and inherit this process's environment.
    if not env.get('DOTNET_ROOT') and (dn := shutil.which('dotnet', path=env['PATH'])):
        root = None
        try:
            out = subprocess.run([dn, '--list-runtimes'], capture_output=True, text=True, timeout=60).stdout
            for ln in out.splitlines():
                if not ln.startswith('Microsoft.NETCore.App'): continue
                p = ln[ln.rfind('[') + 1:ln.rfind(']')] if '[' in ln else ''
                if p.endswith('/shared/Microsoft.NETCore.App'): root = p[:-len('/shared/Microsoft.NETCore.App')]
                elif p: root = p
                break
        except Exception: pass
        env['DOTNET_ROOT'] = os.environ['DOTNET_ROOT'] = root or str(Path(dn).resolve().parent)""")]))
    P.append(('3.9 survey note', "listed = ', '.join('{} ({})'.format(n, mods[n]['kind'])", [(
        '''    if extra: notes.append(f'modules besides main / sdk: {", ".join(f"{n} ({mods[n]["kind"]})" for n in extra)}; the provisional profile loads {G["modules"][0]} (load order main, subsdk*, sdk)')''',
        '''    if extra:
        # Nested same-quote strings inside an f-string need Python 3.12 (PEP 701); this script has to
        # parse on the 3.9 that ships with the Xcode command line tools, so keep the inner
        # expressions out of the f-string.
        listed = ', '.join('{} ({})'.format(n, mods[n]['kind']) for n in extra)
        notes.append('modules besides main / sdk: ' + listed + '; the provisional profile loads '
                     + G['modules'][0] + ' (load order main, subsdk*, sdk)')''')]))
    P.append(('3.9 not-brought-up note', '_known = ", ".join("{} {}".format(v, b["display"])', [(
        '''        say(f'[RED] this {artifact} uses {pkg_ver} ({disp}), which game profile {reg.id} was not brought up on ''',
        '''        _known = ", ".join("{} {}".format(v, b["display"]) for v, b in reg.builds().items())
        say(f'[RED] this {artifact} uses {pkg_ver} ({disp}), which game profile {reg.id} was not brought up on '''),
        ('''({", ".join(f"{v} {b["display"]}" for v, b in reg.builds().items())})''',
        '''({_known})''')]))
    P.append(('3.9 derived note', '_reg = ", ".join("{} {}".format(v, b["display"]) for v, b in builds.items())', [(
        '''        if pkg_ver not in builds: derived = f'{pkg_ver} is not a version game profile {g.id} registers ({", ".join(f"{v} {b["display"]}" for v, b in builds.items())})\'''',
        '''        if pkg_ver not in builds:
            _reg = ", ".join("{} {}".format(v, b["display"]) for v, b in builds.items())
            derived = f'{pkg_ver} is not a version game profile {g.id} registers ({_reg})\'''')]))
    for name, marker, pairs in P:
        if marker in t:
            skip(f'NSP script {name} (already patched)'); continue
        hit = True
        for old, new in pairs:
            if old not in t:
                if name.startswith('3.9'):   # upstream may fix these themselves; a miss is not an error
                    hit = False; skip(f'NSP script {name} (upstream no longer has the pattern)'); break
                fail(f'scripts/build_ipa_from_nsp.py: patch "{name}" anchor missing')
            t = t.replace(old, new, 1)
        if hit: done(f'NSP script {name}')
    return t

def patch_shader_split(t):
    if 'a backslash cannot sit inside an f-string expression' in t: return skip('shader_split.py (already patched)')
    old = '''        ue_inline_shaders(d, f'/{rel}#{re.sub(r"^(\\.\\./)+", "", os.path.normpath(pk.mount + name))}', out)'''
    if old not in t: fail('dm/gfx/tools/shader_split.py: ue_inline_shaders anchor missing')
    new = '''        _sub = re.sub(r"^(\\.\\./)+", "", os.path.normpath(pk.mount + name))   # a backslash cannot sit inside an f-string expression before 3.12
        ue_inline_shaders(d, '/{}#{}'.format(rel, _sub), out)'''
    return done('shader_split.py 3.9', t.replace(old, new, 1))

NVM = 'dm/gfx/nvn/nvn_mtl.m'
def patch_nvn_mtl(t):
    # The fork's fix for the iOS save-load freeze (NX2Apple issue #4): an upload batch's commit can sit
    # recorded in the open replay block (rec_commit_upload) while the submit thread sleeps on a slot or
    # on g_up_pending — nothing else hands the block over mid-submission, so the submission can never
    # end and the wait never resolves. Upstream independently fixed the up_begin half (Little Nightmares
    # II, their comment in up_begin); ours is kept for the case their tree loses it, and the
    # mtl_finish_gpu half (a loader's QueueFinish mid-submission) is ours alone.
    P = [
        ('up_begin publish', ['the iOS save-load freeze of NX2Apple issue #4', "Little Nightmares II's first render passes"], [(
            '''    unsigned slot = g_up_seq++ % 3;
    up_wait_zero(&g_up_alloc_busy[slot]);''',
            '''    unsigned slot = g_up_seq++ % 3;
    if (atomic_load(&g_up_alloc_busy[slot])) rec_publish();   // The commit of the batch that still holds this slot sits in the open replay block (rec_commit_upload). Hand the block to the encode thread before sleeping on the slot: a submit thread that opens a 4th batch within one submission would otherwise wait forever — nothing else hands the block over mid-submission, and the submission cannot end while up_begin blocks (the iOS save-load freeze of NX2Apple issue #4)
    up_wait_zero(&g_up_alloc_busy[slot]);''')]),
        ('finish publish', ['hand it over before waiting on g_up_pending'], [(
            '''    if (g_fence) mtl_wait(g_fence, UINT64_MAX);
    up_wait_zero(&g_up_pending);''',
            '''    if (g_fence) mtl_wait(g_fence, UINT64_MAX);
    if (on_sub_thread()) rec_publish();   // Pending upload commits sit in the open replay block: hand it over before waiting on g_up_pending, or a loader's QueueFinish mid-submission (Three Houses-style per-resource waits) sleeps forever. Other threads (suspend, diagnostics) cannot publish the submit thread's block; their waits resolve once the submission ends
    up_wait_zero(&g_up_pending);''')]),
    ]
    for name, markers, pairs in P:
        if any(m in t for m in markers):
            skip(f'nvn_mtl.m {name} (already patched)'); continue
        for old, new in pairs:
            if old not in t: fail(f'{NVM}: patch "{name}" anchor missing: {old[:70]!r}')
            t = t.replace(old, new, 1)
        done(f'nvn_mtl.m {name}')
    return t

def patch_main_m(t):
    if 'romfs.idx' in t: return skip('main.m romfs.idx (already patched)')
    old = ('    for (NSString *d in @[[doc stringByAppendingPathComponent:@"romfs"], [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"romfs"]])\n'
           '        if ([fm fileExistsAtPath:[d stringByAppendingPathComponent:@DM_GAME_ROMFS_MARKER]]) return d;   // only a directory containing the game profile\'s romfs_marker path counts (Mario: System/Resource, the resource size table)')
    new = ('    for (NSString *d in @[[doc stringByAppendingPathComponent:@"romfs"], [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"romfs"]]) {\n'
           '        // A ROMFSARC archive: <dir>/romfs.idx next to romfs.NN shards. The host opens it when DM_ROMFS\n'
           '        // points at the base; the marker check does not apply (there are no directories to walk).\n'
           '        NSString *idx = [d stringByAppendingPathComponent:@"romfs.idx"];\n'
           '        if ([fm fileExistsAtPath:idx]) return d;\n'
           '        // A plain directory tree: only one containing the game profile\'s romfs_marker path counts\n'
           '        // (Mario: System/Resource, the resource size table)\n'
           '        if ([fm fileExistsAtPath:[d stringByAppendingPathComponent:@DM_GAME_ROMFS_MARKER]]) return d;\n'
           '    }')
    if old not in t: fail('dm/ios/Sources/main.m: romfs_locate anchor missing')
    return done('main.m romfs.idx', t.replace(old, new, 1))

def patch_hades2(t):
    """The fork's Hades II profile carries what we verified end to end — the update (v1,
    1.0.137848) registered and packed, the measured NVN texture slots (35: slot 34 lies past the
    translator's built-in 32) and the widescreen investigation notes — and upstream's is v0-only.
    The fork's full file ships beside it as game.fork.tsv and is restored wholesale when the
    sync loses the marker; if upstream reworks the profile, merge by hand."""
    if 'build	v1	1.0.137848' in t: return skip('Hades II profile (already patched)')
    fork = (REPO / 'dm/games/0100A00019DE0000/game.fork.tsv').read_text(encoding='utf-8')
    say('  … restoring the fork\'s Hades II profile (update v1, measured slots, notes)')
    return done('Hades II profile v1', fork)

# One marker per carrier: the string that exists only when the fork's patch is in place.
MARKERS = {
    'dm/host/hle_fs.c': 'romfsarc',
    'dm/host/Makefile': 'romfs_arc.c',
    'dm/ios/tools/build_ipa.sh': 'DM_FULL_ROMFS',
    'scripts/build_ipa_from_nsp.py': '--work-dir',
    'dm/gfx/tools/shader_split.py': 'a backslash cannot sit inside an f-string expression',
    'dm/ios/Sources/main.m': 'romfs.idx',
    'dm/gfx/nvn/nvn_mtl.m': 'hand it over before waiting on g_up_pending',
    'dm/games/0100A00019DE0000/game.tsv': 'build	v1	1.0.137848',
}
PATCHERS = {
    'dm/host/hle_fs.c': patch_hle_fs,
    'dm/host/Makefile': patch_makefile,
    'dm/ios/tools/build_ipa.sh': patch_build_ipa,
    'scripts/build_ipa_from_nsp.py': patch_nsp,
    'dm/gfx/tools/shader_split.py': patch_shader_split,
    'dm/ios/Sources/main.m': patch_main_m,
    'dm/gfx/nvn/nvn_mtl.m': patch_nvn_mtl,
    'dm/games/0100A00019DE0000/game.tsv': patch_hades2,
}

report, problems = [], []
class SyncProblem(Exception): pass
def say(s): report.append(s); print(s, flush=True)
def fail(s):
    problems.append(s); say('[FAIL] ' + s)
    raise SyncProblem(s)
def skip(name): say(f'  = {name}')
def done(name, t=None):
    say(f'  + {name}')
    return t

def take_from_upstream(rev, path, dest):
    data = blob(rev, path)
    if data is None: fail(f'{path}: not in upstream {rev}'); return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

def verify(skip_build):
    say('--- verify ---')
    py = '/usr/bin/python3' if os.path.exists('/usr/bin/python3') else sys.executable
    bad = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in ('.git', 'third_party', '__pycache__', '.build', 'node_modules')]
        for f in files:
            if not f.endswith('.py'): continue
            p = Path(root) / f
            r = subprocess.run([py, '-c', 'import ast,sys\ntry: ast.parse(open(sys.argv[1],encoding="utf-8",errors="replace").read())\nexcept SyntaxError as e: print(f"{e.lineno}: {e.msg}")', str(p)], capture_output=True, text=True)
            if r.stdout.strip(): bad.append(f'{p.relative_to(REPO)}:{r.stdout.strip()}')
    if bad:
        for b in bad: fail(f'Python 3.9 syntax: {b}')
    else: say(f'  + every .py parses on the Python 3.9 floor')
    r = subprocess.run(['bash', '-n', 'dm/ios/tools/build_ipa.sh'], cwd=REPO, capture_output=True, text=True)
    if r.returncode: fail(f'build_ipa.sh: bash -n failed: {r.stderr.strip()}')
    else: say('  + build_ipa.sh: bash -n OK')
    # archive reader: compile and run against a small generated archive
    with tempfile.TemporaryDirectory() as td:
        src, arc = Path(td) / 'src', Path(td) / 'romfs'
        (src / 'sub').mkdir(parents=True)
        (src / 'a.txt').write_bytes(b'hello'); (src / 'sub' / 'b.txt').write_bytes(b'world')
        r = subprocess.run([sys.executable, 'dm/tools/romfs_arc.py', 'pack', str(src), str(arc), '--shard-mib', '1'], cwd=REPO, capture_output=True, text=True)
        if r.returncode: fail(f'archive pack failed: {r.stderr.strip()[:200]}'); return
        exe = Path(td) / 't_arc'
        r = subprocess.run(['clang', '-O1', '-I', 'dm/host', '-o', str(exe), 'dm/host/tests/t_romfs_arc.c', 'dm/host/romfs_arc.c'], cwd=REPO, capture_output=True, text=True)
        if r.returncode: fail(f'archive test compile failed: {r.stderr.strip()[:400]}'); return
        r = subprocess.run([str(exe), str(arc)], capture_output=True, text=True)
        if r.returncode or 'all checks passed' not in r.stdout: fail(f'archive test failed: {r.stdout.strip()[:200]} {r.stderr.strip()[:200]}')
        else: say('  + archive reader test passed')
    if skip_build: say('  = host build skipped (--skip-build)'); return
    games = sorted(p.name for p in (REPO / 'dm/games').iterdir() if p.name.startswith('0100'))
    game = '01006F8002326000' if '01006F8002326000' in games else games[0]
    say(f'  … building the macOS host for {game} (a few minutes)')
    r = subprocess.run(['make', '-C', 'dm/host', f'GAME={game}', 'dmhost', '-j4'], cwd=REPO, capture_output=True, text=True)
    if r.returncode:
        tail = '\n'.join((r.stdout + r.stderr).splitlines()[-25:])
        fail(f'host build failed:\n{tail}')
    else: say(f'  + host build OK ({game})')

def apply_changes(a, changes):
    """Take every changed file from upstream, then re-apply the fork's patches to the carriers."""
    touched = 0
    for kind, path in changes:
        dest = REPO / path
        if kind == 'D':
            if path in OURS: fail(f'upstream deleted a fork file: {path}')
            if dest.exists(): dest.unlink(); say(f'  - {path}'); touched += 1
            continue
        if path in OURS: fail(f'upstream writes over a fork file: {path} (resolve by hand)')
        take_from_upstream(a.new, path, dest); touched += 1
        if path in PATCHED:
            r = PATCHERS[path](dest.read_text(encoding='utf-8', errors='replace'))
            if r is not None and r != dest.read_text(encoding='utf-8', errors='replace'):
                dest.write_text(r, encoding='utf-8')
    say(f'{touched} files taken from upstream')
    # Second pass over every carrier, including ones upstream did not change this time: a fork
    # patch can be lost without the file ever appearing in the diff (a wholesale tree replace,
    # a bad merge), so presence is asserted, not assumed.
    for path, patcher in PATCHERS.items():
        p = REPO / path
        if not p.exists(): fail(f'{path}: missing before patching')
        t = p.read_text(encoding='utf-8', errors='replace')
        r = patcher(t)
        if r is not None and r != t: p.write_text(r, encoding='utf-8')
        now = p.read_text(encoding='utf-8', errors='replace')
        if MARKERS[path] not in now:
            fail(f'{path}: fork patch marker missing after sync: {MARKERS[path]!r}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--old', required=True, help='upstream ref the fork is currently at')
    ap.add_argument('--new', required=True, help='upstream ref to sync to')
    ap.add_argument('--skip-build', action='store_true')
    a = ap.parse_args()

    say(f'sync {a.old[:7]} → {a.new[:7]}')
    changes = upstream_changes(a.old, a.new)
    say(f'{len(changes)} upstream file changes under {" ".join(VENDORED)}')
    try:
        apply_changes(a, changes)
        verify(a.skip_build)
    except SyncProblem: pass
    if problems:
        say(f'\nSYNC FAILED: {len(problems)} problem(s) — nothing committed; the working tree is left as the script wrote it, `git checkout -- .` restores it')
        sys.exit(1)
    say('\nSYNC OK — commit and push from the caller')


if __name__ == '__main__':
    main()

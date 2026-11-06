# Ocarina of Time Switch 2 experimental build

Workflow: `.github/workflows/build-oot-ipa.yml`.

This is a separate pipeline. It does not update or replace the Mario Kart workflow.
The GitHub workflow runs a capacity check only. The build now uses the local Windows route described below.

## Verified local input

- Original NUP preserved in Downloads: 25,020,741,061 bytes.
- NUP header length and table-of-contents SHA-256 passed.
- Internal title ID: `0400486024DEC000` (the download filename has an extra digit).
- Update v131072, no base record. Its own ExeFS and RomFS are present.
- 186,592 file records, 26,236,424,856 bytes in the RomFS tree.
- The three executable files passed the NUP parser's SHA-256 checks and their build IDs match the selected profile.
- This does not verify every RomFS file or prove that the standalone update has every required game asset. Full packing checks each file as read.

## Experimental source

Pinned source: vinifloriano/nxnative `b0f6a7a3bb0cb41c8e9a64caad08c50e14501f99`, upstream PR https://github.com/seedds/nxnative/pull/1387.
This is an unmerged bring-up branch, not the stable engine. Its v131072 profile reached the Mac opening sequence, with no validated gameplay or iPhone run.
Related Mac gameplay report: https://github.com/seedds/nxnative/pull/1299 (different build/source). That report describes a 6.2 GiB heap and 13Ã¢â‚¬â€œ14.3 GB resident memory. These are compatibility concerns, not validated iPhone requirements.

## Current blocker

Capacity-only run https://github.com/Coleman1321/NX2Apple-build/actions/runs/42126195638 found 35.55 GiB free. The compressed NUP plus extracted RomFS alone need about 47.8 GiB, before shaders, tool dependencies and compilation. The workflow uses an 80 GiB conservative free-space gate. Its preflight stops before any game-data transfer.
The simulator directory is only 5.1 MB; removing it cannot resolve this. Unused Xcode installs account for only several GB each.

A Mac build environment with sufficient free disk is required, or a Windows cross-build setup with Apple's Metal developer tools. The Windows PC has ample free disk, but that toolchain is not configured here.

## Output and privacy

Game files must never be committed into this public repository. The workflow accepts owner-only draft release input parts; no input release has been uploaded yet. Output IPAs and RomFS parts also remain in draft releases.
The build uses external RomFS and verifies the executable's actual linked iOS SDK is at least 27.1. It checks the IPA stays below 65,535 ZIP entries. The new engine stores shaders as an image, avoiding the old loose-file ZIP64 failure.
The matching RomFS parts must be reassembled and copied as `Documents/romfs.img`; Mario Kart shards cannot be reused.
No IPA has been produced, signed or installed.

## Local Windows setup (2026-11-05)

The Windows builder is installed from LNPANDY/NX2Apple commit `185574225ee782c55be4f53d1a71c0cb7b975c2b` in a separate working checkout. The Ocarina engine remains pinned to the experimental revision above. No engine changes were made.

Installed and checked:

- Isolated Python 3.12 environment with lz4, capstone 5.0.9, fonttools, backports.zstd, zbic and nsz.
- Verified LLVM-MinGW 20261020 / Clang 23.1.4 and Mach-O linker.
- Portable .NET SDK 10.0.403, verified against Microsoft's published SHA-512.
- iPhoneOS27.2.sdk (27.2 / 24B8118), with Windows symlink-stub repairs from the official builder.
- zstd 1.5.7.
- SPIRV-Cross built for Windows from the engine's pinned Khronos commit `f11ba9f0b21ba8fc15153d50a2a1ae31ab1cf8f7`, linked statically to include its runtime dependencies.
- Real cross-compile and cross-link probes passed for an arm64 iOS executable.

Game preparation completed with the official NUP packer: 187,186 packed entries, about 24.44 GiB, at `Downloads/0400486024DEC000_build/extract/v131072/RomFS.img`. The packer verified each file's SHA-256 as it read it. Original NUP unchanged.

The only remaining required dependency is Apple's Metal Developer Tools for Windows 6.2, obtained by the user from https://developer.apple.com/download/all/?q=metal%20developer%20tools (Apple-account download).

`scripts/build_oot_windows.py` imports that ZIP from Downloads, checks the toolchain, launches the official Windows driver, and verifies the finished IPA's actual SDK, ZIP entry count and CRC. It preserves the registered Ocarina memory profile with `--no-heap-check`, rather than applying the Windows provisional heap estimate. Its status JSON and logs go to the chosen output directory. `--wait-for-metal` optionally waits for the download before starting. A launcher was started locally with a one-hour wait for that dependency; shader compilation has not started while Metal is missing.

Local source paths and process IDs are recorded only in the local output folder, not in Git. The game data is not uploaded to GitHub.

### Metal installed and build started (2026-11-06)

Apple supplied an EXE self-extracting installer, not a ZIP: `Metal_Developer_Tools6.2Windows.exe`, 339,551,184 bytes. Its Authenticode signature verified as valid, signed by Apple Inc. It was unpacked into the local builder tool folder and configured with the official toolchain helper.

Metal reports `Apple metal version 32023.850 (metalfe-custom-windows)`. The real shader probe produced a 3,136-byte iOS metallib. All required doctor probes passed.

The local Windows IPA pipeline started at 09:59 Eastern. It reused the prepared RomFS and reached stage 2/6, rewriting main, subsdk0 and sdk. The launcher logs progress and verifies the SDK/ZIP after a successful build. This milestone is not a completed IPA or an iPhone compatibility test.

# Ocarina of Time Switch 2 experimental build

Workflow: `.github/workflows/build-oot-ipa.yml`.

This is a separate pipeline. It does not update or replace the Mario Kart workflow.
The first dispatch runs a capacity check only; the actual IPA build has not started.

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
Related Mac gameplay report: https://github.com/seedds/nxnative/pull/1299 (different build/source). That report describes a 6.2 GiB heap and 13–14.3 GB resident memory. These are compatibility concerns, not validated iPhone requirements.

## Current blocker

Capacity-only run https://github.com/Coleman1321/NX2Apple-build/actions/runs/42126195638 found 35.55 GiB free. The compressed NUP plus extracted RomFS alone need about 47.8 GiB, before shaders, tool dependencies and compilation. The workflow uses an 80 GiB conservative free-space gate. Its preflight stops before any game-data transfer.
The simulator directory is only 5.1 MB; removing it cannot resolve this. Unused Xcode installs account for only several GB each.

A Mac build environment with sufficient free disk is required, or a Windows cross-build setup with Apple's Metal developer tools. The Windows PC has ample free disk, but that toolchain is not configured here.

## Output and privacy

Game files must never be committed into this public repository. The workflow accepts owner-only draft release input parts; no input release has been uploaded yet. Output IPAs and RomFS parts also remain in draft releases.
The build uses external RomFS and verifies the executable's actual linked iOS SDK is at least 27.1. It checks the IPA stays below 65,535 ZIP entries. The new engine stores shaders as an image, avoiding the old loose-file ZIP64 failure.
The matching RomFS parts must be reassembled and copied as `Documents/romfs.img`; Mario Kart shards cannot be reused.
No IPA has been produced, signed or installed.

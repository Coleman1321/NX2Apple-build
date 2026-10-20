# Increased Memory Limit

The app ships `com.apple.developer.kernel.increased-memory-limit` in its entitlements
(`Sources/DmIOS.entitlements`, wired in through `CODE_SIGN_ENTITLEMENTS` in `project.yml`).

## Why it matters

iOS gives an app a per-process physical-memory budget and kills it (jetsam, SIGKILL, no crash
report) when it goes over. On current iPhones that budget is about **3.3 GB** without the
entitlement and **6–8 GB** with it, depending on the device.

Measured here, both on a 12 GB iPhone:

| Game | Peak resident | Headroom | Result |
|---|---|---|---|
| Tears of the Kingdom | 3,342 MB | 33 MB | killed entering the world map |
| Hades II | — | — | asks for a 3.10 GB heap; at the budget limit |

Lowering the render scale to 0.5 did not change the Tears of the Kingdom outcome, so the limit is
the guest heap rather than the GPU. The only way past it is a higher budget.

## What the entitlement needs

Two conditions, both required:

1. **The signature carries it.** `build_ipa.sh` builds unsigned (the sideloader re-signs), so what
   matters is whether the sideloader copies unknown entitlements from the IPA into its own signature
   instead of dropping them.
2. **The App ID has it enabled.** The provisioning profile a sideloader generates only includes
   entitlements the App ID is registered for. The sideloader has to ask Apple for it.

## Which sideloaders keep it

Reported by [playport.dev](https://playport.dev/) (a different project with the same requirement):

| Sideloader | Keeps the entitlement |
|---|---|
| AltStore Classic 2.2 or later | Yes |
| Impactor (from a computer) | Yes |
| Xcode with a Personal Team | Yes |
| SideStore 0.7.0, free Apple ID | Not by default — see below |
| Sideloadly and others | Check the tool; Sideloadly does not enable it |

## SideStore with a free Apple ID

The entitlement attaches to the App ID, so it survives the weekly refresh once set. One-time fix:

1. Install this app through SideStore, so its App ID has been created with Apple.
2. Sideload **GetMoreRam** and sign in with the same Apple ID SideStore uses.
3. In GetMoreRam open **App IDs**, tap **Refresh**, select this app's App ID, then
   **Add Increased Memory Limit**.
4. Reinstall the app from SideStore (it upgrades in place; `Documents/` — the RomFS archive and the
   saves — is preserved).
5. Confirm: `Documents/log.txt` should now show a much larger `headroom to the system memory limit`
   in the `memory up to frame N` lines. GetMoreRam uses one of a free Apple ID's three app slots, so
   delete it afterwards if you need the slot back.

## Checking whether it took effect

Launch the game, let it run a few hundred frames, then read the memory line in `Documents/log.txt`:

```
memory up to frame 600: resident 3342 MB, ... headroom to the system memory limit 33 MB
```

- `headroom` in the low tens of MB, then the log stops with no `CRASH sig=` line → no entitlement.
- `headroom` in the hundreds of MB or more at the same frame count → the entitlement is active.

`os_proc_available_memory()` is what produces that number (`dm/gfx/nvn/nvn_mtl.m`), and it reports
the distance to the budget the kernel enforces.

## Xcode route

With a Personal Team and a real device, add the capability in Xcode
(Signing & Capabilities → + Capability → Increased Memory Limit) and build from there. That is the
one route where the app is signed at build time, so no re-signing step can drop the entitlement.

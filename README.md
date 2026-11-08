# BurgerTime Deluxe - Hi-score Save

Battery-backed **high score saving** for *BurgerTime Deluxe* (Game Boy). The game is
unchanged: no new screens or menus. The hi-score you saw last time is simply still
there next time, instead of resetting to zero whenever the console is switched off.

**Download:** see the [latest release](../../releases/latest) (BPS and IPS patches).
This repository contains no game data; you need your own copy of the ROM.

## Base ROM

The patch applies to exactly this file:

| This | Should be this |
|---|---|
| Name | `BurgerTime Deluxe (World).gb` |
| Size | 65536 bytes |
| CRC32 | `88219A49` |
| MD5 | `9627134CA3EA6E885275D30460CE3563` |
| SHA-1 | `1AAFCEF0DD5FBB8E95188631E0B2DECDF84E9AED` |

The BPS patch verifies this and refuses to apply to anything else; the IPS patch cannot.

## Patching

Apply the `.bps` patch (preferred) or the `.ips` patch to your ROM with the online patcher at
<https://www.romhacking.net/patch/> (it works in your browser, so there is nothing to
install) or any other IPS/BPS patcher. Your original is not modified.

## Requirements

Saving needs cartridge RAM:

- **Emulators:** anything that supports MBC1 + RAM + battery (BGB, SameBoy, mGBA, ...).
  A `.sav` file appears next to the ROM.
- **Hardware:** a flash cart or rewritable cartridge supporting MBC1 with 8 KB of save
  RAM. Battery-backed RAM and non-volatile FRAM both qualify; the DMG-GBWR-50 rewritable
  cartridge uses FRAM.

Without save RAM the game still plays, but, as in the original game, the hi-score is
lost when the console is switched off. A soft reset does not wipe it, with or without
save RAM.

## Using it

- Nothing to do: the hi-score is stored automatically whenever it changes.
- The game's built-in soft reset (A + B + Start + Select) still works and does not wipe
  the hi-score.
- **Reset the hi-score:** switch the console on while holding **Down + Select** and
  release once the game is running. This works at power-on only; the game's own soft
  reset does not trigger it.

## Limitations

- Only the hi-score is saved.
- A damaged save (wrong check byte, or digits that are not valid BCD) is ignored and
  the game starts with a zero hi-score.
- Don't share one save slot between several games on the same cartridge.

## How it works

Everything goes into unused space or hook points; the header is changed to MBC1+RAM+BATTERY
(`0x147` 01 to 03, `0x149` 00 to 02) and its checksums are recalculated.

| Where | What |
|---|---|
| `0x0185` | boot hook: `call $0049` (replaces `ld [$0000],a`) |
| `0x0040` | VBlank vector: `call $0051` then `jp $3FD0` |
| `0x0049`, `0x0051` | 7-byte stubs in the unused part of the interrupt table |
| `0x3FD0` | save routine (47 bytes, bank 0) |
| `0x7EE3` | load routine (bank 1) |

Game RAM: hi-score `$DFF0-$DFF2` (3 bytes BCD, same order as on screen), current score
`$C342-$C344`. Save RAM at `$A000`: the three hi-score bytes plus a check byte
(`$A5 + b0 + b1 + b2`).

- The **load routine** runs once at boot, after the game's own RAM clear. It forces ROM
  bank 1 first, so it does not depend on which bank was mapped before.
- The **save routine** runs after the game's own VBlank handler has finished drawing
  (the handler's `reti` returns into it), so VRAM updates are not delayed, and it writes
  to save RAM only when the hi-score changed.

If you have Python, you can try this yourself using the scripts from the repository:
`patch_burgertime.py` rebuilds the patched ROM from your original ROM, and
`make_release_burgertime.py` builds the patches, READMEs and zip.

## Tested

BGB and real hardware: DMG-GBWR-50 rewritable cartridge and EZ Flash Jr, played on Game Boy,
Game Boy Color, Analogue Pocket and ModRetro Chromatic. Tested: saving, loading, hi-score reset
and soft resets.

## Legal

No game data is included, only the differences. *BurgerTime* belongs to its respective
owners; this is an unofficial fan modification and is not affiliated with them.

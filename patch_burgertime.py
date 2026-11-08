#!/usr/bin/env python3
"""Add hi-score saving (battery SRAM) to "BurgerTime Deluxe (World).gb".

Usage:  python patch_burgertime.py "roms\\BurgerTime Deluxe (World).gb"
Output: same folder, "<name> (hi-score save).gb". The original is not modified.

Diagnostic:  add --header-only to get "<name> (header only).gb": only the cartridge
header is changed (RAM+battery declared), no code. Use it to tell whether a flaky
cart is bothered by the header/RAM setup itself or by the save code.

What it changes
  header 0x147   01 -> 03   MBC1 -> MBC1+RAM+BATTERY
  header 0x149   00 -> 02   8 KB cartridge RAM
  0x0185         ld [$0000],a  ->  call Boot     (boot: restore hi-score)
  0x0040         VBlank vector -> call VBlank2 ; jp Tail
  0x0049         Boot stub    (7 bytes, unused interrupt-table gap)
  0x0051         VBlank2      (7 bytes, unused interrupt-table gap)
  0x3FD0         Tail         (47 bytes, bank 0)
  0x7EE3         Load routine (bank 1)

How the VBlank hook works
  The game's VBlank handler does its VRAM drawing in a tight time window, so the save
  must not run before it. The vector now does "call VBlank2"; VBlank2 pushes the
  registers and jumps to the original handler exactly as the old vector did. The
  handler's final reti therefore returns to the instruction after the call, a
  "jp Tail" that runs the save AFTER the game has finished drawing, then returns to
  the interrupted code. The game's drawing starts only 6 cycles later than originally.

Save only WRITES to cartridge RAM when the hi-score differs from the saved copy.

Boot stub: forces ROM bank 1 and jumps to Load, so Load does not depend on which
ROM bank happened to be mapped before (a reset does not necessarily reset the
cartridge's bank register).

Reset: hold Down + Select while the console is switched on (a power-on boot; the
game's own soft reset does not trigger it) and the saved hi-score is ignored and overwritten with zero. Change RESET_BUTTONS / RESET_DPAD
below to pick others; all selected buttons must be held together.

SRAM layout at $A000:  hi-score byte 0..2, then check byte = $A5 + b0 + b1 + b2
Load also rejects a record whose bytes are not valid BCD (each nibble 0-9).
Hi-score RAM: $DFF0-$DFF2 (3 bytes, BCD, same order as on screen)
"""
import sys
from pathlib import Path

HI_SCORE = 0xDFF0
SRAM = 0xA000
VBLANK_HANDLER = 0x04D4          # original target of the jp in the VBlank vector
VECTOR = 0x0040                  # VBlank vector: push af,bc,de,hl ; jp 04D4
TAIL_ADDR = 0x3FD0               # 48 bytes of 0xFF in bank 0
TAIL_SPACE = 48
LOAD_ADDR = 0x7EE3               # 285 bytes of 0xFF in bank 1
BOOT_ADDR = 0x0049               # 7 zero bytes after the LCD-STAT vector's reti
VB2_ADDR = 0x0051                # 7 zero bytes after the timer vector's reti
HOOK_BOOT = 0x0185

# Held together at boot -> wipe the hi-score. Bit values:
RESET_BUTTONS = 0x04             # A=1, B=2, Select=4, Start=8   (here: Select)
RESET_DPAD = 0x08                # Right=1, Left=2, Up=4, Down=8 (here: Down; 0 = unused)
VALIDATE_BCD = True              # set False if a legitimate hi-score ever fails to restore


def le(v):
    return bytes([v & 0xFF, v >> 8])


def asm(org, prog):
    """Tiny two-pass assembler: bytes, 'label:' strings, ('jr', opcode, label)."""
    labels, pos = {}, org
    for it in prog:
        if isinstance(it, bytes):
            pos += len(it)
        elif isinstance(it, str):
            labels[it.rstrip(":")] = pos
        else:
            pos += 2
    out, pos = bytearray(), org
    for it in prog:
        if isinstance(it, bytes):
            out += it
            pos += len(it)
        elif isinstance(it, tuple):
            _, op, lab = it
            off = labels[lab] - (pos + 2)
            assert -128 <= off <= 127, "jr out of range"
            out += bytes([op, off & 0xFF])
            pos += 2
    return bytes(out)


def build_vb2():
    # What the original vector did: save registers, enter the real handler.
    return asm(VB2_ADDR, [
        b"\xF5", b"\xC5", b"\xD5", b"\xE5",   # push af / bc / de / hl
        b"\xC3" + le(VBLANK_HANDLER),         # jp $04D4
    ])


def build_tail(org):
    # Runs after the game's handler has finished (its reti returns to 0x0043,
    # which jumps here). Interrupted code's registers are live again, so keep them.
    return asm(org, [
        b"\xF5", b"\xC5", b"\xD5", b"\xE5",   # push af / bc / de / hl
        b"\x3E\x0A",                          # ld a,$0A
        b"\xEA\x00\x00",                      # ld [$0000],a      enable SRAM
        b"\x21" + le(HI_SCORE),                # ld hl,$DFF0
        b"\x11" + le(SRAM),                   # ld de,$A000
        b"\x06\x03",                          # ld b,3
        b"\x0E\xA5",                          # ld c,$A5          running check byte
        "l:",
        b"\x1A",                              # ld a,[de]         saved byte
        b"\xBE",                              # cp [hl]           same as hi-score byte?
        ("jr", 0x28, "same"),                 # jr z,same
        b"\x7E",                              # ld a,[hl]
        b"\x12",                              # ld [de],a         changed -> write it
        "same:",
        b"\x2A",                              # ld a,[hl+]
        b"\x81",                              # add a,c
        b"\x4F",                              # ld c,a
        b"\x13",                              # inc de
        b"\x05",                              # dec b
        ("jr", 0x20, "l"),                    # jr nz,l
        b"\x1A",                              # ld a,[de]         saved check byte
        b"\xB9",                              # cp c
        ("jr", 0x28, "done"),                 # jr z,done
        b"\x79",                              # ld a,c
        b"\x12",                              # ld [de],a         check changed -> write it
        "done:",
        b"\xAF",                              # xor a
        b"\xEA\x00\x00",                      # ld [$0000],a      disable SRAM
        b"\xE1", b"\xD1", b"\xC1", b"\xF1",   # pop hl / de / bc / af
        b"\xC9",                              # ret               to the interrupted code
    ])


def build_boot():
    # Entered by "call" from 0x0185, right after the game's "xor a" at 0x0184, so A=0.
    return asm(BOOT_ADDR, [
        b"\x3C",                              # inc a             A = 1
        b"\xEA\x00\x20",                      # ld [$2000],a      force ROM bank 1
        b"\xC3" + le(LOAD_ADDR),              # jp Load           (its ret returns to 0x0188)
    ])


def build_load():
    code = [
        b"\xC5", b"\xD5", b"\xE5",      # push bc / de / hl
        b"\x3E\x10",                    # ld a,$10          select buttons
        b"\xE0\x00",                    # ldh [$FF00],a
        b"\xF0\x00",                    # ldh a,[$FF00]     (read twice: lets the
        b"\xF0\x00",                    # ldh a,[$FF00]      lines settle on hardware)
        b"\xE6" + bytes([RESET_BUTTONS]),   # and RESET_BUTTONS  pressed reads as 0
    ]
    if RESET_DPAD:
        code += [
            b"\x47",                    # ld b,a
            b"\x3E\x20",                # ld a,$20          select d-pad
            b"\xE0\x00",                # ldh [$FF00],a
            b"\xF0\x00",                # ldh a,[$FF00]
            b"\xF0\x00",                # ldh a,[$FF00]
            b"\xE6" + bytes([RESET_DPAD]),  # and RESET_DPAD
            b"\xB0",                    # or b              zero only if all held
        ]
    code += [
        b"\x3E\x30",                    # ld a,$30          deselect (flags untouched)
        b"\xE0\x00",                    # ldh [$FF00],a
        ("jr", 0x28, "done"),           # jr z,done         combo held -> skip loading
        b"\x3E\x0A",                    # ld a,$0A
        b"\xEA\x00\x00",                # ld [$0000],a      enable SRAM
        b"\x21" + le(SRAM),             # ld hl,$A000
        b"\x0E\xA5",                    # ld c,$A5
        b"\x06\x03",                    # ld b,3
        "sum:",
        b"\x2A",                        # ld a,[hl+]
        b"\x81",                        # add a,c
        b"\x4F",                        # ld c,a
        b"\x05",                        # dec b
        ("jr", 0x20, "sum"),
        b"\x7E",                        # ld a,[hl]         stored check byte
        b"\xB9",                        # cp c
        ("jr", 0x20, "done"),           # jr nz,done        invalid -> keep defaults
    ]
    if VALIDATE_BCD:
        code += [
            b"\x21" + le(SRAM),         # ld hl,$A000
            b"\x06\x03",                # ld b,3
            "bcd:",
            b"\x7E",                    # ld a,[hl]
            b"\xE6\x0F",                # and $0F           low digit
            b"\xFE\x0A",                # cp 10
            ("jr", 0x30, "done"),       # jr nc,done        digit > 9 -> reject
            b"\x2A",                    # ld a,[hl+]
            b"\xCB\x37",                # swap a
            b"\xE6\x0F",                # and $0F           high digit
            b"\xFE\x0A",                # cp 10
            ("jr", 0x30, "done"),
            b"\x05",                    # dec b
            ("jr", 0x20, "bcd"),
        ]
    code += [
        b"\x21" + le(SRAM),             # ld hl,$A000
        b"\x11" + le(HI_SCORE),          # ld de,$DFF0
        b"\x06\x03",                    # ld b,3
        "cp:",
        b"\x2A",                        # ld a,[hl+]
        b"\x12",                        # ld [de],a
        b"\x13",                        # inc de
        b"\x05",                        # dec b
        ("jr", 0x20, "cp"),
        "done:",
        b"\xAF",                        # xor a             (the game expects A=0 here)
        b"\xEA\x00\x00",                # ld [$0000],a      disable SRAM
        b"\xE1", b"\xD1", b"\xC1",      # pop hl / de / bc
        b"\xC9",                        # ret
    ]
    return asm(LOAD_ADDR, code)


def fix_checksums(rom):
    c = 0
    for b in rom[0x134:0x14D]:
        c = (c - b - 1) & 0xFF
    rom[0x14D] = c
    g = (sum(rom) - rom[0x14E] - rom[0x14F]) & 0xFFFF
    rom[0x14E], rom[0x14F] = g >> 8, g & 0xFF


def expect(rom, addr, want, what):
    got = bytes(rom[addr:addr + len(want)])
    if got != want:
        sys.exit(f"Refusing to patch: {what} at 0x{addr:04X} is {got.hex(' ')}, "
                 f"expected {want.hex(' ')}. Wrong ROM version?")


def main(path, header_only=False):
    src = Path(path)
    rom = bytearray(src.read_bytes())
    if len(rom) != 0x10000:
        sys.exit("Expected a 64 KB ROM.")

    expect(rom, 0x147, b"\x01", "cartridge type")
    expect(rom, 0x149, b"\x00", "RAM size")
    expect(rom, 0x150, b"\xF3", "boot code (di)")
    expect(rom, 0x184, b"\xAF", "boot code (xor a)")
    expect(rom, HOOK_BOOT, b"\xEA\x00\x00", "boot hook (ld [$0000],a)")
    expect(rom, VECTOR, b"\xF5\xC5\xD5\xE5\xC3" + le(VBLANK_HANDLER), "VBlank vector")
    expect(rom, 0x48, b"\xD9", "LCD STAT vector (reti)")
    expect(rom, 0x50, b"\xD9", "timer vector (reti)")

    if header_only:
        rom[0x147] = 0x03
        rom[0x149] = 0x02
        fix_checksums(rom)
        dst = src.with_name(src.stem + " (header only).gb")
        dst.write_bytes(rom)
        print(f"Written: {dst}  (header only, no save code)")
        return dst

    tail = build_tail(TAIL_ADDR)
    vb2 = build_vb2()
    boot = build_boot()
    load = build_load()
    if len(tail) > TAIL_SPACE:
        sys.exit("Tail does not fit in the bank 0 free space.")

    areas = ((TAIL_ADDR, tail, 0xFF, "Tail"), (VB2_ADDR, vb2, 0x00, "VBlank2"),
             (BOOT_ADDR, boot, 0x00, "Boot"), (LOAD_ADDR, load, 0xFF, "Load"))
    for addr, code, fill, name in areas:
        if any(b != fill for b in rom[addr:addr + len(code)]):
            sys.exit(f"{name} target area at 0x{addr:04X} is not free "
                     f"(not all 0x{fill:02X}).")
    for addr, code, fill, name in areas:
        rom[addr:addr + len(code)] = code
        print(f"{name}: {len(code)} bytes at 0x{addr:04X}")

    rom[HOOK_BOOT:HOOK_BOOT + 3] = b"\xCD" + le(BOOT_ADDR)              # call Boot
    rom[VECTOR:VECTOR + 7] = (b"\xCD" + le(VB2_ADDR)                    # call VBlank2
                              + b"\xC3" + le(TAIL_ADDR) + b"\x00")      # jp Tail (0x0043)
    rom[0x147] = 0x03        # MBC1+RAM+BATTERY
    rom[0x149] = 0x02        # 8 KB RAM
    fix_checksums(rom)

    dst = src.with_name(src.stem + " (hi-score save).gb")
    dst.write_bytes(rom)
    print(f"Written: {dst}")
    return dst


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    main(args[0], header_only="--header-only" in sys.argv)

"""Print the key Game Boy ROM header fields and find free space.
Usage: python gbheader.py game.gb
"""
import sys

CART_TYPES = {
    0x00: "ROM ONLY", 0x01: "MBC1", 0x02: "MBC1+RAM", 0x03: "MBC1+RAM+BATTERY",
    0x08: "ROM+RAM", 0x09: "ROM+RAM+BATTERY",
    0x0F: "MBC3+TIMER+BATTERY", 0x10: "MBC3+TIMER+RAM+BATTERY",
    0x11: "MBC3", 0x12: "MBC3+RAM", 0x13: "MBC3+RAM+BATTERY",
    0x19: "MBC5", 0x1A: "MBC5+RAM", 0x1B: "MBC5+RAM+BATTERY",
}
RAM_SIZES = {0: "none", 1: "2 KB", 2: "8 KB", 3: "32 KB", 4: "128 KB", 5: "64 KB"}


def main(path):
    rom = open(path, "rb").read()
    if len(rom) < 0x150:
        sys.exit("File too small to be a Game Boy ROM.")

    title = rom[0x134:0x144].split(b"\x00")[0].decode("ascii", "replace")
    cart = rom[0x147]
    rom_code = rom[0x148]
    ram_code = rom[0x149]

    hdr_calc = 0
    for b in rom[0x134:0x14D]:
        hdr_calc = (hdr_calc - b - 1) & 0xFF

    glob_calc = (sum(rom) - rom[0x14E] - rom[0x14F]) & 0xFFFF
    glob_stored = (rom[0x14E] << 8) | rom[0x14F]

    print(f"File size     : {len(rom)} bytes ({len(rom) // 1024} KB)")
    print(f"Title         : {title}")
    print(f"CGB flag      : 0x{rom[0x143]:02X}")
    print(f"Cart type     : 0x{cart:02X} {CART_TYPES.get(cart, '(unknown)')}")
    print(f"ROM size code : 0x{rom_code:02X} ({32 << rom_code} KB)")
    print(f"RAM size code : 0x{ram_code:02X} ({RAM_SIZES.get(ram_code, '?')})")
    print(f"Header sum    : stored 0x{rom[0x14D]:02X}, computed 0x{hdr_calc:02X}"
          f" {'OK' if hdr_calc == rom[0x14D] else 'MISMATCH'}")
    print(f"Global sum    : stored 0x{glob_stored:04X}, computed 0x{glob_calc:04X}")
    print(f"Entry point   : {rom[0x100:0x104].hex(' ')}  (usually 00 C3 lo hi)")

    # Free space: runs of 0x00 or 0xFF at least 32 bytes long
    print("\nFree space candidates (runs >= 32 bytes):")
    found = 0
    i = 0
    while i < len(rom):
        if rom[i] in (0x00, 0xFF):
            j = i
            while j < len(rom) and rom[j] == rom[i]:
                j += 1
            if j - i >= 32:
                bank = i // 0x4000
                print(f"  0x{i:05X}-0x{j - 1:05X}  {j - i:5d} bytes  "
                      f"(fill 0x{rom[i]:02X}, bank {bank})")
                found += 1
            i = j
        else:
            i += 1
    if not found:
        print("  none found")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])

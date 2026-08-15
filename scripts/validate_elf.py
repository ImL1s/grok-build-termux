#!/usr/bin/env python3
"""
ELF Binary Validator for Android/Termux (grok-build-termux).

Validates native Android ELF binaries against Bionic libc requirements and
Android 15+ 16 KiB page-size alignment constraints.

Features:
- Validates ELF magic, architecture, endianness, and ELF type.
- Checks Bionic dynamic linker (/system/bin/linker64) vs glibc ld.so.
- Enforces 16 KiB page-size alignment (p_align >= 16384 and p_vaddr % p_align == p_offset % p_align) on PT_LOAD segments.
- Analyzes PT_DYNAMIC DT_NEEDED dependencies (detects libc.so vs libc.so.6).
- Supports JSON output, self-testing, and mock ELF generation for testing pipelines.
"""

import argparse
import json
import os
import struct
import sys
from typing import Any, Dict, List, Optional, Tuple

# ELF Constants
EI_MAG0 = 0
EI_MAG1 = 1
EI_MAG2 = 2
EI_MAG3 = 3
EI_CLASS = 4
EI_DATA = 5
EI_VERSION = 6
EI_OSABI = 7
EI_ABIVERSION = 8

ELFMAG = b"\x7fELF"
ELFCLASSNONE = 0
ELFCLASS32 = 1
ELFCLASS64 = 2

ELFDATANONE = 0
ELFDATA2LSB = 1  # Little endian
ELFDATA2MSB = 2  # Big endian

ET_NONE = 0
ET_REL = 1
ET_EXEC = 2
ET_DYN = 3
ET_CORE = 4

EM_NONE = 0
EM_386 = 3
EM_ARM = 40
EM_X86_64 = 62
EM_AARCH64 = 183

ARCH_NAMES = {
    EM_386: "i686",
    EM_ARM: "arm",
    EM_X86_64: "x86_64",
    EM_AARCH64: "aarch64",
}

ARCH_BY_NAME = {v: k for k, v in ARCH_NAMES.items()}

# Program Header Types
PT_NULL = 0
PT_LOAD = 1
PT_DYNAMIC = 2
PT_INTERP = 3
PT_NOTE = 4
PT_SHLIB = 5
PT_PHDR = 6
PT_TLS = 7
PT_GNU_EH_FRAME = 0x6474e550
PT_GNU_STACK = 0x6474e551
PT_GNU_RELRO = 0x6474e552

# Dynamic Section Tags
DT_NULL = 0
DT_NEEDED = 1
DT_STRTAB = 5
DT_SYMTAB = 6
DT_STRSZ = 10

# Bionic vs Glibc Linkers
BIONIC_LINKERS = [
    "/system/bin/linker64",
    "/system/bin/linker",
    "/apex/com.android.runtime/bin/linker64",
    "/apex/com.android.runtime/bin/linker",
]

GLIBC_LINKERS = [
    "/lib/ld-linux-aarch64.so.1",
    "/lib64/ld-linux-x86-64.so.2",
    "/lib/ld-linux.so.2",
    "/lib/ld-linux-armhf.so.3",
    "/lib/ld-musl-aarch64.so.1",
    "/lib/ld-musl-x86_64.so.1",
]

FORBIDDEN_GLIBC_LIBS = [
    "libc.so.6",
    "libpthread.so.0",
    "libm.so.6",
    "libdl.so.2",
    "librt.so.1",
]


class ElfValidationError(Exception):
    pass


class ElfSegment:
    def __init__(
        self,
        p_type: int,
        p_offset: int,
        p_vaddr: int,
        p_paddr: int,
        p_filesz: int,
        p_memsz: int,
        p_flags: int,
        p_align: int,
    ):
        self.p_type = p_type
        self.p_offset = p_offset
        self.p_vaddr = p_vaddr
        self.p_paddr = p_paddr
        self.p_filesz = p_filesz
        self.p_memsz = p_memsz
        self.p_flags = p_flags
        self.p_align = p_align

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.p_type,
            "offset": hex(self.p_offset),
            "vaddr": hex(self.p_vaddr),
            "filesz": self.p_filesz,
            "memsz": self.p_memsz,
            "flags": self.p_flags,
            "align": hex(self.p_align),
            "align_decimal": self.p_align,
        }


class ElfBinary:
    def __init__(self, data: bytes, filename: str = "<memory>"):
        self.data = data
        self.filename = filename
        self.is_64bit = False
        self.is_little_endian = True
        self.endian_prefix = "<"
        self.e_type = 0
        self.e_machine = 0
        self.e_version = 0
        self.e_entry = 0
        self.e_phoff = 0
        self.e_shoff = 0
        self.e_flags = 0
        self.e_ehsize = 0
        self.e_phentsize = 0
        self.e_phnum = 0
        self.e_shentsize = 0
        self.e_shnum = 0
        self.e_shstrndx = 0
        self.segments: List[ElfSegment] = []
        self.interpreter: Optional[str] = None
        self.needed_libraries: List[str] = []
        self._parse()

    def _parse(self):
        if len(self.data) < 52:
            raise ElfValidationError(f"File too small for ELF header ({len(self.data)} bytes)")

        if self.data[:4] != ELFMAG:
            raise ElfValidationError(f"Invalid ELF magic: {self.data[:4]!r}")

        elf_class = self.data[EI_CLASS]
        if elf_class == ELFCLASS64:
            self.is_64bit = True
        elif elf_class == ELFCLASS32:
            self.is_64bit = False
        else:
            raise ElfValidationError(f"Invalid ELF class: {elf_class}")

        elf_data = self.data[EI_DATA]
        if elf_data == ELFDATA2LSB:
            self.is_little_endian = True
            self.endian_prefix = "<"
        elif elf_data == ELFDATA2MSB:
            self.is_little_endian = False
            self.endian_prefix = ">"
        else:
            raise ElfValidationError(f"Invalid ELF data encoding: {elf_data}")

        fmt = self.endian_prefix
        if self.is_64bit:
            if len(self.data) < 64:
                raise ElfValidationError("File too small for 64-bit ELF header")
            hdr_fmt = fmt + "16sHHIQQQIHHHHHH"
            fields = struct.unpack_from(hdr_fmt, self.data, 0)
            self.e_type = fields[1]
            self.e_machine = fields[2]
            self.e_version = fields[3]
            self.e_entry = fields[4]
            self.e_phoff = fields[5]
            self.e_shoff = fields[6]
            self.e_flags = fields[7]
            self.e_ehsize = fields[8]
            self.e_phentsize = fields[9]
            self.e_phnum = fields[10]
            self.e_shentsize = fields[11]
            self.e_shnum = fields[12]
            self.e_shstrndx = fields[13]
        else:
            hdr_fmt = fmt + "16sHHIIIIIHHHHHH"
            fields = struct.unpack_from(hdr_fmt, self.data, 0)
            self.e_type = fields[1]
            self.e_machine = fields[2]
            self.e_version = fields[3]
            self.e_entry = fields[4]
            self.e_phoff = fields[5]
            self.e_shoff = fields[6]
            self.e_flags = fields[7]
            self.e_ehsize = fields[8]
            self.e_phentsize = fields[9]
            self.e_phnum = fields[10]
            self.e_shentsize = fields[11]
            self.e_shnum = fields[12]
            self.e_shstrndx = fields[13]

        self._parse_program_headers()
        self._parse_dynamic_section()

    def _parse_program_headers(self):
        if self.e_phoff == 0 or self.e_phnum == 0:
            return

        fmt = self.endian_prefix
        for i in range(self.e_phnum):
            offset = self.e_phoff + i * self.e_phentsize
            if offset + self.e_phentsize > len(self.data):
                break

            if self.is_64bit:
                phdr_fmt = fmt + "IIQQQQQQ"
                fields = struct.unpack_from(phdr_fmt, self.data, offset)
                p_type = fields[0]
                p_flags = fields[1]
                p_offset = fields[2]
                p_vaddr = fields[3]
                p_paddr = fields[4]
                p_filesz = fields[5]
                p_memsz = fields[6]
                p_align = fields[7]
            else:
                phdr_fmt = fmt + "IIIIIIII"
                fields = struct.unpack_from(phdr_fmt, self.data, offset)
                p_type = fields[0]
                p_offset = fields[1]
                p_vaddr = fields[2]
                p_paddr = fields[3]
                p_filesz = fields[4]
                p_memsz = fields[5]
                p_flags = fields[6]
                p_align = fields[7]

            segment = ElfSegment(
                p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align
            )
            self.segments.append(segment)

            if p_type == PT_INTERP:
                interp_bytes = self.data[p_offset : p_offset + p_filesz]
                self.interpreter = interp_bytes.rstrip(b"\x00").decode("utf-8", errors="replace")

    def _parse_dynamic_section(self):
        dyn_segment = next((s for s in self.segments if s.p_type == PT_DYNAMIC), None)
        if not dyn_segment:
            return

        fmt = self.endian_prefix
        entry_size = 16 if self.is_64bit else 8
        num_entries = dyn_segment.p_filesz // entry_size

        dt_needed_offsets = []
        strtab_offset = None
        strtab_vaddr = None

        for i in range(num_entries):
            off = dyn_segment.p_offset + i * entry_size
            if off + entry_size > len(self.data):
                break
            if self.is_64bit:
                tag, val = struct.unpack_from(fmt + "QQ", self.data, off)
            else:
                tag, val = struct.unpack_from(fmt + "II", self.data, off)

            if tag == DT_NULL:
                break
            elif tag == DT_NEEDED:
                dt_needed_offsets.append(val)
            elif tag == DT_STRTAB:
                strtab_vaddr = val

        if strtab_vaddr is not None:
            # Map vaddr to file offset using PT_LOAD
            for seg in self.segments:
                if seg.p_type == PT_LOAD and seg.p_vaddr <= strtab_vaddr < seg.p_vaddr + seg.p_memsz:
                    strtab_offset = seg.p_offset + (strtab_vaddr - seg.p_vaddr)
                    break

        if strtab_offset is not None:
            for str_off in dt_needed_offsets:
                lib_offset = strtab_offset + str_off
                end = self.data.find(b"\x00", lib_offset)
                if end != -1:
                    lib_name = self.data[lib_offset:end].decode("utf-8", errors="replace")
                    self.needed_libraries.append(lib_name)


def validate_elf(
    elf: ElfBinary,
    min_page_size: int = 16384,
    strict_16k: bool = True,
    target_arch: str = "aarch64",
    bionic_only: bool = True,
) -> Tuple[bool, List[str], List[str]]:
    """
    Validates an ELF binary against Android/Termux deployment criteria.
    Returns (is_valid, errors, warnings).
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Architecture Check
    actual_arch = ARCH_NAMES.get(elf.e_machine, f"unknown({elf.e_machine})")
    if target_arch != "any":
        expected_machine = ARCH_BY_NAME.get(target_arch)
        if elf.e_machine != expected_machine:
            errors.append(
                f"Architecture mismatch: binary is '{actual_arch}' (e_machine={elf.e_machine}), "
                f"expected '{target_arch}'"
            )

    # 2. Binary Format (Must be 64-bit for aarch64/x86_64, Little Endian)
    if target_arch in ("aarch64", "x86_64") and not elf.is_64bit:
        errors.append(f"64-bit architecture {target_arch} requires ELFCLASS64 binary")
    if not elf.is_little_endian:
        errors.append("Android targets must be Little Endian (ELFDATA2LSB)")

    # 3. Interpreter / Dynamic Linker Check
    if elf.interpreter:
        if bionic_only:
            if not any(elf.interpreter == linker or elf.interpreter.startswith("/system/bin/linker") or elf.interpreter.startswith("/apex/com.android.runtime/bin/linker") for linker in BIONIC_LINKERS):
                errors.append(
                    f"Incompatible dynamic linker: '{elf.interpreter}'. "
                    f"Android Bionic requires '/system/bin/linker64' or '/system/bin/linker'."
                )
            if any(elf.interpreter.startswith(glibc) or glibc in elf.interpreter for glibc in GLIBC_LINKERS):
                errors.append(
                    f"Desktop Linux / glibc interpreter detected: '{elf.interpreter}'. "
                    "Cannot execute on Android/Termux Bionic libc."
                )
    else:
        # Static executable
        warnings.append("Binary is statically linked (no PT_INTERP found)")

    # 4. 16 KiB Page-Size Alignment Check
    load_segments = [s for s in elf.segments if s.p_type == PT_LOAD]
    if not load_segments:
        errors.append("No PT_LOAD segments found in ELF binary")
    else:
        for idx, seg in enumerate(load_segments):
            # Check p_align
            if strict_16k and seg.p_align < min_page_size:
                errors.append(
                    f"PT_LOAD segment #{idx} alignment {seg.p_align} (0x{seg.p_align:x}) is less than "
                    f"required {min_page_size} (0x{min_page_size:x}) for Android 15+ 16 KiB compatibility"
                )

            # Check congruence: p_vaddr % p_align == p_offset % p_align
            if seg.p_align > 1:
                vaddr_mod = seg.p_vaddr % seg.p_align
                offset_mod = seg.p_offset % seg.p_align
                if vaddr_mod != offset_mod:
                    errors.append(
                        f"PT_LOAD segment #{idx} violates ELF congruence: "
                        f"p_vaddr (0x{seg.p_vaddr:x}) % p_align (0x{seg.p_align:x}) = 0x{vaddr_mod:x} != "
                        f"p_offset (0x{seg.p_offset:x}) % p_align (0x{seg.p_align:x}) = 0x{offset_mod:x}"
                    )

    # 5. Shared Library Dependencies Check (glibc vs Bionic)
    for lib in elf.needed_libraries:
        if lib in FORBIDDEN_GLIBC_LIBS or lib.startswith("ld-linux"):
            errors.append(
                f"Forbidden glibc runtime dependency detected: '{lib}'. "
                "Binary must link against Android Bionic (libc.so, libm.so, libdl.so)."
            )

    is_valid = len(errors) == 0
    return is_valid, errors, warnings


# ---------------------------------------------------------------------------
# Synthetic Mock ELF Generator for Test Suite Validation
# ---------------------------------------------------------------------------
def generate_mock_elf(mock_type: str) -> bytes:
    """
    Generates synthetic ELF byte sequences for unit tests and validator self-tests.
    Supported types:
    - 'valid_16k_bionic': Valid 64-bit aarch64 Bionic ELF with 16 KiB alignment
    - 'invalid_4k_bionic': 64-bit aarch64 Bionic ELF with legacy 4 KiB alignment
    - 'invalid_glibc': 64-bit aarch64 ELF with /lib/ld-linux-aarch64.so.1 and libc.so.6
    - 'misaligned_load': 64-bit aarch64 ELF where p_vaddr % align != p_offset % align
    - 'invalid_magic': Corrupt header with non-ELF magic
    - 'valid_static_16k': Statically linked 16 KiB aarch64 binary
    """
    if mock_type == "invalid_magic":
        return b"NOT_AN_ELF_BINARY_HEADER"

    is_64 = True
    endian = "<"
    e_machine = EM_AARCH64
    e_type = ET_DYN

    # Build Header
    ident = bytearray(16)
    ident[0:4] = ELFMAG
    ident[EI_CLASS] = ELFCLASS64
    ident[EI_DATA] = ELFDATA2LSB
    ident[EI_VERSION] = 1
    ident[EI_OSABI] = 0

    phentsize = 56
    phoff = 64
    ehsize = 64

    # Determine segments based on mock_type
    interp_str = b"/system/bin/linker64\x00"
    if mock_type == "invalid_glibc":
        interp_str = b"/lib/ld-linux-aarch64.so.1\x00"

    align = 0x4000  # 16 KiB
    if mock_type == "invalid_4k_bionic":
        align = 0x1000  # 4 KiB

    # Strings and offsets
    dynstr = b"\x00"
    if mock_type == "invalid_glibc":
        dynstr += b"libc.so.6\x00"
    else:
        dynstr += b"libc.so\x00libdl.so\x00"

    # We will build 4 segments:
    # 0: PT_PHDR
    # 1: PT_INTERP (omitted if valid_static_16k)
    # 2: PT_LOAD (RX)
    # 3: PT_LOAD (RW)
    # 4: PT_DYNAMIC

    has_interp = mock_type != "valid_static_16k"
    phnum = 5 if has_interp else 4

    elf_header = struct.pack(
        endian + "16sHHIQQQIHHHHHH",
        bytes(ident),
        e_type,
        e_machine,
        1,  # e_version
        0x4000,  # e_entry
        phoff,  # e_phoff
        0,  # e_shoff
        0,  # e_flags
        ehsize,
        phentsize,
        phnum,
        0,  # e_shentsize
        0,  # e_shnum
        0,  # e_shstrndx
    )

    data = bytearray(elf_header)

    # Pad to phoff
    if len(data) < phoff:
        data.extend(b"\x00" * (phoff - len(data)))

    # Segment metadata calculations
    interp_offset = 0x200
    interp_len = len(interp_str)
    dynstr_offset = 0x300
    dynamic_offset = 0x400

    # PT_LOAD 1: Offset 0, vaddr 0, size 0x1000, align
    load1_offset = 0x0
    load1_vaddr = 0x0
    load1_filesz = 0x1000
    load1_memsz = 0x1000
    load1_align = align

    if mock_type == "misaligned_load":
        # Congruence violation: vaddr % align != offset % align
        load1_vaddr = 0x1000  # offset 0 % 0x4000 = 0, vaddr 0x1000 % 0x4000 = 0x1000

    # PT_LOAD 2: Offset 0x4000, vaddr 0x4000, size 0x1000, align
    load2_offset = 0x4000
    load2_vaddr = 0x4000
    load2_filesz = 0x1000
    load2_memsz = 0x1000
    load2_align = align

    phdrs = []
    # 0. PT_PHDR
    phdrs.append(
        struct.pack(endian + "IIQQQQQQ", PT_PHDR, 4, phoff, phoff, phoff, phnum * phentsize, phnum * phentsize, 8)
    )

    # 1. PT_INTERP
    if has_interp:
        phdrs.append(
            struct.pack(
                endian + "IIQQQQQQ",
                PT_INTERP,
                4,
                interp_offset,
                interp_offset,
                interp_offset,
                interp_len,
                interp_len,
                1,
            )
        )

    # 2. PT_LOAD 1
    phdrs.append(
        struct.pack(
            endian + "IIQQQQQQ",
            PT_LOAD,
            5,  # R-X
            load1_offset,
            load1_vaddr,
            load1_vaddr,
            load1_filesz,
            load1_memsz,
            load1_align,
        )
    )

    # 3. PT_LOAD 2
    phdrs.append(
        struct.pack(
            endian + "IIQQQQQQ",
            PT_LOAD,
            6,  # RW-
            load2_offset,
            load2_vaddr,
            load2_vaddr,
            load2_filesz,
            load2_memsz,
            load2_align,
        )
    )

    # 4. PT_DYNAMIC
    phdrs.append(
        struct.pack(
            endian + "IIQQQQQQ",
            PT_DYNAMIC,
            6,
            dynamic_offset,
            dynamic_offset,
            dynamic_offset,
            0x40,
            0x40,
            8,
        )
    )

    data.extend(b"".join(phdrs))

    # Pad and write Interpreter string
    if len(data) < interp_offset:
        data.extend(b"\x00" * (interp_offset - len(data)))
    data[interp_offset : interp_offset + interp_len] = interp_str

    # Pad and write Dynstr
    if len(data) < dynstr_offset:
        data.extend(b"\x00" * (dynstr_offset - len(data)))
    data[dynstr_offset : dynstr_offset + len(dynstr)] = dynstr

    # Pad and write Dynamic Section
    if len(data) < dynamic_offset:
        data.extend(b"\x00" * (dynamic_offset - len(data)))

    dyn_entries = []
    # DT_NEEDED = 1 (libc offset in dynstr)
    dyn_entries.append(struct.pack(endian + "QQ", DT_NEEDED, 1))
    # DT_STRTAB = 5 (vaddr of dynstr)
    dyn_entries.append(struct.pack(endian + "QQ", DT_STRTAB, dynstr_offset))
    # DT_STRSZ = 10
    dyn_entries.append(struct.pack(endian + "QQ", DT_STRSZ, len(dynstr)))
    # DT_NULL = 0
    dyn_entries.append(struct.pack(endian + "QQ", DT_NULL, 0))

    dyn_bytes = b"".join(dyn_entries)
    data[dynamic_offset : dynamic_offset + len(dyn_bytes)] = dyn_bytes

    # Pad full binary to load2_offset + load2_filesz
    total_len = load2_offset + load2_filesz
    if len(data) < total_len:
        data.extend(b"\x00" * (total_len - len(data)))

    return bytes(data)


def run_self_test() -> bool:
    """Runs automated internal test suite verifying positive and negative validation cases."""
    print("Running ELF Validator internal self-tests...")
    test_cases = [
        ("valid_16k_bionic", True, "Valid 16 KiB Bionic aarch64 binary"),
        ("invalid_4k_bionic", False, "4 KiB page size Bionic binary (should fail strict 16K)"),
        ("invalid_glibc", False, "glibc ld-linux.so interpreter binary (should fail Bionic check)"),
        ("misaligned_load", False, "Misaligned PT_LOAD segment congruence violation"),
        ("invalid_magic", False, "Corrupt ELF magic header"),
        ("valid_static_16k", True, "Statically linked 16 KiB aarch64 binary"),
    ]

    all_passed = True
    for mock_type, expected_pass, desc in test_cases:
        mock_bytes = generate_mock_elf(mock_type)
        try:
            elf = ElfBinary(mock_bytes, filename=f"mock_{mock_type}")
            is_valid, errors, warnings = validate_elf(
                elf, min_page_size=16384, strict_16k=True, target_arch="aarch64", bionic_only=True
            )
        except ElfValidationError as e:
            is_valid = False
            errors = [str(e)]
            warnings = []

        passed = (is_valid == expected_pass)
        status_sym = "✓" if passed else "✗"
        print(f"  [{status_sym}] {desc} (Result: {'VALID' if is_valid else 'INVALID'}, Expected: {'VALID' if expected_pass else 'INVALID'})")
        if not passed:
            all_passed = False
            print(f"      Errors returned: {errors}")

    if all_passed:
        print("All self-tests passed successfully.")
    else:
        print("Self-tests FAILED.")
    return all_passed


def main():
    parser = argparse.ArgumentParser(
        description="ELF Binary Validator for grok-build-termux (Bionic & 16 KiB Page Alignment)"
    )
    parser.add_argument("files", nargs="*", help="Path(s) to ELF binary files to validate")
    parser.add_argument(
        "--min-page-size",
        type=int,
        default=16384,
        help="Minimum required page size in bytes (default: 16384 / 16 KiB)",
    )
    parser.add_argument(
        "--strict-16k",
        action="store_true",
        default=True,
        help="Enforce strict 16 KiB alignment on all PT_LOAD segments (default: True)",
    )
    parser.add_argument(
        "--target-arch",
        choices=["aarch64", "x86_64", "arm", "i686", "any"],
        default="aarch64",
        help="Target architecture to verify (default: aarch64)",
    )
    parser.add_argument(
        "--bionic-only",
        action="store_true",
        default=True,
        help="Require Android Bionic dynamic linker (reject glibc/musl) (default: True)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON report",
    )
    parser.add_argument(
        "--generate-mock",
        type=str,
        metavar="OUT_PATH",
        help="Generate synthetic mock ELF binary to OUT_PATH for testing",
    )
    parser.add_argument(
        "--mock-type",
        choices=[
            "valid_16k_bionic",
            "invalid_4k_bionic",
            "invalid_glibc",
            "misaligned_load",
            "invalid_magic",
            "valid_static_16k",
        ],
        default="valid_16k_bionic",
        help="Type of mock ELF to generate with --generate-mock",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run validator self-tests",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose diagnostic logging",
    )

    args = parser.parse_args()

    if args.self_test:
        success = run_self_test()
        sys.exit(0 if success else 1)

    if args.generate_mock:
        mock_bytes = generate_mock_elf(args.mock_type)
        os.makedirs(os.path.dirname(os.path.abspath(args.generate_mock)), exist_ok=True)
        with open(args.generate_mock, "wb") as f:
            f.write(mock_bytes)
        print(f"Generated mock ELF binary '{args.mock_type}' at {args.generate_mock} ({len(mock_bytes)} bytes)")
        sys.exit(0)

    if not args.files:
        parser.print_help()
        sys.exit(2)

    overall_success = True
    results = []

    for filepath in args.files:
        file_res: Dict[str, Any] = {
            "file": filepath,
            "valid": False,
            "errors": [],
            "warnings": [],
            "details": {},
        }

        if not os.path.exists(filepath):
            file_res["errors"].append(f"File not found: {filepath}")
            overall_success = False
            results.append(file_res)
            continue

        try:
            with open(filepath, "rb") as f:
                data = f.read()

            elf = ElfBinary(data, filename=filepath)
            is_valid, errors, warnings = validate_elf(
                elf,
                min_page_size=args.min_page_size,
                strict_16k=args.strict_16k,
                target_arch=args.target_arch,
                bionic_only=args.bionic_only,
            )

            file_res["valid"] = is_valid
            file_res["errors"] = errors
            file_res["warnings"] = warnings
            file_res["details"] = {
                "arch": ARCH_NAMES.get(elf.e_machine, f"unknown({elf.e_machine})"),
                "class": "64-bit" if elf.is_64bit else "32-bit",
                "endian": "little" if elf.is_little_endian else "big",
                "interpreter": elf.interpreter,
                "needed_libraries": elf.needed_libraries,
                "segments": [s.to_dict() for s in elf.segments],
            }

            if not is_valid:
                overall_success = False

        except Exception as e:
            file_res["errors"].append(f"ELF parse error: {e}")
            overall_success = False

        results.append(file_res)

    if args.json:
        print(json.dumps({"success": overall_success, "results": results}, indent=2))
    else:
        for r in results:
            status = "PASS" if r["valid"] else "FAIL"
            print(f"[{status}] {r['file']}")
            if r["details"]:
                print(f"  Arch: {r['details']['arch']} ({r['details']['class']}, {r['details']['endian']}-endian)")
                if r["details"]["interpreter"]:
                    print(f"  Interpreter: {r['details']['interpreter']}")
                if r["details"]["needed_libraries"]:
                    print(f"  Dependencies: {', '.join(r['details']['needed_libraries'])}")
            for err in r["errors"]:
                print(f"  ERROR: {err}")
            for warn in r["warnings"]:
                print(f"  WARNING: {warn}")
            print()

    sys.exit(0 if overall_success else 1)


if __name__ == "__main__":
    main()

"""
Tier 4 Real-World Scenario 5: Cross-Compiled Bionic ELF Header & 16 KiB Alignment Validation.

Exercised Features:
- F6: Native Bionic Build Profile
- F7: 16 KiB ELF Page-Size Alignment
- F30: CI Cross-Compilation & ELF Validator
"""

import unittest
import os
import tempfile
from scripts.validate_elf import (
    ElfBinary,
    validate_elf,
    generate_mock_elf,
)


class TestScenarioElfValidation(unittest.TestCase):

    def test_scenario_elf_validator_full_positive_pipeline(self):
        """Simulates CI validating a valid 16 KiB Bionic aarch64 native release binary."""
        mock_elf_data = generate_mock_elf("valid_16k_bionic")
        with tempfile.NamedTemporaryFile(suffix="_grok_bin", delete=False) as f:
            f.write(mock_elf_data)
            temp_path = f.name

        try:
            with open(temp_path, "rb") as f:
                data = f.read()
            elf = ElfBinary(data, filename=temp_path)

            is_valid, errors, warnings = validate_elf(
                elf,
                min_page_size=16384,
                strict_16k=True,
                target_arch="aarch64",
                bionic_only=True,
            )

            self.assertTrue(is_valid)
            self.assertEqual(len(errors), 0)
            self.assertEqual(elf.e_machine, 183)  # EM_AARCH64
            self.assertEqual(elf.interpreter, "/system/bin/linker64")
            self.assertTrue(all(seg.p_align >= 16384 for seg in elf.segments if seg.p_type == 1))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_scenario_elf_validator_catches_glibc_and_4k_page_alignment(self):
        """Simulates CI catching an invalid desktop Linux glibc build with 4 KiB alignment."""
        # 1. Catch 4 KiB aligned binary
        mock_4k = generate_mock_elf("invalid_4k_bionic")
        elf_4k = ElfBinary(mock_4k)
        valid_4k, err_4k, _ = validate_elf(elf_4k, min_page_size=16384, strict_16k=True)
        self.assertFalse(valid_4k)
        self.assertTrue(any("alignment" in err.lower() for err in err_4k))

        # 2. Catch glibc ld-linux interpreter binary
        mock_glibc = generate_mock_elf("invalid_glibc")
        elf_glibc = ElfBinary(mock_glibc)
        valid_glibc, err_glibc, _ = validate_elf(elf_glibc, bionic_only=True)
        self.assertFalse(valid_glibc)
        self.assertTrue(any("glibc" in err.lower() for err in err_glibc))


if __name__ == "__main__":
    unittest.main()

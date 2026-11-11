import unittest
import struct

from package_release import validate_metadata, validate_windows_amd64_dll


class ReleaseMetadataTests(unittest.TestCase):
    def setUp(self):
        self.repository = "https://github.com/fixture-user/cpa-plugin-codexreflow"
        self.metadata = {"Name": "codexreflow", "Version": "0.1.0", "GitHubRepository": self.repository}

    def test_matching_metadata(self):
        validate_metadata(self.metadata, "0.1.0", self.repository)

    def test_development_build_rejected(self):
        self.metadata["Version"] = "0.1.0-dev"
        with self.assertRaises(ValueError):
            validate_metadata(self.metadata, "0.1.0", self.repository)

    def test_version_and_source_mismatch_rejected(self):
        for field, value in (("Name", "codexcomp"), ("Version", "0.2.0"), ("GitHubRepository", "https://github.com/uf-hy/cpa-plugin-codexcomp")):
            with self.subTest(field=field):
                changed = {**self.metadata, field: value}
                with self.assertRaises(ValueError):
                    validate_metadata(changed, "0.1.0", self.repository)

    def test_placeholder_and_invalid_versions_rejected(self):
        for version in ("v0.1.0", "0.1.0-dev", "00.1.0", "0.1", "1; echo test"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                validate_metadata(self.metadata, version, self.repository)
        for repository in ("https://github.com/OWNER/cpa-plugin-codexreflow", "https://github.com/REPLACE_WITH_OWNER/cpa-plugin-codexreflow", "https://example.com/user/repo"):
            with self.subTest(repository=repository), self.assertRaises(ValueError):
                validate_metadata(self.metadata, "0.1.0", repository)


class ReleasePlatformTests(unittest.TestCase):
    def fixture(self, machine=0x8664, dll_flag=0x2000):
        raw = bytearray(256)
        raw[:2] = b"MZ"
        struct.pack_into("<I", raw, 60, 128)
        raw[128:132] = b"PE\0\0"
        struct.pack_into("<H", raw, 132, machine)
        struct.pack_into("<H", raw, 150, dll_flag)
        return raw

    def test_windows_amd64_dll(self):
        validate_windows_amd64_dll(self.fixture())

    def test_invalid_and_other_platforms_rejected(self):
        for raw in (b"not a DLL", self.fixture(machine=0xAA64), self.fixture(dll_flag=0)):
            with self.assertRaises(ValueError):
                validate_windows_amd64_dll(raw)


if __name__ == "__main__":
    unittest.main()

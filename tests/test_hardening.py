"""Tests for hardened error paths added in the production robustness pass."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from skillhub.core import (  # noqa: E402
    InstallError,
    ManifestError,
    Registry,
    SkillError,
    parse_manifest,
    resolve_dependencies,
)
from skillhub.cli import main  # noqa: E402

REG = os.path.join(os.path.dirname(__file__), "..", "demos", "01-basic", "registry")


def _mk_skill(tmp, name, version, requires=None):
    d = os.path.join(tmp, name)
    os.makedirs(d, exist_ok=True)
    req = ("requires: [" + ", ".join(requires) + "]\n") if requires else ""
    body = "---\nname: %s\nversion: %s\ndescription: %s\n%s---\nbody\n" % (
        name, version, name, req)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(body)
    return d


class TestManifestHardening(unittest.TestCase):
    def test_non_string_input_raises(self):
        """parse_manifest must raise ManifestError for non-string input."""
        with self.assertRaises(ManifestError):
            parse_manifest(None)  # type: ignore[arg-type]

    def test_empty_string_raises(self):
        """Empty string has no front-matter fence -> ManifestError."""
        with self.assertRaises(ManifestError):
            parse_manifest("")

    def test_unclosed_frontmatter_raises(self):
        """Front-matter that never closes raises ManifestError."""
        manifest = "---\nname: foo\nversion: 1.0.0\ndescription: x\n"
        with self.assertRaises(ManifestError):
            parse_manifest(manifest)

    def test_invalid_name_chars_raises(self):
        """Names with uppercase letters are rejected."""
        bad = "---\nname: FooBar\nversion: 1.0.0\ndescription: x\n---\nbody"
        with self.assertRaises(ManifestError):
            parse_manifest(bad)


class TestRegistryHardening(unittest.TestCase):
    def test_empty_registry_path_raises(self):
        """Constructing Registry with empty string raises SkillError."""
        with self.assertRaises(SkillError):
            Registry("")

    def test_nonexistent_registry_raises(self):
        """skills() on a non-existent path raises SkillError."""
        reg = Registry("/does/not/exist/ever")
        with self.assertRaises(SkillError):
            reg.skills()

    def test_bad_manifest_in_registry_skipped(self):
        """A corrupt SKILL.md is silently skipped; good skills still load."""
        with tempfile.TemporaryDirectory() as tmp:
            _mk_skill(tmp, "good", "1.0.0")
            bad = os.path.join(tmp, "bad")
            os.makedirs(bad, exist_ok=True)
            with open(os.path.join(bad, "SKILL.md"), "w") as fh:
                fh.write("---\nname: bad\nversion: 1.0.0\n")
            reg = Registry(tmp)
            skills = reg.skills()
            self.assertIn("good", skills)
            self.assertNotIn("bad", skills)

    def test_get_empty_name_raises(self):
        """Registry.get with empty name raises SkillError."""
        reg = Registry(REG)
        with self.assertRaises(SkillError):
            reg.get("")

    def test_search_non_string_raises(self):
        """Registry.search with non-string raises SkillError."""
        reg = Registry(REG)
        with self.assertRaises(SkillError):
            reg.search(123)  # type: ignore[arg-type]

    def test_empty_search_returns_all_skills(self):
        """Empty query string returns all skills with score > 0."""
        reg = Registry(REG)
        results = reg.search("")
        self.assertTrue(len(results) > 0)


class TestResolveDepsHardening(unittest.TestCase):
    def test_empty_root_raises(self):
        """resolve_dependencies with empty root raises InstallError."""
        with self.assertRaises(InstallError):
            resolve_dependencies("", {})

    def test_unknown_root_raises(self):
        """resolve_dependencies with unknown root raises InstallError."""
        with self.assertRaises(InstallError):
            resolve_dependencies("ghost", {})


class TestLockfileHardening(unittest.TestCase):
    def test_corrupt_lockfile_recovered(self):
        """A lockfile with invalid JSON is silently replaced on next install."""
        with tempfile.TemporaryDirectory() as tmp:
            lp = os.path.join(tmp, ".skillhub-lock.json")
            with open(lp, "w") as fh:
                fh.write("NOT JSON {{{")
            reg = Registry(REG)
            result = reg.install("web-fetch", tmp)
            self.assertIn("web-fetch", result["installed"])

    def test_non_dict_lockfile_recovered(self):
        """A lockfile containing a JSON array is silently replaced on install."""
        with tempfile.TemporaryDirectory() as tmp:
            lp = os.path.join(tmp, ".skillhub-lock.json")
            with open(lp, "w") as fh:
                json.dump([1, 2, 3], fh)
            reg = Registry(REG)
            result = reg.install("web-fetch", tmp)
            self.assertIn("web-fetch", result["installed"])


class TestCliHardening(unittest.TestCase):
    def test_nonexistent_registry_exits_nonzero(self):
        """Passing a nonexistent registry path to list -> exit code 2."""
        rc = main(["list", "-r", "/does/not/exist"])
        self.assertEqual(rc, 2)

    def test_missing_skill_info_exits_nonzero(self):
        """info for a skill that does not exist -> exit code 2."""
        rc = main(["info", "no-such-skill", "-r", REG])
        self.assertEqual(rc, 2)

    def test_install_unknown_skill_exits_nonzero(self):
        """install of an unknown skill -> exit code 2."""
        with tempfile.TemporaryDirectory() as target:
            rc = main(["install", "ghost-skill", "-r", REG, "-t", target])
        self.assertEqual(rc, 2)

    def test_remove_uninstalled_skill_exits_nonzero(self):
        """remove of a skill that is not installed -> exit code 2."""
        with tempfile.TemporaryDirectory() as target:
            rc = main(["remove", "web-fetch", "-t", target])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()

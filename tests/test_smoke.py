"""Smoke tests for SKILLHUB. Standard library only, no network."""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from skillhub import TOOL_NAME, TOOL_VERSION, parse_manifest  # noqa: E402
from skillhub.core import (  # noqa: E402
    InstallError,
    ManifestError,
    Registry,
    resolve_dependencies,
)
from skillhub.cli import main  # noqa: E402

REG = os.path.join(os.path.dirname(__file__), "..", "demos", "01-basic", "registry")


def _mk_skill(tmp, name, version, requires=None):
    d = os.path.join(tmp, name)
    os.makedirs(d, exist_ok=True)
    req = "requires: [%s]\n" % ", ".join(requires) if requires else ""
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as fh:
        fh.write(
            "---\nname: %s\nversion: %s\ndescription: test %s\n%s---\nbody\n"
            % (name, version, name, req)
        )
    return d


class TestManifest(unittest.TestCase):
    def test_parse_ok(self):
        meta, body = parse_manifest(
            "---\nname: a\nversion: 1.2.3\ndescription: x\ntags: [t1, t2]\n---\nhi"
        )
        self.assertEqual(meta["name"], "a")
        self.assertEqual(meta["tags"], ["t1", "t2"])
        self.assertEqual(body, "hi")

    def test_missing_field(self):
        with self.assertRaises(ManifestError):
            parse_manifest("---\nname: a\nversion: 1.0.0\n---\nbody")

    def test_bad_version(self):
        with self.assertRaises(ManifestError):
            parse_manifest("---\nname: a\nversion: 1.0\ndescription: x\n---\nb")

    def test_no_fence(self):
        with self.assertRaises(ManifestError):
            parse_manifest("name: a\n")


class TestRegistry(unittest.TestCase):
    def test_load_and_search(self):
        reg = Registry(REG)
        skills = reg.skills()
        self.assertIn("summarize", skills)
        self.assertIn("web-fetch", skills)
        ranked = reg.search("summarize")
        self.assertTrue(ranked)
        self.assertEqual(ranked[0][0].name, "summarize")

    def test_dependency_order(self):
        reg = Registry(REG)
        order = resolve_dependencies("summarize", reg.skills())
        self.assertLess(order.index("web-fetch"), order.index("summarize"))

    def test_missing_dep(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            _mk_skill(tmp, "alpha", "1.0.0", requires=["ghost"])
            reg = Registry(tmp)
            with self.assertRaises(InstallError):
                resolve_dependencies("alpha", reg.skills())

    def test_cycle_detection(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            _mk_skill(tmp, "a", "1.0.0", requires=["b"])
            _mk_skill(tmp, "b", "1.0.0", requires=["a"])
            reg = Registry(tmp)
            with self.assertRaises(InstallError):
                resolve_dependencies("a", reg.skills())


class TestInstall(unittest.TestCase):
    def test_install_idempotent_and_remove(self):
        import tempfile
        reg = Registry(REG)
        with tempfile.TemporaryDirectory() as target:
            r1 = reg.install("summarize", target)
            self.assertIn("web-fetch", r1["installed"])
            self.assertIn("summarize", r1["installed"])
            self.assertTrue(os.path.isdir(os.path.join(target, "web-fetch")))

            r2 = reg.install("summarize", target)
            self.assertEqual(r2["installed"], [])
            self.assertIn("summarize", r2["skipped"])

            with self.assertRaises(InstallError):
                reg.remove("web-fetch", target)  # still required

            reg.remove("summarize", target)
            reg.remove("web-fetch", target)
            self.assertEqual(reg.installed(target), {})


class TestCli(unittest.TestCase):
    def test_version(self):
        self.assertEqual(TOOL_NAME, "skillhub")
        self.assertTrue(TOOL_VERSION)

    def test_list_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "json", "list", "-r", REG])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        names = {d["name"] for d in data}
        self.assertIn("summarize", names)

    def test_search_miss_nonzero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "json", "search", "zzz-nope", "-r", REG])
        self.assertEqual(rc, 1)

    def test_info_install_order(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "json", "info", "summarize", "-r", REG])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["install_order"][0], "web-fetch")

    def test_install_cli_roundtrip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as target:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["--format", "json", "install", "summarize",
                           "-r", REG, "-t", target])
            self.assertEqual(rc, 0)
            rep = json.loads(buf.getvalue())
            self.assertIn("summarize", rep["installed"])

    def test_unknown_skill_nonzero(self):
        rc = main(["info", "does-not-exist", "-r", REG])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()

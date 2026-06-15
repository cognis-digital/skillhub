"""Core engine for SKILLHUB.

A skill is a directory containing a ``SKILL.md`` manifest with a YAML-ish
front-matter header (a small, dependency-free subset we parse by hand) plus the
skill body. The registry is a directory of such skill folders. Installation
copies a skill (and its dependencies) into a target agent skills directory and
records the installation in a lockfile so repeated installs are idempotent.

Everything here is real logic: manifest parsing, semver-ish version comparison,
topological dependency resolution with cycle detection, content hashing for
integrity, search/ranking, and atomic-ish copy install.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Tuple

MANIFEST_NAME = "SKILL.md"
LOCKFILE_NAME = ".skillhub-lock.json"
_REQUIRED_FIELDS = ("name", "version", "description")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

logger = logging.getLogger(__name__)


class SkillError(Exception):
    """Base class for all skillhub errors."""


class ManifestError(SkillError):
    """Raised when a SKILL.md manifest is malformed."""


class InstallError(SkillError):
    """Raised when installation fails."""


def parse_version(v: str) -> Tuple[int, int, int]:
    m = _VERSION_RE.match(v.strip())
    if not m:
        raise ManifestError(f"invalid version (need MAJOR.MINOR.PATCH): {v!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _parse_scalar(raw: str):
    raw = raw.strip()
    if not raw:
        return ""
    if raw[0] in "\"'" and raw[-1:] == raw[0]:
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        items = []
        for part in inner.split(","):
            part = part.strip()
            if part[:1] in "\"'" and part[-1:] == part[:1]:
                part = part[1:-1]
            if part:
                items.append(part)
        return items
    return raw


def parse_manifest(text: str) -> Tuple[Dict[str, object], str]:
    """Parse a SKILL.md manifest.

    Format: a ``---`` fenced front-matter block of ``key: value`` lines,
    followed by the free-form body. Returns ``(metadata, body)``.
    """
    if not isinstance(text, str):
        raise ManifestError("manifest text must be a string")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ManifestError("manifest must start with a '---' front-matter fence")
    meta: Dict[str, object] = {}
    body_start = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            body_start = i + 1
            break
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ManifestError(f"malformed front-matter line: {line!r}")
        key, _, value = line.partition(":")
        meta[key.strip()] = _parse_scalar(value)
    if body_start is None:
        raise ManifestError("front-matter fence was never closed with '---'")

    for fld in _REQUIRED_FIELDS:
        if fld not in meta or meta[fld] == "":
            raise ManifestError(f"missing required field: {fld!r}")
    if not isinstance(meta["name"], str) or not _NAME_RE.match(meta["name"]):
        raise ManifestError(f"invalid skill name: {meta.get('name')!r}")
    parse_version(str(meta["version"]))  # validate

    deps = meta.get("requires", [])
    if isinstance(deps, str):
        deps = [deps] if deps else []
    meta["requires"] = list(deps)
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [tags] if tags else []
    meta["tags"] = list(tags)

    body = "\n".join(lines[body_start:]).strip()
    return meta, body


def _hash_dir(path: str) -> str:
    h = hashlib.sha256()
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for fname in sorted(files):
            fp = os.path.join(root, fname)
            rel = os.path.relpath(fp, path).replace(os.sep, "/")
            h.update(rel.encode("utf-8"))
            try:
                with open(fp, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
            except OSError as exc:
                logger.warning("skipping unreadable file in hash: %s: %s", fp, exc)
    return h.hexdigest()


@dataclass
class Skill:
    name: str
    version: str
    description: str
    requires: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    author: str = ""
    path: str = ""
    body: str = ""

    @property
    def version_tuple(self) -> Tuple[int, int, int]:
        return parse_version(self.version)

    def content_hash(self) -> str:
        if self.path and os.path.isdir(self.path):
            return _hash_dir(self.path)
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, object]:
        d = asdict(self)
        d.pop("body", None)
        return d

    @classmethod
    def from_dir(cls, path: str) -> "Skill":
        manifest_path = os.path.join(path, MANIFEST_NAME)
        if not os.path.isfile(manifest_path):
            raise ManifestError(f"no {MANIFEST_NAME} in {path}")
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            raise ManifestError(
                f"cannot read manifest {manifest_path}: {exc}"
            ) from exc
        except UnicodeDecodeError as exc:
            raise ManifestError(
                f"manifest is not valid UTF-8: {manifest_path}: {exc}"
            ) from exc
        meta, body = parse_manifest(raw)
        return cls(
            name=str(meta["name"]),
            version=str(meta["version"]),
            description=str(meta["description"]),
            requires=list(meta.get("requires", [])),  # type: ignore[arg-type]
            tags=list(meta.get("tags", [])),  # type: ignore[arg-type]
            author=str(meta.get("author", "")),
            path=path,
            body=body,
        )


def resolve_dependencies(
    root: str, available: Dict[str, Skill]
) -> List[str]:
    """Return install order (deps first) for ``root`` via DFS topo-sort.

    Raises InstallError on a missing dependency or a dependency cycle.
    """
    if not root or not isinstance(root, str):
        raise InstallError(
            f"root skill name must be a non-empty string, got {root!r}"
        )
    if root not in available:
        raise InstallError(f"skill not found: {root!r}")

    order: List[str] = []
    visiting: set = set()
    done: set = set()

    def visit(name: str, trail: Tuple[str, ...]) -> None:
        if name in done:
            return
        if name in visiting:
            cycle = " -> ".join(trail + (name,))
            raise InstallError(f"dependency cycle detected: {cycle}")
        if name not in available:
            raise InstallError(
                f"missing dependency {name!r} "
                f"(required by {trail[-1] if trail else 'root'})"
            )
        visiting.add(name)
        for dep in available[name].requires:
            visit(dep, trail + (name,))
        visiting.discard(name)
        done.add(name)
        order.append(name)

    visit(root, ())
    return order


class Registry:
    """A directory of skill folders."""

    def __init__(self, path: str):
        if not path or not isinstance(path, str):
            raise SkillError(
                f"registry path must be a non-empty string, got {path!r}"
            )
        self.path = os.path.abspath(path)

    def _ensure(self) -> None:
        if not os.path.isdir(self.path):
            raise SkillError(f"registry path does not exist: {self.path}")

    def skills(self) -> Dict[str, Skill]:
        """Load every valid skill in the registry, keyed by name."""
        self._ensure()
        out: Dict[str, Skill] = {}
        for entry in sorted(os.listdir(self.path)):
            d = os.path.join(self.path, entry)
            if not os.path.isdir(d):
                continue
            if not os.path.isfile(os.path.join(d, MANIFEST_NAME)):
                continue
            try:
                sk = Skill.from_dir(d)
            except ManifestError as exc:
                logger.warning("skipping invalid skill %r: %s", d, exc)
                continue
            if sk.name in out:
                # keep the higher version
                if sk.version_tuple <= out[sk.name].version_tuple:
                    continue
            out[sk.name] = sk
        return out

    def get(self, name: str) -> Skill:
        if not name or not isinstance(name, str):
            raise SkillError(
                f"skill name must be a non-empty string, got {name!r}"
            )
        skills = self.skills()
        if name not in skills:
            raise SkillError(f"skill not found in registry: {name!r}")
        return skills[name]

    def search(self, query: str) -> List[Tuple[Skill, int]]:
        """Rank skills by relevance to ``query``. Returns (skill, score)."""
        if not isinstance(query, str):
            raise SkillError(f"search query must be a string, got {query!r}")
        q = query.lower().strip()
        terms = [t for t in re.split(r"\s+", q) if t]
        results: List[Tuple[Skill, int]] = []
        for sk in self.skills().values():
            score = 0
            hay_name = sk.name.lower()
            hay_desc = sk.description.lower()
            hay_tags = [t.lower() for t in sk.tags]
            for term in terms:
                if term == hay_name:
                    score += 100
                elif term in hay_name:
                    score += 40
                if term in hay_tags:
                    score += 25
                if term in hay_desc:
                    score += 10
            if not terms:
                score = 1
            if score > 0:
                results.append((sk, score))
        results.sort(key=lambda r: (-r[1], r[0].name))
        return results

    # ----- installation -----

    @staticmethod
    def _load_lock(target: str) -> Dict[str, object]:
        lp = os.path.join(target, LOCKFILE_NAME)
        if os.path.isfile(lp):
            with open(lp, "r", encoding="utf-8") as fh:
                try:
                    data = json.load(fh)
                    if not isinstance(data, dict):
                        raise ValueError("lockfile root must be a JSON object")
                    return data
                except (json.JSONDecodeError, ValueError, OSError) as exc:
                    logger.warning(
                        "lockfile %s is corrupt or unreadable (%s); starting fresh",
                        lp, exc,
                    )
                    return {"installed": {}}
        return {"installed": {}}

    @staticmethod
    def _save_lock(target: str, lock: Dict[str, object]) -> None:
        lp = os.path.join(target, LOCKFILE_NAME)
        try:
            with open(lp, "w", encoding="utf-8") as fh:
                json.dump(lock, fh, indent=2, sort_keys=True)
        except OSError as exc:
            raise InstallError(f"cannot write lockfile {lp}: {exc}") from exc

    def install(
        self, name: str, target: str, force: bool = False
    ) -> Dict[str, object]:
        """Install ``name`` and its dependencies into ``target``.

        Idempotent: a skill already present at the same content hash is
        skipped unless ``force`` is set. Returns an install report.
        """
        available = self.skills()
        if name not in available:
            raise InstallError(f"skill not found in registry: {name!r}")
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as exc:
            raise InstallError(
                f"cannot create target directory {target!r}: {exc}"
            ) from exc
        order = resolve_dependencies(name, available)
        lock = self._load_lock(target)
        installed = lock.setdefault("installed", {})  # type: ignore[assignment]

        report = {"target": os.path.abspath(target), "installed": [],
                  "skipped": [], "order": order}
        for sk_name in order:
            sk = available[sk_name]
            digest = sk.content_hash()
            dest = os.path.join(target, sk_name)
            prev = installed.get(sk_name)  # type: ignore[union-attr]
            if (
                not force
                and isinstance(prev, dict)
                and prev.get("hash") == digest
                and os.path.isdir(dest)
            ):
                report["skipped"].append(sk_name)  # type: ignore[union-attr]
                continue
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            try:
                shutil.copytree(sk.path, dest)
            except OSError as exc:
                raise InstallError(
                    f"failed to copy skill {sk_name!r} to {dest!r}: {exc}"
                ) from exc
            installed[sk_name] = {  # type: ignore[index]
                "version": sk.version,
                "hash": digest,
                "requires": sk.requires,
            }
            report["installed"].append(sk_name)  # type: ignore[union-attr]
        self._save_lock(target, lock)
        return report

    def installed(self, target: str) -> Dict[str, object]:
        if not target or not isinstance(target, str):
            raise SkillError(
                f"target must be a non-empty string, got {target!r}"
            )
        lock = self._load_lock(target)
        return dict(lock.get("installed", {}))  # type: ignore[arg-type]

    def remove(self, name: str, target: str) -> Dict[str, object]:
        """Remove an installed skill. Refuses if another skill still needs it."""
        lock = self._load_lock(target)
        installed = lock.setdefault("installed", {})  # type: ignore[assignment]
        if name not in installed:  # type: ignore[operator]
            raise InstallError(f"skill not installed: {name!r}")
        dependents = [
            other
            for other, meta in installed.items()  # type: ignore[union-attr]
            if other != name and name in (meta or {}).get("requires", [])
        ]
        if dependents:
            raise InstallError(
                f"cannot remove {name!r}; still required by: "
                + ", ".join(sorted(dependents))
            )
        dest = os.path.join(target, name)
        if os.path.isdir(dest):
            try:
                shutil.rmtree(dest)
            except OSError as exc:
                raise InstallError(
                    f"failed to remove skill directory {dest!r}: {exc}"
                ) from exc
        del installed[name]  # type: ignore[union-attr]
        self._save_lock(target, lock)
        return {"removed": name, "target": os.path.abspath(target)}

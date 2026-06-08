"""SKILLHUB - Local skill registry and installer for AI agents.

A zero-install, standard-library-only tool that manages a local registry of
"skills" (reusable agent capabilities packaged as directories with a manifest)
and installs them into an agent's skills directory.

Spiritual sibling of ClawHub: ride the viral skills-registry pattern, but fully
local and dependency-free.
"""

from skillhub.core import (
    Registry,
    Skill,
    SkillError,
    ManifestError,
    InstallError,
    parse_manifest,
    resolve_dependencies,
)

TOOL_NAME = "skillhub"
TOOL_VERSION = "1.0.0"

__all__ = [
    "Registry",
    "Skill",
    "SkillError",
    "ManifestError",
    "InstallError",
    "parse_manifest",
    "resolve_dependencies",
    "TOOL_NAME",
    "TOOL_VERSION",
]

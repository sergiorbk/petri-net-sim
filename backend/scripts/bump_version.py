#!/usr/bin/env python3
"""Bump this project's version number across every source of truth.

There are four independent places that state the release number (see
backend/tests/test_version_alignment.py's docstring for why there are four,
not one): frontend/package.json, backend/pyproject.toml,
Settings.APP_VERSION's default in backend/src/core/config.py, and
PETRI_NET_SIM_VERSION in backend/src/services/petri/exporter/toolspecific.py.
Two golden PNML fixtures embed the version string too (it appears in every
``toolspecific`` block they contain), and frontend/src/lib/pnml-export.test.ts
hardcodes it twice more, pinned byte-for-byte rather than read from
package.json like the rest of that file. A version bump has to touch all of
these together or the release ships mismatched, which is exactly what
test_version_alignment.py exists to catch: this script runs that same test
against itself before exiting successfully, so a bug here fails loudly
instead of shipping a mismatch anyway.

Usage (run from anywhere, needs the backend venv active or invoked via it):
    python backend/scripts/bump_version.py 1.1.0

This is exactly the command a human doing a manual bump would run; the
``bump-version.yml`` GitHub Actions workflow calls the same script with the
same argument, then runs `npm install` / `uv lock` to refresh the lockfiles
and the full test suites as a merge gate, and only then commits and tags,
none of which this script does itself. This script's job stops at "every
source file that states the version now agrees with itself and with what the
exporters actually emit."

Prerequisites this script assumes are already met (it does not install
anything, to stay side-effect-free about dependencies):
  - The backend venv it is run with has the project's dependencies installed
    (it imports backend/src directly, in-process, to regenerate the Python
    golden fixture).
  - frontend/node_modules exists (`npm install` has been run at least once),
    so vite-node and vitest are available to regenerate and self-check the
    TypeScript golden fixture. See regenerate-composed-fixture.ts, this
    script's frontend-side sibling.

``--repo-root`` lets this be pointed at a scratch copy of the repository
instead of the one this script itself lives in, so the script can be
verified end-to-end (bump, regenerate, self-check) without ever touching the
real working tree's version. The Python interpreter running this script
(sys.executable) is used as-is for the backend self-check regardless of
--repo-root, so a scratch copy needs no venv of its own. frontend/node_modules
is a different story: vite-node has to load the real vite.config.ts to get
the "@" alias pnml-export-composed.ts genuinely depends on, and that config
imports real plugin packages, so --repo-root's own frontend/node_modules has
to exist too. A scratch copy therefore needs one, cheaply, without a real
`npm install`: a directory junction or symlink onto an already-installed
frontend/node_modules works, since nothing here writes into it.
"""

from __future__ import annotations

import argparse
import platform
import re
import subprocess
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# Where this script itself lives: the default --repo-root when none is given.
_TOOLING_ROOT = Path(__file__).resolve().parent.parent.parent


class BumpError(RuntimeError):
    """A version bump step failed in a way the caller needs to see clearly."""


def _read(path: Path) -> str:
    if not path.is_file():
        raise BumpError(f"expected a file at {path}, found none")
    return path.read_text(encoding="utf-8")


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _replace_exactly_once(path: Path, pattern: str, replacement: str) -> None:
    text = _read(path)
    new_text, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise BumpError(
            f"expected exactly one match for {pattern!r} in {path}, found {count} "
            "(has the surrounding source moved since this script was written?)"
        )
    _write(path, new_text)


def _current_frontend_version(repo_root: Path) -> str:
    package_json = repo_root / "frontend" / "package.json"
    text = _read(package_json)
    match = re.search(r'"version":\s*"(\d+\.\d+\.\d+)"', text)
    if not match:
        raise BumpError(f'could not find a "version": "X.Y.Z" field in {package_json}')
    return match.group(1)


# ---------------------------------------------------------------------------
# Step 1: the four literal sources of truth
# ---------------------------------------------------------------------------


def bump_frontend_package_json(repo_root: Path, old: str, new: str) -> None:
    path = repo_root / "frontend" / "package.json"
    _replace_exactly_once(path, rf'"version": "{re.escape(old)}"', f'"version": "{new}"')


def bump_backend_pyproject(repo_root: Path, old: str, new: str) -> None:
    path = repo_root / "backend" / "pyproject.toml"
    _replace_exactly_once(
        path, rf'(?m)^version = "{re.escape(old)}"$', f'version = "{new}"'
    )


def bump_toolspecific_version(repo_root: Path, old: str, new: str) -> None:
    path = repo_root / "backend" / "src" / "services" / "petri" / "exporter" / "toolspecific.py"
    _replace_exactly_once(
        path,
        rf'PETRI_NET_SIM_VERSION = "{re.escape(old)}"',
        f'PETRI_NET_SIM_VERSION = "{new}"',
    )


def bump_app_version_default(repo_root: Path, old: str, new: str) -> None:
    path = repo_root / "backend" / "src" / "core" / "config.py"
    _replace_exactly_once(
        path,
        rf'APP_VERSION: str = Field\(default="{re.escape(old)}"\)',
        f'APP_VERSION: str = Field(default="{new}")',
    )


# ---------------------------------------------------------------------------
# Step 2: the two hardcoded literals in the frontend export test
# ---------------------------------------------------------------------------


def bump_pnml_export_test_literals(repo_root: Path, old: str, new: str) -> None:
    """The flat-export "pinned byte-for-byte" test in pnml-export.test.ts
    hardcodes ``version="X.Y.Z"`` twice instead of reading pkg.version like
    every other assertion in that file (deliberately: that test pins an
    exact document, so it does not want to silently track a version bump the
    way the rest of the suite does). Those two spots have to move by hand
    on every bump, which is exactly why this script exists to do it."""
    path = repo_root / "frontend" / "src" / "lib" / "pnml-export.test.ts"
    text = _read(path)
    pattern = rf'tool="PetriNetSim" version="{re.escape(old)}"'
    new_text, count = re.subn(pattern, f'tool="PetriNetSim" version="{new}"', text)
    if count != 2:
        raise BumpError(
            f"expected exactly 2 hardcoded PetriNetSim version literals in {path}, "
            f"found {count}"
        )
    _write(path, new_text)


# ---------------------------------------------------------------------------
# Step 3: regenerate the two golden PNML fixtures by running the actual
# exporters, not by hand-editing XML.
# ---------------------------------------------------------------------------


def regenerate_backend_fixture(repo_root: Path) -> None:
    """Runs the Python ComposedPNMLExporter in-process against the same §7
    worked example backend/tests/test_composed_pnml_exporter.py's
    ``pipeline_demo_model`` fixture builds, and writes the result over
    backend/tests/fixtures/composed_conformant_v21.pnml.

    Imported fresh (old ``src.*`` modules evicted from sys.modules first) so
    this always reads the just-bumped PETRI_NET_SIM_VERSION off disk, never a
    stale cached one from an earlier version's import in the same process.
    """
    backend_dir = repo_root / "backend"
    backend_str = str(backend_dir)
    if backend_str not in sys.path:
        sys.path.insert(0, backend_str)
    for mod_name in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
        del sys.modules[mod_name]

    from src.domain.composed import ComposedModel, LinkType
    from src.domain.models import PetriNet
    from src.services.petri.exporter import ComposedPNMLExporter

    model = ComposedModel(name="PipelineDemo")

    generator = PetriNet(name="Generator")
    generator.add_place("Pool", tokens=5, x=60, y=80, place_id="p_pool")
    generator.add_place("Ready", tokens=0, x=200, y=80, place_id="p_ready")
    generator.add_place("Log", tokens=0, x=200, y=200, place_id="p_log")
    generator.add_transition(
        "Generate", mean_delay=1.0, distribution="det", x=130, y=80, transition_id="t_gen"
    )
    generator.add_arc("p_pool", "t_gen", arc_id="a_g1")
    generator.add_arc("t_gen", "p_ready", arc_id="a_g2")
    generator.add_arc("t_gen", "p_log", arc_id="a_g3")

    server = PetriNet(name="Server")
    server.add_place("In", tokens=0, x=60, y=80, place_id="p_in")
    server.add_place("Busy", tokens=0, x=200, y=80, place_id="p_busy")
    server.add_place("Done", tokens=0, x=340, y=80, place_id="p_done")
    server.add_transition(
        "Start", mean_delay=2.0, distribution="exp", x=130, y=80, transition_id="t_start"
    )
    server.add_transition(
        "End", mean_delay=3.0, distribution="det", x=270, y=80, transition_id="t_end"
    )
    server.add_arc("p_in", "t_start", arc_id="a_s1")
    server.add_arc("t_start", "p_busy", arc_id="a_s2")
    server.add_arc("p_busy", "t_end", arc_id="a_s3")
    server.add_arc("t_end", "p_done", arc_id="a_s4")

    model.add_object(generator, name="Generator", priority=1, x=40, y=60)
    model.add_object(server, name="Server", priority=0, x=360, y=60)

    # L0: fusion on object0's MIDDLE place slot (index 1), the off-by-one detector.
    model.add_link(
        LinkType.PLACE_FUSION, source_object=0, source_element=1, target_object=1, target_element=0
    )
    model.add_link(
        LinkType.TRANSITION_TO_PLACE,
        source_object=1,
        source_element=0,
        target_object=0,
        target_element=2,
        quantity=2,
    )

    xml = ComposedPNMLExporter().export(model)
    fixture_path = backend_dir / "tests" / "fixtures" / "composed_conformant_v21.pnml"
    fixture_path.write_text(xml, encoding="utf-8")
    print(f"Wrote {fixture_path}")


def _node_bin(repo_root: Path, name: str) -> Path:
    """Resolves an npm-installed binary from repo_root's own frontend/node_modules.

    vite-node has to auto-load the app's real vite.config.ts to pick up the
    "@" alias (pnml-export-composed.ts has a real, non-type-only import that
    depends on it), and that config imports its plugins (@vitejs/plugin-react,
    @tailwindcss/vite), which means repo_root's own frontend/node_modules has
    to genuinely exist, not just the tooling that lives in it. For the real
    repository that is `npm install`'s job. A --repo-root scratch copy has no
    node_modules of its own by default; verifying the script against one
    therefore means pointing (or linking) one at an already-installed
    frontend/node_modules first, e.g. a directory junction on Windows
    (`New-Item -ItemType Junction`) or a symlink elsewhere, rather than
    reinstalling hundreds of megabytes of dependencies for a throwaway check.
    """
    bin_dir = repo_root / "frontend" / "node_modules" / ".bin"
    exe = f"{name}.cmd" if platform.system() == "Windows" else name
    path = bin_dir / exe
    if not path.exists():
        raise BumpError(
            f"{path} not found; run `npm install` in {repo_root / 'frontend'} first "
            f"(bump_version.py needs {name}, a frontend devDependency, to run the actual "
            "TypeScript exporter rather than hand-editing its fixture)."
        )
    return path


def regenerate_frontend_fixture(repo_root: Path) -> None:
    """Shells out to vite-node to run the real TypeScript exportComposedPnml
    (see regenerate-composed-fixture.ts for why this has to be a subprocess
    rather than an in-process call: this is a Python script). Executed with
    cwd set to repo_root's frontend/ so vite-node picks up that tree's
    vite.config.ts (for the "@" alias), that tree's package.json (for the
    version the fixture should embed), and writes into that tree's own
    fixtures directory (regenerate-composed-fixture.ts resolves its output
    path relative to its own file location).
    """
    vite_node = _node_bin(repo_root, "vite-node")
    frontend_dir = repo_root / "frontend"
    script = frontend_dir / "scripts" / "regenerate-composed-fixture.ts"
    if not script.is_file():
        raise BumpError(f"expected {script} to exist (it ships with the repo)")
    result = subprocess.run(
        [str(vite_node), str(script)],
        cwd=frontend_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BumpError(
            "regenerating the frontend golden fixture failed:\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
    print(result.stdout.strip())


# ---------------------------------------------------------------------------
# Step 4: self-verify. Exits nonzero (via BumpError -> non-zero process exit)
# on any mismatch, rather than leaving a silently broken bump for CI or a
# human to discover later.
# ---------------------------------------------------------------------------


def self_verify(repo_root: Path) -> None:
    backend_dir = repo_root / "backend"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_version_alignment.py",
            "tests/test_composed_pnml_exporter.py",
            "-q",
            "--no-cov",
        ],
        cwd=backend_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BumpError(
            "self-verify failed: backend version-alignment / golden-fixture tests did "
            f"not pass after the bump.\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
    print(result.stdout.strip())

    vitest = _node_bin(repo_root, "vitest")
    frontend_dir = repo_root / "frontend"
    result = subprocess.run(
        [str(vitest), "run", "src/lib/pnml-export.test.ts"],
        cwd=frontend_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BumpError(
            "self-verify failed: frontend pnml-export.test.ts did not pass after the "
            f"bump.\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
    print(result.stdout.strip())


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def bump(new_version: str, repo_root: Path) -> None:
    old_version = _current_frontend_version(repo_root)
    if old_version == new_version:
        raise BumpError(f"already at version {new_version}, nothing to bump")

    print(f"Bumping {old_version} -> {new_version} in {repo_root}")

    bump_frontend_package_json(repo_root, old_version, new_version)
    bump_backend_pyproject(repo_root, old_version, new_version)
    bump_toolspecific_version(repo_root, old_version, new_version)
    bump_app_version_default(repo_root, old_version, new_version)
    bump_pnml_export_test_literals(repo_root, old_version, new_version)

    regenerate_backend_fixture(repo_root)
    regenerate_frontend_fixture(repo_root)

    self_verify(repo_root)

    print(f"Done: every version source now agrees on {new_version}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", help='New version, e.g. "1.1.0" (three dot-separated integers).')
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help=(
            "Repository root to edit (default: the repository this script lives in). "
            "Point this at a scratch copy to verify the script without touching the "
            "real working tree's version."
        ),
    )
    args = parser.parse_args(argv)

    if not VERSION_RE.match(args.version):
        parser.error(f'version must look like "X.Y.Z" (three dot-separated integers), got {args.version!r}')

    repo_root = (args.repo_root or _TOOLING_ROOT).resolve()

    try:
        bump(args.version, repo_root)
    except BumpError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

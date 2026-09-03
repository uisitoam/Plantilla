# Renaming the package

`src/implacost/` is not just a folder. It is an importable package whose name
appears in every import statement, in the build configuration, in the console
script definitions, in the coverage and dependency tooling, and in the prefix for
environment variables. Renaming the directory alone leaves a project that will
not import.

Below, `implacost` is the old name and `newname` the new one.

## Two names, not one

They are allowed to differ, and knowing which is which saves confusion:

| | Where | Constraint |
|---|---|---|
| **Distribution name** | `[project] name` in `pyproject.toml` | May contain hyphens: `my-project` |
| **Import name** | the `src/implacost/` directory | Must be a Python identifier: `my_project` |

If you want hyphens in the distribution name, the package directory still has to
use underscores. `importlib.metadata.version()` takes the *distribution* name.

## The steps

### 1. Move the directory

```bash
git mv src/implacost src/newname
```

### 2. Rewrite the references

Imports are absolute throughout — relative imports to parent packages are banned
by a lint rule — so every module refers to the package by name. Save this as
`rename.py` at the repository root and run it once:

```python
"""Rewrite every reference to the package name. Usage: python rename.py old new"""

import pathlib
import subprocess
import sys

if len(sys.argv) != 3:
    raise SystemExit("Usage: python rename.py old new")

OLD, NEW = sys.argv[1], sys.argv[2]
SUFFIXES = {".py", ".toml", ".yaml", ".yml", ".md", ".example", ".txt", ".cfg", ".json"}
SKIP = {"CHANGELOG.md", "uv.lock", "rename.py"}

listed = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)

for name in listed.stdout.split():
    path = pathlib.Path(name)

    if path.name in SKIP or (path.suffix not in SUFFIXES and path.name != "justfile"):
        continue

    if not path.exists() or not path.is_file():
        print("skipped missing/non-file", name)
        continue

    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        print("skipped unreadable", name, exc)
        continue

    updated = text.replace(OLD, NEW).replace(OLD.upper(), NEW.upper())
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        print("updated", name)
```

```bash
python rename.py implacost newname && rm rename.py
```

Driving it from `git ls-files` is what keeps it away from `.venv/`, the caches and
anything else untracked. It also handles the `IMPLACOST_` environment prefix in
the same pass, and catches two references that a search for `import` would miss:
the module paths passed as *strings* to `monkeypatch.setattr` in the tests, and
the `--cov=implacost` argument in `pyproject.toml`.

A `sed`-and-`xargs` one-liner is the obvious alternative and is worth avoiding:
the flags differ between macOS and Linux, and if it dies partway through — a long
file list is enough — you are left with a half-renamed repository, which is a
worse position than not having started.

### 3. Check what the rewrite touched

The command above is broad on purpose, so read the diff before trusting it:

```bash
git diff --stat
git diff pyproject.toml configs/config.yaml
```

In `pyproject.toml`, these five must all have changed — each one fails in a
different way if it did not:

```toml
[project]
name = "newname"                                    # the distribution

[project.scripts]
newname-etl = "newname.cli.etl:main"                # the console scripts
newname-train = "newname.cli.train:main"

[tool.hatch.build.targets.wheel]
packages = ["src/newname"]                          # what gets built

[tool.pytest.ini_options]
addopts = ["--cov=newname", ...]                    # coverage measures nothing without this

[tool.coverage.run]
source = ["src/newname"]

[tool.deptry]
known_first_party = ["newname"]                     # or your own imports look undeclared
```

The metadata that is *not* a name still wants attention, since the script cannot
guess at it: `authors`, `description`, the `[project.urls]` block, and the
licence. `LICENSE` ships as MIT with a placeholder copyright holder, and
`Private :: Do Not Upload` in `classifiers` blocks an accidental publish — remove
it deliberately if you intend to release.

And in `configs/config.yaml`, decide whether these two should follow the package
name or stay as they are — they are labels, not identifiers:

```yaml
project_name: newname
wandb:
  project: newname      # renaming this starts a new project in the W&B UI
```

Pointing at a new W&B project means existing runs stay under the old one. That is
usually what you want when a project is genuinely new, and not what you want if
you are only tidying a name.

### 4. Reinstall

The old distribution is installed in editable mode, so its metadata and console
scripts survive a plain `uv sync`. Replace the environment:

```bash
rm -rf .venv
uv sync
```

### 5. Verify

```bash
uv run python -c "import newname; print(newname.__version__, newname.PROJECT_ROOT)"
uv run newname-etl
just check
```

The whole sequence has been run against a copy of this repository: it ends with
`just check` green and all tests passing, so a failure here means a step was
skipped rather than that the procedure is incomplete.

The first line is the one that matters. If `__version__` prints `0.0.0.dev0`, the
distribution name in `pyproject.toml` does not match what
`importlib.metadata.version()` is asked for in `src/newname/__init__.py`. That
mismatch **fails silently** — the lookup is wrapped in a `try` so that running
from a raw checkout works — so nothing else will tell you.

### 6. Clean up the leftovers

```bash
just clean
git status   # stale __pycache__ or .egg-info from the old name
```

## Things that do not need changing

**`PROJECT_ROOT`.** It is `Path(__file__).resolve().parents[2]`, counting
directory levels rather than matching names, so `src/newname/config.py` resolves
to the repository root exactly as before. The depth only matters if you also move
the package to a different level in the tree.

**The `.env` file.** It is git-ignored and local. But the prefix inside it does
change: `IMPLACOST_WANDB__MODE` becomes `NEWNAME_WANDB__MODE`, matching
`env_prefix` in `config.py`. An old variable is not an error — it is simply
ignored, which is the failure mode the prefix exists to produce.

**`uv.lock`.** Regenerated by the `uv sync` in step 4.

**The repository directory and the git remote.** Independent of the package name.
Rename them if you like; nothing in the code reads either.

## The order matters in one place

Rename before you have runs and data you care about. After that point, a rename
also means a new W&B project, and any absolute path you have written down
elsewhere — a cluster job script, a bookmarked report — refers to
directories derived from the old layout.

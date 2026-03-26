from __future__ import annotations

import importlib.util
import inspect
import pathlib
import sys
import traceback


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TEST_ROOT = REPO_ROOT / "backend" / "tests"


def load_module(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "backend"))

    passed = 0
    failed = 0

    for path in sorted(TEST_ROOT.glob("test_*.py")):
        module = load_module(path)
        for name, obj in sorted(vars(module).items()):
            if not name.startswith("test_") or not callable(obj):
                continue
            if inspect.signature(obj).parameters:
                continue
            try:
                obj()
                passed += 1
            except Exception:  # pragma: no cover - CLI script
                failed += 1
                print(f"FAILED {path.name}::{name}", file=sys.stderr)
                traceback.print_exc()

    print(f"backend checks: passed={passed} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

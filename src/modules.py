# lang: Python 3, file: modules.py, target: all platforms
# plugin module scanner and injector

import os, ast

MODULE_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "src", "command", "modules")
_loaded_modules = {}


def scan_modules():
    _loaded_modules.clear()
    if not os.path.isdir(MODULE_DIR):
        print(f"[modules] dir not found: {MODULE_DIR}")
        return
    found = 0
    for fname in sorted(os.listdir(MODULE_DIR)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        path = os.path.join(MODULE_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()
            tree = ast.parse(src)
            meta = None
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name) and tgt.id == "META":
                            meta = ast.literal_eval(node.value)
            if meta and "name" in meta:
                _loaded_modules[meta["name"]] = {
                    "meta":   meta,
                    "source": src,
                    "path":   path,
                }
                found += 1
            else:
                print(f"[modules] skipped {fname}: no META dict with 'name' key")
        except Exception as e:
            print(f"[modules] parse error {fname}: {e}")
    print(f"[modules] loaded {found} module(s) from {MODULE_DIR}")


def build_module_injection(selected_names: list) -> str:
    parts = []
    for name in selected_names:
        entry = _loaded_modules.get(name)
        if not entry:
            continue
        src   = entry["source"]
        lines = []
        skip  = False
        for line in src.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("META"):
                skip = True
            if skip:
                if (not stripped.startswith("META")
                        and not stripped.startswith("#")
                        and line
                        and line[0] not in (" ", "\t", "}", "]", ")")
                        and stripped):
                    skip = False
                    lines.append(line)
                continue
            lines.append(line)
        body = "\n".join(lines)
        body = "\n" + body
        body = body.replace("\ndef run(",       f"\ndef _mod_{name}(")
        body = body.replace("\nasync def run(", f"\nasync def _mod_{name}(")
        parts.append(
            f"# module: {name}\n{body.strip()}\n_MODULES[{name!r}] = _mod_{name}\n"
        )
    return "\n".join(parts)


def get_loaded_modules() -> dict:
    return _loaded_modules
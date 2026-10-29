"""Apply Ruff formatting with the project's single-blank-line convention."""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "backend", ROOT / "scripts", ROOT / "docs/diagrams"]

def compact_sections(source):
    protected_lines = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Constant, ast.JoinedStr)) and isinstance(
            getattr(node, "value", ""), str
        ):
            protected_lines.update(range(node.lineno, node.end_lineno + 1))
    result = []
    for number, line in enumerate(source.splitlines(keepends=True), 1):
        if number not in protected_lines and not line.strip() and result and not result[-1].strip():
            continue
        result.append(line)
    formatted = "".join(result)
    if ast.dump(ast.parse(source)) != ast.dump(ast.parse(formatted)):
        raise ValueError("Formatting must not change the Python syntax tree.")
    return formatted

def main():
    checking = "--check" in sys.argv
    command = [sys.executable, "-m", "ruff", "check", *map(str, TARGETS)]
    if not checking:
        command.append("--fix")
    subprocess.run(command, check=True, cwd=ROOT)
    changed = []
    for directory in TARGETS:
        for path in sorted(directory.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text()
            process = subprocess.run(
                [sys.executable, "-m", "ruff", "format", "--stdin-filename", str(path), "-"],
                input=source,
                capture_output=True,
                text=True,
                check=True,
                cwd=ROOT,
            )
            formatted = compact_sections(process.stdout)
            if source != formatted:
                changed.append(str(path.relative_to(ROOT)))
                if not checking:
                    path.write_text(formatted)
    if checking and changed:
        raise SystemExit("Formatting needed: " + ", ".join(changed))
    print(
        f"Python formatting {'verified' if checking else 'applied'}; {len(changed)} files changed."
    )

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Render the Supervisor template with device-local paths outside the checkout."""

import argparse
import os
from pathlib import Path
import shlex
import tempfile


DEPLOY_DIR = Path(__file__).resolve().parent


def render_config(project_dir: Path) -> str:
    project_dir = project_dir.expanduser().resolve()
    # Supervisor treats comment markers specially even inside command quotes.
    if any(char in str(project_dir) for char in "\r\n;#"):
        raise ValueError("Project path must not contain newlines, ';' or '#'.")
    if not (project_dir / "main.py").is_file():
        raise ValueError(f"main.py not found in {project_dir}")
    python = project_dir / ".venv" / "bin" / "python"
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError(f"Python environment not found: {python}. Create .venv first.")

    template = (DEPLOY_DIR / "flesh.conf").read_text(encoding="utf-8")
    # Quote command arguments for Supervisor's shlex parser; escape INI interpolation.
    return template.replace(
        "@@PYTHON_COMMAND@@", shlex.quote(str(python)).replace("%", "%%")
    ).replace("@@PROJECT_DIR@@", str(project_dir).replace("%", "%%"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-dir", type=Path, default=DEPLOY_DIR.parent,
        help="Project directory (default: parent of this script's deploy directory).",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("/etc/supervisor/conf.d/flesh.conf"),
        help="Destination config file, outside the Git checkout by default.",
    )
    args = parser.parse_args()
    try:
        content = render_config(args.project_dir)
        output = args.output.expanduser().absolute()
        output.parent.mkdir(parents=True, exist_ok=True)
        # Replace atomically so an interrupted install cannot leave a partial config.
        fd, temporary = tempfile.mkstemp(prefix=".flesh-", dir=output.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as config_file:
                config_file.write(content)
                os.fchmod(config_file.fileno(), 0o644)
            os.replace(temporary, output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Installation failed: {error}\n")

    print(f"Installed {output}")
    print(f"Project: {args.project_dir.expanduser().resolve()}")
    print("Apply with: sudo supervisorctl reread && sudo supervisorctl update")


if __name__ == "__main__":
    main()

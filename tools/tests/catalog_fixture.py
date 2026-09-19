"""Fixed release-policy fixture, independent of the copyable example's version."""
from pathlib import Path
import shutil
import tomllib


def copy_example(destination):
    source = Path(__file__).resolve().parents[2] / 'examples/hello-vitrallis'
    shutil.copytree(source, destination)
    manifest = destination / 'app.toml'
    version = tomllib.loads(manifest.read_text())['version']
    manifest.write_text(manifest.read_text().replace(f'version = "{version}"', 'version = "0.1.0"'))
    (destination / 'CHANGELOG.md').write_text(
        '# Changelog\n\n## 0.1.0 — 2026-09-12\n\n- Add the offline greeting window and keyboard navigation.\n')

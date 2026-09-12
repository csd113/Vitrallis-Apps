#!/usr/bin/env python3
"""Validate pinned catalog sources and/or an unpublished native package offline."""
import argparse
from pathlib import Path
import subprocess
import sys

from catalog_lib import (Invalid, ROOT, load_json, local_files, manifest,
                         source_repositories, validate_sources)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, help='catalog file (default: repository apps.json)')
    parser.add_argument('--repo', type=Path, default=ROOT, help='Git object checkout (default: tool repository)')
    parser.add_argument('--source-repo', action='append', default=[], metavar='OWNER/REPO=PATH',
                        help='use another local checkout for this source repository; repeatable')
    parser.add_argument('--package', type=Path, action='append', default=[],
                        help='validate an unpublished package directory; repeatable')
    args = parser.parse_args(argv)
    try:
        mappings = source_repositories(args.source_repo)
        if args.catalog is not None or not args.package:
            path = args.catalog or ROOT / 'apps.json'
            catalog = load_json(path)
            validate_sources(catalog, args.repo, mappings)
            print(f'OK: {path} ({len(catalog["apps"])} apps; pinned bytes verified)')
        for path in args.package:
            package = manifest(local_files(path), path)
            print(f'OK: {path} ({package["id"]} {package["version"]}; manifest v1)')
    except (Invalid, OSError, ValueError, RecursionError, subprocess.SubprocessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

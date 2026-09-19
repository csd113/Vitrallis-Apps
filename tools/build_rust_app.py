#!/usr/bin/env python3
"""Stage experimental Rust payloads inside an unchanged manifest v1 package."""
import argparse
import ctypes as c
import os
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import tempfile
import tomllib

from catalog_lib import Invalid, read_file, regular_path, local_files, manifest, FILE_LIMIT

TARGETS = {'armv7-unknown-linux-gnueabihf', 'aarch64-unknown-linux-gnu', 'x86_64-unknown-linux-gnu'}


def validate_binary(payload, triple):
    elf_class, machine = {
        'armv7-unknown-linux-gnueabihf': (1, 40),
        'aarch64-unknown-linux-gnu': (2, 183),
        'x86_64-unknown-linux-gnu': (2, 62),
    }[triple]
    if (len(payload) < 64 or payload[:4] != b'\x7fELF'
            or payload[4:7] != bytes((elf_class, 1, 1))
            or struct.unpack_from('<H', payload, 18)[0] != machine):
        raise Invalid('Cargo output is not a matching little-endian Linux ELF executable')
    if machine == 40 and not struct.unpack_from('<I', payload, 36)[0] & 0x400:
        raise Invalid('ARM payload must use the hard-float ABI')


def publish_directory(source, destination):
    """Atomic no-replace rename; ordinary rename can replace an empty directory."""
    library = c.CDLL(None, use_errno=True)
    if sys.platform == 'darwin' and hasattr(library, 'renamex_np'):
        rename = library.renamex_np
        rename.argtypes = [c.c_char_p, c.c_char_p, c.c_uint]
        arguments = (os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform.startswith('linux') and hasattr(library, 'renameat2'):
        rename = library.renameat2
        rename.argtypes = [c.c_int, c.c_char_p, c.c_int, c.c_char_p, c.c_uint]
        arguments = (-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # NOREPLACE
    else:
        raise Invalid('Staging requires a platform with atomic no-replace directory rename')
    rename.restype = c.c_int
    if rename(*arguments) != 0:
        error = c.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def build(source, destination, targets, zig=False):
    source = regular_path(source)
    destination = Path(os.path.abspath(destination))
    if destination.exists() or destination.is_symlink():
        raise Invalid('Output already exists; choose a fresh staging directory')
    regular_path(destination.parent)
    if source == destination or source in destination.parents:
        raise Invalid('Build output must be outside the source package')
    if not targets or len(targets) != len(set(targets)) or set(targets) - TARGETS:
        raise Invalid('Choose unique supported Linux targets')
    files = local_files(source)
    metadata = manifest(files, source)
    if metadata['runtime'] != 'python' or metadata['entry'] != 'main.py':
        raise Invalid('Experimental Rust uses the manifest v1 Python supervisor')
    cargo = tomllib.loads(read_file(source / 'Cargo.toml', FILE_LIMIT).decode())
    name = cargo.get('package', {}).get('name', '')
    if not name or any(ch not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for ch in name):
        raise Invalid('Cargo package needs a simple binary name')
    if cargo['package'].get('version') != metadata['version']:
        raise Invalid('Cargo and app manifest versions must agree')
    with tempfile.TemporaryDirectory(prefix='vitrallis-rust-build-') as build_dir:
        build_dir = str(Path(build_dir).resolve())
        with tempfile.TemporaryDirectory(prefix='.vitrallis-rust-stage-', dir=destination.parent) as stage_dir:
            staged = Path(stage_dir) / 'package'
            staged.mkdir()
            for relative, data in files.items():
                target = staged / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            for triple in targets:
                command = ['cargo', 'zigbuild' if zig else 'build', '--locked', '--release',
                           '--manifest-path', str(source / 'Cargo.toml'), '--target', triple,
                           '--target-dir', build_dir]
                subprocess.run(command, check=True)
                binary = Path(build_dir) / triple / 'release' / name
                payload = read_file(binary, FILE_LIMIT)
                validate_binary(payload, triple)
                target = staged / 'bin' / triple / 'app'
                target.parent.mkdir(parents=True)
                target.write_bytes(payload)
                target.chmod(0o755)
            manifest(local_files(staged), staged)
            # Staging is complete before its final name becomes visible.
            # Never replace an existing destination or a concurrent creator.
            if destination.exists() or destination.is_symlink():
                raise Invalid('Output appeared during build; refusing replacement')
            publish_directory(staged, destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target', action='append', required=True, choices=sorted(TARGETS))
    parser.add_argument('--zig', action='store_true', help='Use optional cargo-zigbuild cross linker')
    args = parser.parse_args()
    try:
        print(build(args.source, args.output, args.target, args.zig))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Cannot stage Rust app: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""Shared, offline catalog/package checks. Python 3.11+, Git, no pip dependencies."""
import hashlib
from datetime import date
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import tempfile
import tomllib
import zlib

ROOT = Path(__file__).resolve().parent.parent
FILE_LIMIT = 2 * 1024 * 1024
BUNDLE_LIMIT = 16 * 1024 * 1024
CATALOG_LIMIT = 8 * 1024 * 1024
FILE_COUNT = 256
ID = r"[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+"
VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
REPOSITORY = r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}/(?!\.{1,2}$)[A-Za-z0-9_.-]{1,100}"
SOURCE_PATH = r"apps/[a-z0-9]+(?:-[a-z0-9]+)*"
COMMIT = r"[0-9a-f]{40}"


class Invalid(ValueError):
    """Input does not satisfy the repository contracts."""


def require(condition, where, message):
    if not condition:
        raise Invalid(f"{where}: {message}")


def match(value, pattern, where, limit=None):
    require(isinstance(value, str) and re.fullmatch(pattern, value) is not None
            and (limit is None or len(value) <= limit), where, "invalid value")


def safe_path(value, where):
    match(value, r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", where, 240)
    require(all(part not in ('.', '..') for part in value.split('/')),
            where, "dot/traversal components are forbidden")


def text_value(value, where, limit=1000):
    require(isinstance(value, str) and 1 <= len(value) <= limit,
            where, f"expected text of length 1..{limit}")
    require(not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value),
            where, "control characters are forbidden")


def regular_path(path):
    """Reject symlink parents and special files before any reads/writes."""
    path = Path(os.path.abspath(path))
    for parent in reversed((path, *path.parents)):
        info = parent.lstat()
        require(not stat.S_ISLNK(info.st_mode), parent, "symlinks are forbidden")
        if parent != path:
            require(stat.S_ISDIR(info.st_mode), parent, "expected directory")
    return path


def read_file(path, limit):
    path = regular_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode), path, "expected regular file")
        require(info.st_size <= limit, path, f"exceeds {limit} bytes")
        data = stream.read(limit + 1)
    require(len(data) <= limit, path, f"exceeds {limit} bytes")
    return data


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, key, "duplicate JSON key")
        result[key] = value
    return result


def load_json(path):
    try:
        return json.loads(read_file(path, CATALOG_LIMIT), object_pairs_hook=unique_object,
                          parse_constant=lambda value: reject_constant(value))
    except (ValueError, RecursionError) as error:
        raise Invalid(f"{path}: {error}") from error


def reject_constant(value):
    raise Invalid(f"non-JSON number {value}")


# Deliberately bounded to the vocabulary used by apps.schema.json. Unknown
# keywords fail closed; this is not a general JSON Schema implementation.
SCHEMA_KEYS = {'$schema', 'title', 'description', 'type', 'const', 'required',
               'properties', 'additionalProperties', 'items', 'minItems', 'maxItems',
               'minLength', 'maxLength', 'minimum', 'maximum', 'pattern'}
TYPES = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool}


def check_schema(schema, where='schema'):
    require(type(schema) is dict, where, "expected schema object")
    require(not set(schema) - SCHEMA_KEYS, where, "unsupported schema keyword")
    if 'type' in schema:
        require(type(schema['type']) is str and schema['type'] in TYPES,
                where, "unsupported schema type")
    for key in ('$schema', 'title', 'description', 'pattern'):
        if key in schema:
            require(type(schema[key]) is str, where, f"{key} must be text")
    if 'pattern' in schema:
        try:
            re.compile(schema['pattern'])
        except re.error as error:
            raise Invalid(f"{where}: invalid regex") from error
    for key in ('minItems', 'maxItems', 'minLength', 'maxLength', 'minimum', 'maximum'):
        if key in schema:
            require(type(schema[key]) is int and schema[key] >= 0,
                    where, f"{key} must be a nonnegative integer")
    if 'additionalProperties' in schema:
        require(type(schema['additionalProperties']) is bool, where, "expected boolean")
    if 'required' in schema:
        required = schema['required']
        require(type(required) is list and all(type(k) is str for k in required)
                and len(required) == len(set(required)), where, "invalid required keys")
    if 'properties' in schema:
        require(type(schema['properties']) is dict, where, "invalid properties")
        for key, child in schema['properties'].items():
            check_schema(child, f'{where}.{key}')
    if 'items' in schema:
        check_schema(schema['items'], f'{where}.items')


def schema_value(value, schema, where):
    if 'type' in schema:
        require(type(value) is TYPES[schema['type']], where,
                f"expected {schema['type']}")
    if 'const' in schema:
        expected = schema['const']
        require(type(value) is type(expected) and value == expected,
                where, f"expected {expected!r}")
    if isinstance(value, dict):
        properties = schema.get('properties', {})
        for key in schema.get('required', []):
            require(key in value, where, f"missing {key}")
        if schema.get('additionalProperties') is False:
            require(not set(value) - properties.keys(), where, "unknown fields")
        for key, child in value.items():
            if key in properties:
                schema_value(child, properties[key], f'{where}.{key}')
    if isinstance(value, list):
        require(schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', len(value)),
                where, "invalid item count")
        for index, item in enumerate(value):
            schema_value(item, schema.get('items', {}), f'{where}[{index}]')
    if isinstance(value, str):
        require(schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', len(value)),
                where, "invalid text length")
        if 'pattern' in schema:
            require(re.search(schema['pattern'], value) is not None, where, "invalid format")
    if type(value) is int:
        require(schema.get('minimum', value) <= value <= schema.get('maximum', value),
                where, "outside allowed range")


def catalog_metadata(catalog):
    schema = load_json(ROOT / 'apps.schema.json')
    check_schema(schema)
    schema_value(catalog, schema, 'catalog')
    ids = []
    for app in catalog['apps']:
        where = app['id']
        match(where, ID, 'app.id', 128)
        require(where not in ids, where, "duplicate app ID")
        ids.append(where)
        for key in ('name', 'description', 'compatibility_notes'):
            text_value(app[key], f'{where}.{key}')
        match(app['version'], VERSION, f'{where}.version', 32)
        match(app['source']['repository'], REPOSITORY, f'{where}.source.repository')
        match(app['source']['commit'], COMMIT, f'{where}.source.commit')
        match(app['source']['path'], SOURCE_PATH, f'{where}.source.path', 240)
        safe_path(app['entry'], f'{where}.entry')
        paths = [row['path'] for row in app['files']]
        check_paths(paths, where)
        require(app['entry'] in paths, where, "entry missing from files")
        require(sum(row['size'] for row in app['files']) <= BUNDLE_LIMIT,
                where, 'bundle exceeds 16 MiB')
    require(ids == sorted(ids), 'catalog.apps', 'must be sorted by ID')


def check_paths(paths, where):
    require(1 <= len(paths) <= FILE_COUNT, where, 'expected 1..256 files')
    seen = set()
    # Track directory spellings too: assets/a and Assets/b collide on macOS.
    spellings = {}
    for path in paths:
        safe_path(path, f'{where}/{path}')
        folded = path.casefold()
        require(folded not in seen, f'{where}/{path}', 'duplicate/case-colliding path')
        seen.add(folded)
        parts = path.split('/')
        for index in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:index])
            key = prefix.casefold()
            require(key not in spellings or spellings[key] == prefix,
                    f'{where}/{path}', 'case-colliding directory/file')
            spellings[key] = prefix
    for path in paths:
        parts = path.casefold().split('/')
        require(not any('/'.join(parts[:i]) in seen for i in range(1, len(parts))),
                f'{where}/{path}', 'file/directory collision')
    require(paths == sorted(paths), where, 'files must be sorted by path (ASCII)')


def git(repo, *args):
    result = subprocess.run(['git', '--no-replace-objects', '-C', str(repo), *args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                            timeout=30)
    require(result.returncode == 0, repo,
            'Git command failed; confirm the checkout and full source commit exist')
    return result.stdout


def committed_files(repo, commit, source_path):
    match(commit, COMMIT, 'source.commit')
    match(source_path, SOURCE_PATH, 'source.path', 240)
    kind = git(repo, 'cat-file', '-t', commit).strip()
    require(kind == b'commit', commit, 'must identify a commit, not a tag/tree/blob')
    tree = f'{commit}:{source_path}'
    require(git(repo, 'cat-file', '-t', tree).strip() == b'tree',
            source_path, 'source path must be a directory at the pinned commit')
    records = git(repo, 'ls-tree', '-rz', '--full-tree', tree).split(b'\0')
    blobs = []
    for record in records:
        if not record:
            continue
        header, raw_path = record.split(b'\t', 1)
        mode, kind, oid = header.decode('ascii').split()
        try:
            path = raw_path.decode('ascii')
        except UnicodeDecodeError as error:
            raise Invalid(f'{source_path}: non-ASCII file path') from error
        require(mode in ('100644', '100755') and kind == 'blob',
                f'{source_path}/{path}', 'symlink, submodule or unsafe file type')
        blobs.append((path, oid))
    blobs.sort()
    check_paths([path for path, _ in blobs], source_path)
    result = {}
    total = 0
    for path, oid in blobs:
        size = int(git(repo, 'cat-file', '-s', oid))
        require(size <= FILE_LIMIT, f'{source_path}/{path}', 'file exceeds 2 MiB')
        total += size
        require(total <= BUNDLE_LIMIT, source_path, 'bundle exceeds 16 MiB')
        result[path] = git(repo, 'cat-file', 'blob', oid)
    return result


def local_files(directory):
    directory = regular_path(directory)
    require(directory.is_dir(), directory, 'expected package directory')
    result = {}
    total = 0
    # Validate the complete source, including development-only tests.
    # Keep build caches outside packages when checking the working tree.
    for base, directories, files in os.walk(directory, followlinks=False):
        for name in sorted(directories):
            regular_path(Path(base) / name)
        for name in sorted(files):
            path = Path(base) / name
            relative = path.relative_to(directory).as_posix()
            safe_path(relative, path)
            result[relative] = read_file(path, FILE_LIMIT)
            total += len(result[relative])
            require(total <= BUNDLE_LIMIT, directory, 'bundle exceeds 16 MiB')
            require(len(result) <= FILE_COUNT, directory, 'more than 256 files')
    result = dict(sorted(result.items()))
    check_paths(list(result), directory)
    return result


def png_icon(data, where):
    """Validate bounded PNG structure, CRCs and decompression, without a GUI."""
    require(data.startswith(b'\x89PNG\r\n\x1a\n'), where, 'expected PNG signature')
    offset, header, ended, compressed = 8, None, False, bytearray()
    idat_seen, idat_closed, palette = False, False, False
    while offset < len(data):
        require(offset + 12 <= len(data), where, 'truncated PNG chunk')
        size, kind = struct.unpack('>I4s', data[offset:offset + 8])
        end = offset + 12 + size
        require(end <= len(data), where, 'truncated PNG payload')
        payload = data[offset + 8:end - 4]
        crc = struct.unpack('>I', data[end - 4:end])[0]
        require(zlib.crc32(kind + payload) & 0xffffffff == crc, where, 'PNG CRC mismatch')
        require(not ended, where, 'data after PNG IEND')
        if header is None:
            require(kind == b'IHDR' and size == 13, where, 'PNG must start with IHDR')
            header = struct.unpack('>IIBBBBB', payload)
        elif kind == b'IHDR':
            raise Invalid(f'{where}: duplicate PNG IHDR')
        elif kind == b'PLTE':
            require(not palette and not idat_seen and 0 < size <= 768 and size % 3 == 0,
                    where, 'invalid PNG palette')
            palette = True
        elif kind == b'IDAT':
            require(not idat_closed, where, 'nonconsecutive PNG IDAT')
            idat_seen = True
            compressed.extend(payload)
        elif kind == b'IEND':
            require(size == 0 and idat_seen, where, 'invalid PNG IEND')
            ended = True
        else:
            require(kind[0] & 32, where, 'unsupported critical PNG chunk')
        if idat_seen and kind != b'IDAT':
            idat_closed = True
        offset = end
    require(header is not None and ended, where, 'incomplete PNG')
    width, height, depth, color, compression, filtering, interlace = header
    require(1 <= width <= 512 and 1 <= height <= 512, where, 'icon dimensions must be 1..512')
    depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
    require(color in depths and depth in depths[color], where, 'invalid PNG color/depth')
    require(compression == filtering == interlace == 0, where, 'use a noninterlaced PNG')
    require(color != 3 or palette, where, 'indexed PNG requires palette')
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    stride = (width * channels * depth + 7) // 8 + 1
    decoder = zlib.decompressobj()
    try:
        pixels = decoder.decompress(compressed, stride * height + 1)
    except zlib.error as error:
        raise Invalid(f'{where}: invalid PNG compression') from error
    require(len(pixels) == stride * height and decoder.eof and not decoder.unused_data,
            where, 'invalid PNG pixel data')
    require(all(pixels[i] <= 4 for i in range(0, len(pixels), stride)),
            where, 'invalid PNG scanline filter')


def manifest(files, where):
    required = {'app.toml', 'icon.png', 'main.py', 'requirements.txt', 'README.md', 'CHANGELOG.md'}
    require(required <= files.keys(), where,
            'missing package files: ' + ', '.join(sorted(required - files.keys())))
    for directory in ('assets/', 'tests/'):
        require(any(path.startswith(directory) for path in files), where,
                f'missing populated {directory} directory (README is sufficient for assets)')
    try:
        data = tomllib.loads(files['app.toml'].decode('utf-8'))
    except (ValueError, UnicodeError) as error:
        raise Invalid(f'{where}/app.toml: {error}') from error
    keys = {'manifest_version', 'name', 'id', 'version', 'runtime', 'entry', 'permissions'}
    require(set(data) == keys, f'{where}/app.toml', 'missing or unknown manifest v1 fields')
    require(type(data['manifest_version']) is int and data['manifest_version'] == 1,
            where, 'unsupported manifest_version (expected integer 1)')
    text_value(data['name'], f'{where}.name')
    match(data['id'], ID, f'{where}.id', 128)
    match(data['version'], VERSION, f'{where}.version', 32)
    require(data['runtime'] == 'python', where, 'runtime must be python')
    safe_path(data['entry'], f'{where}.entry')
    require(data['entry'].endswith('.py') and data['entry'] in files,
            where, 'entry must be a published Python file')
    permissions = data['permissions']
    require(type(permissions) is dict and set(permissions) == {'network', 'audio', 'storage'}
            and all(type(value) is bool for value in permissions.values()),
            where, 'permissions must contain exactly network/audio/storage booleans')
    png_icon(files['icon.png'], f'{where}/icon.png')
    app_changelog(files['CHANGELOG.md'], data['version'], f'{where}/CHANGELOG.md')
    return data


def release_date(value, where):
    match(value, r'\d{4}-\d{2}-\d{2}', where)
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise Invalid(f'{where}: invalid calendar date') from error


def release_summary(value, where):
    text_value(value, where)
    require(len(value.strip()) >= 12 and not re.match(
        r'(?i)^(?:todo|tbd|fixme|placeholder|wip)\b', value.strip()),
        where, 'describe concrete changes; empty or placeholder release notes are forbidden')


def app_changelog(raw, version, where):
    """Read dated release notes without executing or rendering Markdown."""
    require(len(raw) <= FILE_LIMIT, where, 'changelog exceeds 2 MiB')
    try:
        lines = raw.decode('utf-8').splitlines()
    except UnicodeError as error:
        raise Invalid(f'{where}: expected UTF-8 changelog') from error
    entries = {}
    current = None
    for line in lines:
        if line.startswith('## '):
            heading = re.fullmatch(rf'## ({VERSION}) — (\d{{4}}-\d{{2}}-\d{{2}})', line)
            if heading:
                number, day = heading.groups()
                match(number, VERSION, where, 32)
                require(number not in entries, where, f'duplicate changelog version {number}')
                entries[number] = [release_date(day, where), []]
                current = number
            else:
                require(not re.match(r'## (?:\[|\d)', line), where,
                        'release headings must use: ## VERSION — YYYY-MM-DD')
                current = None  # Preserve separately labelled unversioned history.
        elif current is not None:
            entries[current][1].append(line)
    require(entries and next(iter(entries)) == version, where,
            f'newest changelog entry must match manifest version {version}')
    numbers = [tuple(map(int, number.split('.'))) for number in entries]
    require(numbers == sorted(numbers, reverse=True), where, 'release versions must be newest first')
    days = [entry[0] for entry in entries.values()]
    require(days == sorted(days, reverse=True), where, 'release dates must be newest first')
    for number, (day, body) in entries.items():
        bullets = [line[2:].strip() for line in body if line.startswith('- ')]
        require(bullets, where, f'{number}: release entry needs concrete change bullets')
        for bullet in bullets:
            release_summary(bullet, f'{where}/{number}')
        entries[number] = (day, '\n'.join(body).strip())
    return entries


def package_files(files):
    """Exclude app-local development tests from device packages."""
    return {path: data for path, data in files.items() if not path.startswith('tests/')}


def file_rows(files):
    return [{'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            for path, data in sorted(files.items())]


def check_app_source(app, repo):
    where = f"{app['id']} ({app['source']['path']})"
    try:
        files = committed_files(repo, app['source']['commit'], app['source']['path'])
        expected = file_rows(package_files(files))
        require([row['path'] for row in expected] == [row['path'] for row in app['files']],
                where, 'files must enumerate the committed package (excluding tests/)')
        for actual, published in zip(expected, app['files']):
            require(actual == published, f"{where}/{actual['path']}", 'size or SHA-256 mismatch')
        package = manifest(files, where)
        for key in ('id', 'name', 'version', 'runtime', 'entry', 'permissions'):
            require(app[key] == package[key], f'{where}.{key}', 'catalog/manifest mismatch')
    except (Invalid, SyntaxError, ValueError) as error:
        raise Invalid(f'{where}: {error}') from error


def source_repositories(values):
    result = {}
    for value in values:
        name, separator, directory = value.partition('=')
        require(separator and directory, '--source-repo', 'expected OWNER/REPO=/local/checkout')
        match(name, REPOSITORY, '--source-repo')
        require(name not in result, '--source-repo', 'duplicate repository mapping')
        result[name] = Path(directory)
    return result


def validate_sources(catalog, repo, mappings):
    catalog_metadata(catalog)
    for app in catalog['apps']:
        check_app_source(app, mappings.get(app['source']['repository'], repo))


def write_catalog(path, catalog):
    """Replace only an existing regular catalog, after complete validation."""
    path = regular_path(path)
    require(stat.S_ISREG(path.lstat().st_mode), path, 'expected regular catalog file')
    payload = (json.dumps(catalog, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    require(len(payload) <= CATALOG_LIMIT, path, 'catalog exceeds 8 MiB')
    name = None
    try:
        fd, name = tempfile.mkstemp(prefix='.catalog-', dir=path.parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, stat.S_IMODE(path.stat().st_mode))
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)

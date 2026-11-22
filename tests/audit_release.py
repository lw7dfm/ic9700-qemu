#!/usr/bin/env python3
"""Check a clean source distribution for integrity and common accidental leaks.
These generic checks support, but do not replace, a manual publication review.
Findings identify categories and locations without printing credential values.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import ipaddress
import json
import re

BLOCKED_PARTS = {'.git', '.hg', '.svn', '__pycache__', '.ssh', 'work', 'logs',
                 'tools', 'qemu-src', 'backups'}
BLOCKED_SUFFIXES = {'.dat', '.bin', '.img', '.ppm', '.png', '.jpg', '.jpeg',
                    '.webp', '.bmp', '.wav', '.deb', '.pyc', '.so', '.dll',
                    '.exe', '.o', '.a', '.zip', '.tar', '.gz', '.xz', '.7z',
                    '.pem', '.key', '.p12', '.pfx', '.ppk', '.kdbx'}
BLOCKED_NAMES = {'.env', 'id_rsa', 'id_ed25519', 'known_hosts'}
TEXT_RULES = [
    ('personal home path', re.compile(r'/(?:home|Users)/[A-Za-z0-9_.-]+(?:/|\b)')),
    ('Windows user path', re.compile(r'\b[A-Za-z]:[\\/]+Users[\\/]+[A-Za-z0-9_.-]+')),
    ('mounted user path', re.compile(r'/mnt/[a-z]/Users/[A-Za-z0-9_.-]+')),
    ('private key material', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----')),
    ('credential-like assignment', re.compile(
        r'''\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|secret[_-]?key|password|passwd)\b\s*[:=]\s*["'][^"'\r\n]{16,}["']''', re.IGNORECASE)),
    ('provider token pattern', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b')),
    ('credentials in URL', re.compile(r'https?://[^\s/:@]+:[^\s/@]+@')),
    ('internal conversation identifier', re.compile(
        r'''\b(?:[a-z]+[_-])?(?:chat|conversation|session|message|user)[_-]?id\s*[:=]\s*["']?\d{5,}''', re.IGNORECASE)),
]
IPV4 = re.compile(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])')


def audit(root):
    root = Path(root).resolve()
    problems = []
    manifest_path = root / 'SOURCE_MANIFEST.json'
    if manifest_path.is_symlink():
        return ['symlink manifest rejected'], 0
    try:
        expected = json.loads(manifest_path.read_text(encoding='utf-8'))['files']
        if not isinstance(expected, dict) or not expected:
            raise ValueError('empty or invalid inventory')
        for name, info in expected.items():
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                raise ValueError('non-relative inventory path')
            if not isinstance(info, dict) or not re.fullmatch(r'[0-9a-f]{64}', info.get('sha256', '')):
                raise ValueError('invalid inventory checksum')
            if type(info.get('bytes')) is not int or info['bytes'] < 0:
                raise ValueError('invalid inventory size')
    except (OSError, ValueError, TypeError, KeyError):
        return ['missing or invalid source manifest'], 0

    seen = set()
    checked = 0
    for item in sorted(root.rglob('*')):
        relative = item.relative_to(root)
        name = relative.as_posix()
        if item.is_symlink():
            problems.append('symlink: ' + name)
            continue  # Never inspect a symlink target outside the release.
        if any(part in BLOCKED_PARTS for part in relative.parts):
            problems.append('generated/history/private tree: ' + name)
            continue
        if not item.is_file():
            continue
        checked += 1
        if (item.suffix.lower() in BLOCKED_SUFFIXES or item.name in BLOCKED_NAMES
                or item.name.startswith('.env.')):
            problems.append('excluded artifact: ' + name)
        try:
            data = item.read_bytes()
        except OSError:
            problems.append('unreadable file: ' + name)
            continue
        if name in expected:
            seen.add(name)
            if (hashlib.sha256(data).hexdigest() != expected[name]['sha256']
                    or len(data) != expected[name]['bytes']):
                problems.append('inventory mismatch: ' + name)
        elif name != 'SOURCE_MANIFEST.json':
            problems.append('unmanifested file: ' + name)
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            problems.append('unexpected non-text source file: ' + name)
            continue
        for category, rule in TEXT_RULES:
            for match in rule.finditer(text):
                line = text.count('\n', 0, match.start()) + 1
                problems.append(f'{category}: {name}:{line}')
        for match in IPV4.finditer(text):
            try:
                address = ipaddress.ip_address(match.group())
            except ValueError:
                continue
            if not address.is_loopback:
                line = text.count('\n', 0, match.start()) + 1
                problems.append(f'non-loopback IP needs review: {name}:{line}')
    problems.extend('missing file: ' + name for name in sorted(set(expected) - seen))
    return problems, checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    problems, count = audit(args.root)
    if problems:
        print('\n'.join(problems))
        return 1
    print('SOURCE_RELEASE_AUDIT_PASS', count, 'text files checked; manual review still required')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

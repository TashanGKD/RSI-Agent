#!/usr/bin/env python3
"""Local transcript export and non-destructive recording archive. No network calls."""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


class ArchiveError(Exception):
    pass


def reject(code):
    raise ArchiveError(code)


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def regular(path):
    path = Path(path).expanduser()
    if path.is_symlink():
        reject('symlink_source')
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        reject('not_regular_file')
    return path.resolve()


def signature(path):
    s = path.stat()
    return s.st_size, s.st_mtime_ns, s.st_ino


def fingerprint(path):
    before = signature(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    if before != signature(path):
        reject('source_changed_during_read')
    return {'bytes': before[0], 'sha256': h.hexdigest()}


def video_info(path):
    if path.suffix.lower() in ('.part', '.tmp', '.download', '.crdownload'):
        reject('incomplete_download')
    path = regular(path)
    if path.suffix.lower() != '.mp4':
        reject('expected_mp4')
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=60, check=True)
        info = json.loads(result.stdout)
        duration = float(info['format']['duration'])
        streams = info['streams']
        if not math.isfinite(duration) or duration <= 0:
            reject('invalid_video_duration')
        if not {'video', 'audio'}.issubset({s.get('codec_type') for s in streams}):
            reject('missing_audio_or_video_stream')
        return {'duration_seconds': duration, 'streams': [
            {k: s[k] for k in ('codec_type', 'codec_name', 'width', 'height') if k in s}
            for s in streams]}
    except (subprocess.SubprocessError, KeyError, ValueError):
        reject('invalid_video')


def load_json(path):
    path = regular(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        reject('json_too_large')
    return json.loads(path.read_text(encoding='utf-8'))


def destination(path):
    path = Path(path).expanduser().absolute()
    if path.is_symlink():
        reject('symlink_destination')
    if not path.parent.is_dir():
        reject('output_parent_missing')
    return path


def write_new(path, text):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def verify(path):
    root = destination(path)
    if not root.is_dir():
        reject('archive_missing')
    manifest = load_json(root / 'manifest.json')
    if manifest.get('schema_version') != 1:
        reject('unknown_manifest_schema')
    if set(manifest.get('files', {})) != {'video.mp4', 'transcript.md'}:
        reject('invalid_manifest_files')
    for name, expected in manifest['files'].items():
        actual = fingerprint(regular(root / name))
        if actual != expected:
            reject('hash_mismatch:' + name)
    info = video_info(root / 'video.mp4')
    if abs(info['duration_seconds'] - manifest['video']['duration_seconds']) > 0.01:
        reject('duration_mismatch')
    return manifest


def archive(args):
    try:
        dt.date.fromisoformat(args.date)
    except ValueError:
        reject('invalid_date')
    if not args.record_id.isdecimal() or int(args.record_id) == 0:
        reject('invalid_record_id')
    if not args.title.strip():
        reject('empty_title')
    source = Path(args.video).expanduser()
    probe = video_info(source)
    source = regular(source)
    md = regular(args.transcript)
    if md.suffix.lower() != '.md' or not md.read_text(encoding='utf-8').strip():
        reject('invalid_transcript_markdown')
    out = destination(args.output)
    files = {'video.mp4': fingerprint(source), 'transcript.md': fingerprint(md)}
    manifest = {'schema_version': 1, 'title': args.title, 'date': args.date,
                'record_id': args.record_id, 'video': probe, 'files': files,
                'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'inspection': 'ffprobe metadata and SHA256; not full audiovisual review'}
    if out.exists():
        old = verify(out)
        if any(old.get(k) != manifest[k] for k in ['title', 'date', 'record_id', 'files']):
            reject('archive_conflict')
        return {'ok': True, 'status': 'already_archived', 'output': str(out)}
    if not args.apply:
        return {'ok': True, 'status': 'dry_run', 'output': str(out), 'manifest': manifest}
    lock = out.parent / ('.' + out.name + '.archive.lock')
    try:
        lockfd = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        reject('archive_locked')
    os.close(lockfd)
    staging = None
    try:
        if out.exists() or out.is_symlink():
            reject('output_exists')
        staging = Path(tempfile.mkdtemp(prefix='.' + out.name + '-', dir=str(out.parent)))
        for src, name in [(source, 'video.mp4'), (md, 'transcript.md')]:
            before = signature(src)
            shutil.copyfile(src, staging / name)
            os.chmod(staging / name, 0o600)
            if before != signature(src) or fingerprint(staging / name) != files[name]:
                reject('source_changed_during_copy')
        write_new(staging / 'manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        verify(staging)
        if out.exists() or out.is_symlink():
            reject('output_exists')
        staging.rename(out)
        staging = None
    finally:
        if staging is not None:
            shutil.rmtree(staging)
        lock.unlink(missing_ok=True)
    verify(out)
    return {'ok': True, 'status': 'archived', 'output': str(out), 'manifest': manifest}


def timestamp(ms):
    total = int(ms) // 1000
    return f'{total // 3600:02d}:{total // 60 % 60:02d}:{total % 60:02d}'


def transcript(args):
    raw = load_json(args.input)
    expected = load_json(args.pids)
    try:
        paragraphs = raw['minutes']['paragraphs']
        pids = [str(p['pid']) for p in expected['pids']]
        actual = [str(p['pid']) for p in paragraphs]
        if not pids or not actual:
            reject('empty_transcript')
        if (len(pids) != len(set(pids)) or len(actual) != len(set(actual))
                or set(pids) != set(actual) or expected['total'] != len(pids)):
            reject('incomplete_transcript')
        lines = ['# ' + args.title, '', '腾讯会议机器转写，未逐句回听校订。时间为相对录制起点的时间；保留原段落ID。', '']
        for p in sorted(paragraphs, key=lambda x: (int(x['start_time']), int(x['end_time']))):
            if int(p['start_time']) < 0 or int(p['end_time']) < int(p['start_time']):
                reject('invalid_transcript_time')
            words = [w['text'] for s in p['sentences'] for w in s['words']]
            if not all(isinstance(w, str) for w in words):
                reject('invalid_transcript_words')
            speaker = p.get('speaker', {}).get('user_name') or '未标注说话人'
            lines.extend([f"## P{p['pid']} · {timestamp(p['start_time'])}—{timestamp(p['end_time'])} · {speaker}",
                          '', ''.join(words), ''])
    except (KeyError, TypeError, ValueError):
        reject('unsupported_transcript_schema')
    out = destination(args.output)
    if out.exists():
        reject('output_exists')
    if args.apply:
        write_new(out, '\n'.join(lines))
    return {'ok': True, 'status': 'exported' if args.apply else 'dry_run',
            'paragraphs': len(actual), 'output': str(out)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command')
    p = subs.add_parser('archive', help='Inspect; copy only with --apply')
    for name in ['video', 'transcript', 'output', 'title', 'date', 'record-id']:
        p.add_argument('--' + name, required=True)
    p.add_argument('--apply', action='store_true')
    p = subs.add_parser('transcript', help='Export full MCP transcript; write only with --apply')
    for name in ['input', 'pids', 'title', 'output']:
        p.add_argument('--' + name, required=True)
    p.add_argument('--apply', action='store_true')
    p = subs.add_parser('verify', help='Read-only archive verification')
    p.add_argument('directory')
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == 'verify':
            data = verify(args.directory)
            emit({'ok': True, 'status': 'verified', 'manifest': data})
        else:
            emit(archive(args) if args.command == 'archive' else transcript(args))
        return 0
    except (ArchiveError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

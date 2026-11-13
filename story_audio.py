"""Script markers, deliberate pauses and uploaded sound effects."""
import json
import math
from pathlib import Path
import re
import shutil
import wave

from expressive_voice import run_ffmpeg, split_sentences

SAMPLE_RATE = 48000
MARKER = re.compile(r'\[\[(SFX|PAUSE):([^\]\r\n]+)\]\]')


def read_effects(folder):
    manifest = folder / 'effects.json'
    if not manifest.exists():
        return {}
    library = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(library, dict) or any(
            not isinstance(value, dict) or not isinstance(value.get('name'), str)
            or not isinstance(value.get('path'), str) for value in library.values()):
        raise ValueError('Thư viện hiệu ứng không đúng định dạng. Hãy kiểm tra file effects.json.')
    return library


def script_plan(text, sentence_pause, paragraph_pause, effects):
    plan = []
    position = 0

    def add_text(value):
        parts = re.split(r'(\n\s*\n)', value)
        for part in parts:
            if not part.strip():
                if re.search(r'\n\s*\n', part) and plan:
                    if plan[-1].get('auto'):
                        plan[-1]['seconds'] = paragraph_pause
                    elif paragraph_pause:
                        plan.append({'kind': 'pause', 'seconds': paragraph_pause, 'auto': True})
                continue
            for sentence in split_sentences(part.strip()):
                if '[[' in sentence or ']]' in sentence:
                    raise ValueError('Dấu hiệu ứng chưa đúng. Hãy xóa và chèn lại bằng hộp thoại.')
                plan.append({'kind': 'speech', 'text': sentence})
                if sentence_pause:
                    plan.append({'kind': 'pause', 'seconds': sentence_pause, 'auto': True})

    for match in MARKER.finditer(text):
        add_text(text[position:match.start()])
        kind, value = match.groups()
        if kind == 'PAUSE':
            seconds = float(value)
            if not math.isfinite(seconds) or not 0 <= seconds <= 30:
                raise ValueError('Khoảng nghỉ phải từ 0 đến 30 giây.')
            if plan and plan[-1].get('auto'):
                plan.pop()
            plan.append({'kind': 'pause', 'seconds': seconds})
        else:
            effect_id, volume = value.rsplit(':', 1)
            volume = int(volume)
            if not 0 <= volume <= 150:
                raise ValueError('Âm lượng hiệu ứng phải từ 0 đến 150%.')
            if effect_id not in effects:
                raise ValueError(f'Không tìm thấy hiệu ứng {effect_id}. Hãy tải lại trong hộp thoại.')
            effect = effects[effect_id]
            path = Path(effect['path'])
            if not path.is_file():
                raise ValueError(f'File hiệu ứng đã bị di chuyển hoặc xóa: {effect["name"]}')
            plan.append({'kind': 'effect', 'path': str(path), 'volume': volume,
                         'name': effect['name']})
        position = match.end()
    add_text(text[position:])
    if plan and plan[-1].get('auto'):
        plan.pop()
    return plan


def preview_plan(plan, sentence_limit=4):
    count = 0
    preview = []
    for item in plan:
        if item['kind'] == 'speech':
            count += 1
            if count > sentence_limit:
                break
        preview.append(item)
    if preview and preview[-1].get('auto'):
        preview.pop()
    return preview


def script_excerpt(text, start, end=None):
    """Take the selection or current paragraph, keeping sound markers whole."""
    start = max(0, min(start, len(text)))
    if end is None:
        boundaries = list(re.finditer(r'\n[ \t\r]*\n', text))
        left, right = 0, len(text)
        for boundary in boundaries:
            if boundary.end() <= start:
                left = boundary.end()
            elif boundary.start() < start < boundary.end():
                left = boundary.end()
            else:
                right = boundary.start()
                break
        start, end = left, right
    else:
        end = max(start, min(end, len(text)))
    for marker in MARKER.finditer(text):
        if marker.start() < start < marker.end():
            start = marker.start()
        if marker.start() < end < marker.end():
            end = marker.end()
    return text[start:end].strip()


def plain_script(plan):
    return ' '.join(item['text'] for item in plan if item['kind'] == 'speech')


def read_cues(path):
    cues = []
    for block in re.split(r'\n\s*\n', path.read_text(encoding='utf-8-sig').strip()):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        values = re.findall(r'(\d+):(\d+):(\d+),(\d+)', lines[1])
        if len(values) != 2:
            raise ValueError('Không đọc được mốc phụ đề của đoạn giọng đọc.')
        times = [int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000
                 for h, m, s, ms in values]
        cues.append((*times, '\n'.join(lines[2:])))
    return cues


def timestamp(samples):
    ms = round(samples * 1000 / SAMPLE_RATE)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'


def render_story(plan, target, render_speech, progress=None, preview=False):
    """Append speech, silence and effects, shifting captions by decoded frames."""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('Cần cài FFmpeg để thêm khoảng nghỉ và hiệu ứng âm thanh.')
    stage = target.with_suffix('.story.part')
    if stage.exists():
        raise RuntimeError('Tác vụ cũ chưa dọn xong. Hãy thử lại với tên xuất mới.')
    stage.mkdir()
    elapsed = 0
    captions = []
    published = []
    try:
        with wave.open(str(stage / 'joined.wav'), 'wb') as joined:
            joined.setparams((1, 2, SAMPLE_RATE, 0, 'NONE', 'not compressed'))
            for index, item in enumerate(plan):
                kind = item['kind']
                if kind == 'pause':
                    frames = round(item['seconds'] * SAMPLE_RATE)
                    joined.writeframesraw(b'\0\0' * frames)
                    elapsed += frames
                    continue
                if progress:
                    progress(f'{index+1}/{len(plan)} · ' + item.get('text', item.get('name', '')))
                cues = []
                if kind == 'speech':
                    audio, cues = render_speech(item['text'], stage / f'speech_{index}.mp3')
                else:
                    audio = Path(item['path'])
                args = ['-i', str(audio), '-vn']
                if kind == 'effect':
                    args += ['-af', f'volume={item["volume"]/100}']
                pcm = run_ffmpeg(ffmpeg, [*args, '-f', 's16le', '-ac', '1',
                                          '-ar', str(SAMPLE_RATE), 'pipe:1'])
                frames = len(pcm) // 2
                if not frames:
                    raise RuntimeError('Đoạn âm thanh rỗng, hãy kiểm tra lại file hiệu ứng hoặc giọng đọc.')
                joined.writeframesraw(pcm)
                for start, end, text in cues:
                    start_frame = max(0, round(start * SAMPLE_RATE))
                    end_frame = min(frames, round(end * SAMPLE_RATE))
                    if end_frame > start_frame:
                        captions.append(f'{len(captions)+1}\n'
                            f'{timestamp(elapsed+start_frame)} --> {timestamp(elapsed+end_frame)}\n{text}\n')
                elapsed += frames
        if not elapsed:
            raise ValueError('Kịch bản chưa có âm thanh hoặc khoảng nghỉ có độ dài lớn hơn 0.')
        if preview:
            (stage / 'joined.wav').replace(target)
            return target
        run_ffmpeg(ffmpeg, ['-y', '-i', str(stage / 'joined.wav'), '-codec:a', 'libmp3lame',
                            '-q:a', '2', str(stage / 'final.mp3')])
        (stage / 'final.srt').write_text('\n'.join(captions), encoding='utf-8-sig')
        (stage / 'final.txt').write_text(plain_script(plan), encoding='utf-8')
        for suffix in ('.srt', '.txt', '.mp3'):
            destination = target.with_suffix(suffix)
            (stage / ('final' + suffix)).replace(destination)
            published.append(destination)
        return target
    except Exception:
        for path in published:
            path.unlink(missing_ok=True)
        raise
    finally:
        cleanup_story(target)


def cleanup_story(target):
    stage = target.with_suffix('.story.part')
    # Delete only this output's sibling staging directory, never its parent.
    if stage.exists() and not stage.is_symlink() and stage.resolve().parent == target.resolve().parent:
        shutil.rmtree(stage)

"""Script markers, deliberate pauses and uploaded sound effects."""
import json
import math
from pathlib import Path
import re
import shutil
import wave

from expressive_voice import run_ffmpeg, split_sentences
from dialogue import CHARACTER_HEADER, INLINE_VOICE, inline_turns, resolve_character, validate_characters
from voice_effects import speech_filter

SAMPLE_RATE = 48000
MARKER = re.compile(r'\[\[(SFX|PAUSE|MOOD):([^\]\r\n]+)\]\]')
VALID_MOODS = {'binhthuong', 'normal', 'tram', 'tham', 'gap', 'ma'}
SCRIPT_TOKEN = re.compile(MARKER.pattern + '|' + CHARACTER_HEADER + '|' + INLINE_VOICE, re.MULTILINE)


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


def script_plan(text, sentence_pause, paragraph_pause, effects, characters=None):
    if characters is not None:
        validate_characters(characters)
    plan = []
    position = 0
    current_mood = None
    character = {}
    turns = {turn['start']: turn for turn in inline_turns(text)}

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
                speech = {'kind': 'speech', 'text': sentence, **character}
                if current_mood:
                    speech['mood'] = current_mood
                plan.append(speech)
                if sentence_pause:
                    plan.append({'kind': 'pause', 'seconds': sentence_pause, 'auto': True})

    for match in SCRIPT_TOKEN.finditer(text):
        if match.start() < position:
            continue
        add_text(text[position:match.start()])
        if match.group('inline_voice') is not None:
            turn = turns[match.start()]
            profile = ({} if turn['voice'] == 'Người kể' else
                       resolve_character(turn['voice'], characters or {}))
            quoted = text[turn['content_start']:turn['content_end']].replace('\\"', '"')
            quoted_plan = script_plan(quoted, sentence_pause, paragraph_pause, effects, characters)
            for item in quoted_plan:
                if item['kind'] == 'speech':
                    item.update(profile, inline_voice=turn['voice'])
            plan.extend(quoted_plan)
            if sentence_pause and quoted_plan:
                plan.append({'kind': 'pause', 'seconds': sentence_pause, 'auto': True})
            position = turn['end']
            continue
        if match.group('character') is not None:
            character = resolve_character(match.group('character'), characters or {})
            if plan and plan[-1].get('auto'):
                plan[-1]['seconds'] = max(sentence_pause, paragraph_pause)
            elif plan and plan[-1]['kind'] != 'pause' and paragraph_pause:
                plan.append({'kind': 'pause', 'seconds': paragraph_pause, 'auto': True})
            position = match.end()
            continue
        kind, value = match.group(1), match.group(2)
        if kind == 'PAUSE':
            seconds = float(value)
            if not math.isfinite(seconds) or not 0 <= seconds <= 30:
                raise ValueError('Khoảng nghỉ phải từ 0 đến 30 giây.')
            if plan and plan[-1].get('auto'):
                plan.pop()
            plan.append({'kind': 'pause', 'seconds': seconds})
        elif kind == 'MOOD':
            mood = value.strip().lower()
            if mood not in VALID_MOODS:
                raise ValueError(f'Sắc thái "{value}" chưa hỗ trợ. Dùng: tram, tham, gap, ma, binhthuong.')
            current_mood = None if mood in ('binhthuong', 'normal') else mood
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
    for turn in inline_turns(text):
        if turn['content_start'] <= start < end <= turn['content_end']:
            return f'[[VOICE:{turn["voice"]}]]"' + text[start:end] + '"'
        if turn['start'] < start < turn['end']:
            start = turn['start']
        if turn['start'] < end < turn['end']:
            end = turn['end']
    for marker in SCRIPT_TOKEN.finditer(text):
        if marker.start() < start < marker.end():
            start = marker.start()
        if marker.start() < end < marker.end():
            end = marker.end()
    excerpt = text[start:end].strip()
    # A selection in the middle of a turn still uses that character's voice.
    headers = list(re.finditer(CHARACTER_HEADER, text[:start], re.MULTILINE))
    if excerpt and headers and not re.match(CHARACTER_HEADER, excerpt):
        excerpt = headers[-1].group(0).strip() + ' ' + excerpt
    return excerpt


def plain_script(plan):
    if any(item.get('short_section') for item in plan):
        groups = {}
        for item in plan:
            plain = dict(item)
            key = plain.pop('short_section')
            groups.setdefault(key, []).append(plain)
        return '\n\n'.join(
            (f'[[BEAT:{key}]]\n' if key != 'DRAFT' else '') + plain_script(items)
            for key, items in groups.items())
    if any(item.get('inline_voice') for item in plan):
        def assigned_line(item):
            quoted = item['text'].replace('"', '\\"')
            return f'[[VOICE:{item["inline_voice"]}]]"{quoted}"'
        return '\n\n'.join(
            (assigned_line(item) if item.get('inline_voice')
             else (f'[{item["character_header"]}]: ' if item.get('character') else '') + item['text'])
            for item in plan if item['kind'] == 'speech')
    if any(item.get('character') for item in plan):
        lines = []
        previous = object()
        for item in plan:
            if item['kind'] != 'speech':
                continue
            header = item.get('character_header')
            if header == previous:
                lines[-1] += ' ' + item['text']
            else:
                lines.append((f'[{header}]: ' if header else '') + item['text'])
            previous = header
        return '\n\n'.join(lines)
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
        prepared, timing = {}, None
        if any(item.get('short_section') for item in plan):
            from short_pacing import prepare_audio
            prepared, timing = prepare_audio(plan, stage, render_speech, ffmpeg, progress)
        timing_rows = {row['key']: row for row in timing['sections']} if timing else {}
        with wave.open(str(stage / 'joined.wav'), 'wb') as joined:
            joined.setparams((1, 2, SAMPLE_RATE, 0, 'NONE', 'not compressed'))
            for index, item in enumerate(plan):
                kind = item['kind']
                timing_row = timing_rows.get(item.get('short_section'))
                if timing_row is not None:
                    timing_row.setdefault('actual_start', elapsed / SAMPLE_RATE)
                if kind == 'pause':
                    frames = round(item['seconds'] * SAMPLE_RATE)
                    joined.writeframesraw(b'\0\0' * frames)
                    elapsed += frames
                    if timing_row is not None:
                        timing_row['actual_end'] = elapsed / SAMPLE_RATE
                    continue
                if progress:
                    progress(f'{index+1}/{len(plan)} · ' + item.get('text', item.get('name', '')))
                cues = []
                raw_pcm = None
                if index in prepared:
                    raw_pcm, cues = prepared[index]
                    args = ['-f', 's16le', '-ac', '1', '-ar', str(SAMPLE_RATE), '-i', 'pipe:0']
                elif kind == 'speech':
                    audio, cues = render_speech(item['text'], stage / f'speech_{index}.mp3', item)
                    args = ['-i', str(audio), '-vn']
                else:
                    audio = Path(item['path'])
                    args = ['-i', str(audio), '-vn']
                effect = None
                if kind == 'effect':
                    args += ['-af', f'volume={item["volume"]/100}']
                elif kind == 'speech':
                    effect = speech_filter(item.get('voice_effect', 'none'),
                                           item.get('effect_strength', 65), item.get('effect_settings'))
                    if effect:
                        args += ['-af', effect]
                pcm = (raw_pcm if raw_pcm is not None and not effect else
                       run_ffmpeg(ffmpeg, [*args, '-f', 's16le', '-ac', '1',
                                          '-ar', str(SAMPLE_RATE), 'pipe:1'], raw_pcm))
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
                if timing_row is not None:
                    timing_row['actual_end'] = elapsed / SAMPLE_RATE
        if not elapsed:
            raise ValueError('Kịch bản chưa có âm thanh hoặc khoảng nghỉ có độ dài lớn hơn 0.')
        if preview:
            (stage / 'joined.wav').replace(target)
            return target
        run_ffmpeg(ffmpeg, ['-y', '-i', str(stage / 'joined.wav'), '-codec:a', 'libmp3lame',
                            '-q:a', '2', str(stage / 'final.mp3')])
        (stage / 'final.srt').write_text('\n'.join(captions), encoding='utf-8-sig')
        (stage / 'final.txt').write_text(plain_script(plan), encoding='utf-8')
        suffixes = ['.srt', '.txt', '.mp3']
        if timing:
            timing['total_seconds'] = elapsed / SAMPLE_RATE
            timing['voice_target_seconds'] = sum(row['voice_seconds'] for row in timing['sections'])
            (stage / 'final.timing.json').write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding='utf-8')
            suffixes.insert(0, '.timing.json')
        for suffix in suffixes:
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

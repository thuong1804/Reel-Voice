"""Six-beat, restrained narration pacing for a 55-second spiritual story."""
import re
import unicodedata

from expressive_voice import run_ffmpeg

STYLE = 'Short tâm linh · 6 nhịp'
VERSION = 'short-55-v1'
SAMPLE_RATE = 48000
SPECS = (
    dict(key='HOOK', label='HOOK', start=0, end=4, sentence=.08, paragraph=.10, transition=.08,
         note='Dứt khoát, nối ngay sang vật thể; không nghỉ dài sau hook.'),
    dict(key='NEO', label='NEO', start=4, end=14, sentence=.11, paragraph=.16, transition=.12,
         note='Đều, lạnh; nhấn nhẹ chi tiết trái quy luật.'),
    dict(key='LEO1', label='LEO 1', start=14, end=24, sentence=.09, paragraph=.14, transition=.10,
         note='Nén nhịp, hiện tượng diễn ra trực tiếp.'),
    dict(key='LEO2', label='LEO 2', start=24, end=35, sentence=.06, paragraph=.10, transition=.10,
         note='Câu ngắn dồn dập; không kéo chậm mọi câu ngắn.'),
    dict(key='CLIMAX', label='CAO TRÀO', start=35, end=47, sentence=.12, paragraph=.20, transition=.20,
         note='Dừng ngắn trước ba câu lộ bản chất; giữ giọng, không gào.'),
    dict(key='END', label='KẾT', start=47, end=55, sentence=.10, paragraph=.16, transition=0,
         note='Rõ dấu vết còn lại; chốt câu hỏi trực tiếp, không lên giọng cường điệu.'),
)
BY_KEY = {spec['key']: spec for spec in SPECS}
HEADER = re.compile(
    r'^[ \t]*(?:\[\[BEAT:(?P<marker>[^\]\r\n]+)\]\]|'
    r'(?:\#{1,6}[ \t]*)?(?:NHỊP[ \t]+[1-6][ \t]*[—–:\-][ \t]*)?'
    r'(?P<label>HOOK|NEO|LEO[ \t]*[12]|CAO[ \t]+TRÀO|KẾT)'
    r'(?:[ \t]*\([^\r\n)]*\))?[ \t]*:?)'
    r'[ \t]*$', re.MULTILINE | re.IGNORECASE)


def section_key(value):
    value = ''.join(char for char in unicodedata.normalize('NFD', value.upper())
                    if not unicodedata.combining(char))
    value = re.sub(r'[^A-Z0-9]', '', value)
    return {'CAOTRAO': 'CLIMAX', 'KET': 'END'}.get(value, value)


def word_count(text):
    text = re.sub(r'\[\[.*?\]\]|^[ \t]*\[[^\]\r\n]+\]:', '', text, flags=re.MULTILINE)
    return len(re.findall(r'\b\w+\b', text))


def template():
    return '\n\n'.join(f'[[BEAT:{spec["key"]}]]\n' for spec in SPECS)


def has_headers(text):
    return HEADER.search(text) is not None


def extract_sections(text):
    """Accept beat markers, the supplied Markdown example, or six paragraphs."""
    matches = list(HEADER.finditer(text))
    sections = []
    if matches:
        if matches[0].group('marker') and text[:matches[0].start()].strip():
            raise ValueError('Có lời đọc đứng trước nhịp đầu tiên. Hãy đưa lời đó vào đúng nhịp.')
        for index, match in enumerate(matches):
            key = section_key(match.group('marker') or match.group('label'))
            if key not in BY_KEY:
                raise ValueError('Nhịp chưa đúng: ' + key + '. Dùng HOOK, NEO, LEO1, LEO2, CLIMAX, END.')
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[match.end():end]
            other_heading = re.search(r'(?m)^[ \t]*#{1,6}[ \t]+', body)
            if other_heading:
                body = body[:other_heading.start()]
            quoted = re.findall(r'(?m)^[ \t]*>[ \t]?(.*)$', body)
            if quoted:
                body = '\n'.join(quoted)
            else:
                body = '\n'.join(line for line in body.splitlines()
                    if not re.match(r'^[ \t]*(?:---|\*?(?:Hình|Pattern interrupt)[ \t]*:)', line, re.I))
            if not body.strip():
                raise ValueError('Nhịp ' + BY_KEY[key]['label'] + ' chưa có lời đọc.')
            sections.append(dict(key=key, text=body.strip(), start=match.start(), end=end, structured=True))
        order = [list(BY_KEY).index(section['key']) for section in sections]
        if order != sorted(set(order)):
            raise ValueError('Các nhịp phải theo thứ tự HOOK → NEO → LEO1 → LEO2 → CLIMAX → END, không lặp.')
    else:
        paragraphs = list(re.finditer(r'\S(?:.*?\S)?(?=\n[ \t]*\n|\Z)', text, re.DOTALL))
        if len(paragraphs) == 6:
            sections = [dict(key=spec['key'], text=part.group(0), start=part.start(), end=part.end(), structured=True)
                        for spec, part in zip(SPECS, paragraphs)]
        elif text.strip():
            # Unlabelled drafts keep a sensible delivery without inventing beat boundaries.
            sections = [dict(key='DRAFT', text=text.strip(), start=0, end=len(text), structured=False)]
    return sections


def canonical_script(text):
    sections = extract_sections(text)
    if sections and all(section['structured'] for section in sections):
        return '\n\n'.join(f'[[BEAT:{section["key"]}]]\n{section["text"]}' for section in sections)
    return text


def short_plan(text, effects, characters, preview_start=None, preview_end=None):
    from story_audio import script_plan

    sections = extract_sections(text)
    if preview_start is not None:
        selected = [section for section in sections
                    if section['start'] <= preview_start < section['end']
                    or (preview_end is not None and section['start'] < preview_end and section['end'] > preview_start)]
        sections = selected or sections[:1]
    plan = []
    for section in sections:
        spec = BY_KEY.get(section['key'], dict(key='DRAFT', label='BẢN NHÁP', start=0, end=0,
                                              sentence=.10, paragraph=.18, transition=0))
        items = script_plan(section['text'], spec['sentence'], spec['paragraph'], effects, characters)
        speech_indices = [index for index, item in enumerate(items) if item['kind'] == 'speech']
        if not speech_indices:
            raise ValueError('Nhịp ' + spec['label'] + ' cần có lời đọc.')
        for number, index in enumerate(speech_indices):
            item = items[index]
            stressed = ((spec['key'] == 'HOOK' and number == 0)
                        or (spec['key'] == 'CLIMAX' and number >= len(speech_indices) - 3)
                        or (spec['key'] == 'END' and number == len(speech_indices) - 1))
            item.update(rate=0, pitch=0, expressive=False, short_weight=1.08 if stressed else 1,
                        short_gain_db=.6 if stressed else 0)
            if spec['key'] == 'CLIMAX' and stressed and index and items[index-1].get('auto'):
                items[index-1]['seconds'] = .24 if number == len(speech_indices)-1 else .18
        if spec['transition'] and items[-1]['kind'] != 'pause':
            items.append(dict(kind='pause', seconds=spec['transition'], auto=True))
        spoken_words = sum(word_count(items[index]['text']) for index in speech_indices)
        # A draft gets the requested 2.8 words/s, without pretending it has six known beats.
        duration = spec['end'] - spec['start'] if section['structured'] else max(2, spoken_words / 2.8)
        for item in items:
            item.update(short_section=spec['key'], short_duration=duration, short_nominal_start=spec['start'])
        plan.extend(items)
    return plan


def _tempo_chain(factor):
    filters = []
    while factor < .5:
        filters.append('atempo=0.5')
        factor *= 2
    while factor > 2:
        filters.append('atempo=2')
        factor /= 2
    filters.append(f'atempo={factor:.8f}')
    return filters


def prepare_audio(plan, stage, render_speech, ffmpeg, progress=None):
    """Fit dry speech to each beat; leave SFX and ghost filters to the existing renderer."""
    groups = {}
    for index, item in enumerate(plan):
        groups.setdefault(item['short_section'], []).append((index, item))
    prepared = {}
    report = dict(preset=VERSION, target_seconds=55, sections=[],
                  note='Mốc giọng đọc; SFX và đuôi hiệu ứng hồn ma giữ nguyên, có thể kéo dài tổng thời lượng.')
    for key, entries in groups.items():
        target = entries[0][1]['short_duration']
        pause_seconds = sum(item['seconds'] for _, item in entries if item['kind'] == 'pause')
        if target - pause_seconds <= .05:
            raise ValueError('Khoảng nghỉ trong nhịp ' + key + ' đã chiếm hết thời lượng lời đọc.')
        chunks = []
        for index, item in entries:
            if item['kind'] != 'speech':
                continue
            if progress:
                progress(f'{key} · {item["text"]}')
            audio, cues = render_speech(item['text'], stage / f'speech_{index}.mp3', item)
            pcm = run_ffmpeg(ffmpeg, ['-i', str(audio), '-vn', '-f', 's16le', '-ac', '1',
                                      '-ar', str(SAMPLE_RATE), 'pipe:1'])
            if not pcm:
                raise RuntimeError('Đoạn giọng đọc của nhịp ' + key + ' rỗng.')
            chunks.append((index, item, pcm, cues))
        weighted = [len(pcm) // 2 * item['short_weight'] for _, item, pcm, _ in chunks]
        total_weight = sum(weighted)
        target_frames = round((target - pause_seconds) * SAMPLE_RATE)
        cumulative, allocated, tempos = 0, 0, []
        for (index, item, pcm, cues), weight in zip(chunks, weighted):
            cumulative += weight
            end_frame = round(target_frames * cumulative / total_weight)
            frames = max(1, end_frame - allocated)
            allocated = end_frame
            native_frames = len(pcm) // 2
            factor = native_frames / frames
            filters = _tempo_chain(factor)
            if item['short_gain_db']:
                filters += [f'volume={item["short_gain_db"]}dB', 'alimiter=limit=0.97:level=0:latency=1']
            filters += ['apad', f'atrim=end_sample={frames}']
            processed = run_ffmpeg(ffmpeg, [
                '-f', 's16le', '-ar', str(SAMPLE_RATE), '-ac', '1', '-i', 'pipe:0',
                '-af', ','.join(filters), '-f', 's16le', '-ar', str(SAMPLE_RATE), '-ac', '1', 'pipe:1'], pcm)
            if len(processed) != frames * 2:
                raise RuntimeError('Không căn được thời lượng chính xác cho nhịp ' + key + '.')
            scale = frames / native_frames
            prepared[index] = (processed, [(start*scale, end*scale, text) for start, end, text in cues])
            tempos.append(factor)
        warnings = []
        if tempos and (min(tempos) < .6 or max(tempos) > 1.6):
            warnings.append('Lời đọc cần đổi tốc độ nhiều; cân nhắc chỉnh số từ của nhịp.')
        if any(word_count(item['text']) > 14 for _, item, _, _ in chunks):
            warnings.append('Có câu dài hơn 14 từ.')
        if key == 'LEO2' and any(word_count(item['text']) >= 8 for _, item, _, _ in chunks):
            warnings.append('LEO 2 có câu từ 8 từ trở lên; khung đề nghị câu ngắn hơn.')
        report['sections'].append(dict(key=key, target_start=entries[0][1]['short_nominal_start'],
            voice_seconds=target, natural_speech_seconds=sum(len(pcm)//2 for _, _, pcm, _ in chunks)/SAMPLE_RATE,
            pause_seconds=round(pause_seconds, 3), words=sum(word_count(item['text']) for _, item, _, _ in chunks),
            min_tempo=round(min(tempos), 3), max_tempo=round(max(tempos), 3), warnings=warnings))
    return prepared, report

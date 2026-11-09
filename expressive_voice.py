"""Generate narration with pace changes and pauses between spoken beats."""

import re
import shutil
import subprocess
import wave
from typing import NamedTuple


SAMPLE_RATE = 24000
PART_SUFFIXES = ('.mp3.part', '.srt.part', '.txt.part', '.wav.part')


class Beat(NamedTuple):
    text: str
    rate_change: int
    pitch_change: int
    pause_ms: int


def split_sentences(text):
    return [part.strip() for part in re.split(r'(?<=[.!?])\s+|(?<=[.!?]["”’»])\s+', text)
            if part.strip()]


def narration_beats(text, group_regular=True):
    beats = []
    for paragraph in re.split(r'\n\s*\n', text):
        sentences = split_sentences(paragraph)
        regular = []
        paragraph_beats = []

        def flush_regular():
            if regular:
                paragraph_beats.append(Beat(' '.join(regular), 0, 0, 170))
                regular.clear()

        for sentence in sentences:
            if sentence.rstrip('"”’»').endswith('?'):
                flush_regular()
                paragraph_beats.append(Beat(sentence, -7, 7, 350))
            elif len(re.findall(r"\b\w+(?:['’-]\w+)*\b", sentence)) <= 6:
                flush_regular()
                paragraph_beats.append(Beat(sentence, -10, -5, 280))
            else:
                if len(regular) == 4 or sum(map(len, regular)) + len(sentence) > 650:
                    flush_regular()
                regular.append(sentence)
                if not group_regular:
                    flush_regular()
        flush_regular()
        if paragraph_beats:
            last = paragraph_beats[-1]
            paragraph_beats[-1] = Beat(last.text, last.rate_change, last.pitch_change, 430)
            beats.extend(paragraph_beats)
    return beats


def cleanup_expressive(target):
    for suffix in PART_SUFFIXES:
        target.with_suffix(suffix).unlink(missing_ok=True)


def run_ffmpeg(ffmpeg, args, data=None):
    result = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', *args], input=data,
                            capture_output=True, timeout=90,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        details = result.stderr.decode('utf-8', errors='replace').strip()
        raise RuntimeError('FFmpeg không xử lý được âm thanh. ' + details[-500:])
    return result.stdout


async def render_beat(beat, voice, rate, pitch):
    import edge_tts

    rate = max(-50, min(100, rate + beat.rate_change))
    pitch = max(-50, min(50, pitch + beat.pitch_change))
    audio = bytearray()
    cues = []
    async for event in edge_tts.Communicate(
        beat.text, voice, rate=f'{rate:+d}%', pitch=f'{pitch:+d}Hz',
        boundary='SentenceBoundary', connect_timeout=15, receive_timeout=90,
    ).stream():
        if event['type'] == 'audio':
            audio.extend(event['data'])
        elif event['type'] == 'SentenceBoundary':
            cues.append(event)
    if not audio or not cues:
        raise RuntimeError('Dịch vụ không trả về đủ âm thanh và mốc phụ đề.')
    return audio, cues


def srt_time(samples):
    ms = round(samples * 1000 / SAMPLE_RATE)
    return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}'


async def synthesize_expressive(text, voice, rate, pitch, target, progress=None):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('Cần cài FFmpeg để ghép âm thanh cho giọng kể kịch tính.')
    beats = narration_beats(text)
    if not beats:
        raise ValueError('Hãy nhập kịch bản.')

    mp3, srt, script, wav = (target.with_suffix(suffix) for suffix in PART_SUFFIXES)
    captions = []
    elapsed_samples = 0
    published = []
    try:
        with wave.open(str(wav), 'wb') as joined:
            joined.setparams((1, 2, SAMPLE_RATE, 0, 'NONE', 'not compressed'))
            for index, beat in enumerate(beats):
                if progress:
                    progress(beat.text)
                audio, cues = await render_beat(beat, voice, rate, pitch)
                pcm = run_ffmpeg(ffmpeg, ['-f', 'mp3', '-i', 'pipe:0', '-f', 's16le',
                                          '-ac', '1', '-ar', str(SAMPLE_RATE), 'pipe:1'], audio)
                sample_count = len(pcm) // 2
                if not sample_count:
                    raise RuntimeError('Không đọc được đoạn âm thanh vừa tạo.')
                joined.writeframesraw(pcm)
                for cue in cues:
                    start = round(cue['offset'] * SAMPLE_RATE / 10_000_000)
                    end = round((cue['offset'] + cue['duration']) * SAMPLE_RATE / 10_000_000)
                    end = min(end, sample_count)
                    if end > start:
                        captions.append(f'{len(captions) + 1}\n'
                                        f'{srt_time(elapsed_samples + start)} --> '
                                        f'{srt_time(elapsed_samples + end)}\n{cue["text"]}\n')
                elapsed_samples += sample_count
                if index + 1 < len(beats):
                    pause = beat.pause_ms * SAMPLE_RATE // 1000
                    joined.writeframesraw(b'\0\0' * pause)
                    elapsed_samples += pause
        if not captions:
            raise RuntimeError('Không nhận được mốc thời gian phụ đề hợp lệ.')
        run_ffmpeg(ffmpeg, ['-y', '-f', 'wav', '-i', str(wav), '-codec:a', 'libmp3lame',
                            '-q:a', '2', '-f', 'mp3', str(mp3)])
        srt.write_text('\n'.join(captions), encoding='utf-8-sig')
        script.write_text(text, encoding='utf-8')
        for staged, destination in ((srt, target.with_suffix('.srt')),
                                    (script, target.with_suffix('.txt')), (mp3, target)):
            staged.replace(destination)
            published.append(destination)
    except Exception:
        for path in published:
            path.unlink(missing_ok=True)
        raise
    finally:
        cleanup_expressive(target)

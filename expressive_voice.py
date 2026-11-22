"""Generate narration with pace changes and pauses between spoken beats."""

import re
import shutil
import subprocess
import wave
from pathlib import Path
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


def apply_ghost_effect(audio_path, reverb_percent, bass_db):
    """Áp dụng hiệu ứng giọng ma (vàng + trầm) lên file âm thanh đã tạo.

    - Độ vang: dùng aecho (echo trôi)에 các độ trễ ngắn tạo cảm giác réo, âm diffused.
    - Độ trầm: dùng bass EQ tăng/cắt tần số thấp quanh 100 Hz.
    Không thay đổi thời lượng -> mốc phụ đề (SRT) vẫn giữ nguyên.
    """
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('Cần cài FFmpeg để áp dụng hiệu ứng giọng ma.')

    reverb = max(0, min(100, int(reverb_percent))) / 100.0
    bass = max(-20, min(20, int(bass_db)))

    filters = []
    if bass != 0:
        filters.append(f'bass=g={bass}:f=100:w=2')
    if reverb > 0:
        delays = '60|120|180|240|320|400'
        decays = '|'.join(f'{0.7 * reverb * (0.72 ** i):.2f}' for i in range(6))
        filters.append(f'aecho=0.8:0.9:{delays}:{decays}')

    if not filters:
        return audio_path

    filter_str = ','.join(filters)
    audio_path = Path(audio_path)
    tmp = audio_path.with_name(audio_path.stem + '.ghost' + audio_path.suffix)
    try:
        run_ffmpeg(ffmpeg, ['-y', '-i', str(audio_path), '-af', filter_str, str(tmp)])
        tmp.replace(audio_path)
    finally:
        tmp.unlink(missing_ok=True)
    return audio_path


def scale_srt_file(srt_path, factor):
    """Đổi scale mọi mốc thời gian trong file SRT theo hệ số factor."""
    text = srt_path.read_text(encoding='utf-8-sig')

    def repl(m):
        h, mn, s, ms = (int(g) for g in m.groups())
        total = h * 3600 + mn * 60 + s + ms / 1000.0
        total *= factor
        h = int(total // 3600)
        mn = int((total % 3600) // 60)
        s = int(total % 60)
        ms = int(round((total - int(total)) * 1000))
        if ms >= 1000:
            s += 1
            ms = 0
        if s >= 60:
            mn += 1
            s = 0
        if mn >= 60:
            h += 1
            mn = 0
        return f'{h:02}:{mn:02}:{s:02},{ms:03}'

    text = re.sub(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', repl, text)
    srt_path.write_text(text, encoding='utf-8-sig')


def apply_stretch(audio_path, srt_path, stretch_percent):
    """Kéo dài âm thanh bằng atempo (FFmpeg) rồi scale lại mốc phụ đề SRT.

    stretch_percent: 100 = bình thường, 150 = dài gấp 1.5 lần, 200 = dài gấp 2 lần…
    atempo mỗi instancia chỉ chấp nhận 0.5–2.0, nên chain nhiều instancia nếu cần.
    """
    ffmpeg = shutil.which('ffmpeg')
    ffprobe = shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('Cần FFmpeg/FFprobe để kéo dài giọng.')

    stretch = max(100, min(500, int(stretch_percent))) / 100.0
    if stretch <= 1.0:
        return

    def probe_duration(path):
        result = subprocess.run(
            [ffprobe, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
            capture_output=True, text=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return float(result.stdout.strip() or '0')

    old_duration = probe_duration(audio_path)

    tempo = 1.0 / stretch
    filters = []
    remaining = tempo
    while remaining < 0.5:
        filters.append('atempo=0.5')
        remaining /= 0.5
    while remaining > 2.0:
        filters.append('atempo=2.0')
        remaining /= 2.0
    filters.append(f'atempo={remaining:.4f}')

    audio_path = Path(audio_path)
    tmp = audio_path.with_name(audio_path.stem + '.stretch' + audio_path.suffix)
    try:
        run_ffmpeg(ffmpeg, ['-y', '-i', str(audio_path), '-af', ','.join(filters), str(tmp)])
        tmp.replace(audio_path)
    finally:
        tmp.unlink(missing_ok=True)

    new_duration = probe_duration(audio_path)
    factor = new_duration / old_duration if old_duration > 0 else stretch

    srt_path = Path(srt_path)
    if srt_path.exists():
        scale_srt_file(srt_path, factor)


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

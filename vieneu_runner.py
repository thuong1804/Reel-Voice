"""VieNeu v3 backend, run exclusively in its own virtual environment."""
import os
from pathlib import Path
import json
import re
import sys
import subprocess
import shutil
import tempfile
import unicodedata
from expressive_voice import narration_beats, run_ffmpeg
from story_audio import render_story

BASE = Path(__file__).resolve().parent
os.environ.setdefault('HF_HOME', str(BASE / 'models' / 'huggingface'))
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '60')
if (BASE / '.vieneu_ready').exists():
    os.environ.setdefault('HF_HUB_OFFLINE', '1')


def emit(kind, value):
    print(json.dumps({'kind': kind, 'value': value}, ensure_ascii=True), flush=True)


def stamp(seconds):
    ms = round(seconds * 1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'


def atempo_filters(tempo):
    filters = []
    remaining = max(0.35, min(3.0, float(tempo)))
    while remaining < 0.5:
        filters.append('atempo=0.5')
        remaining /= 0.5
    while remaining > 2.0:
        filters.append('atempo=2.0')
        remaining /= 2.0
    if abs(remaining - 1.0) > 1e-3:
        filters.append(f'atempo={remaining:.4f}')
    return filters


def _sentence_contour(sentence, temp):
    """Return restrained punctuation cues before adding a mood's tonal base."""
    stripped = sentence.strip().rstrip('"”’»')
    words = re.findall(r"\b\w+(?:['’-]\w+)*\b", stripped)
    if stripped.endswith('?'):
        return 0.94, 0.4, min(1.1, temp + 0.08), [], 0.0
    if stripped.endswith('!'):
        return 1.05, 0.3, min(1.15, temp + 0.12), [], 1.0
    # Suspension is intentional even in a short phrase.
    if stripped.endswith(('...', '…')):
        return 0.93, -0.5, min(1.1, temp + 0.05), [], 0.0
    if len(words) <= 6:
        return 0.90, -1.0, min(1.1, temp + 0.08), ['bass=g=2.5:f=110:w=2'], 0.0
    return 1.0, 0.0, temp, [], 0.0


def sentence_profile(sentence, base_temp, expressive, mood=None):
    """Combine a mood's base with sentence cues instead of flattening its delivery."""
    temp = max(0.5, min(1.2, float(base_temp)))
    profiles = {
        'tram': (0.92, -1.2, temp, ['bass=g=4:f=110:w=2'], 0.0),
        'tham': (0.88, -0.5, min(1.1, temp + 0.08),
                 ['highpass=f=150', 'treble=g=4:f=3500:w=2',
                  'aecho=0.8:0.88:45|90:0.20|0.12'], -1.0),
        'gap': (1.09, 0.6, min(1.15, temp + 0.12), [], 1.0),
        'ma': (0.80, -2.0, temp,
               ['bass=g=6:f=100:w=2',
                'aecho=0.8:0.9:60|120|180|240|320:0.40|0.28|0.20|0.14|0.09'], 0.0),
    }
    profile = profiles.get(mood)
    if profile is None:
        return _sentence_contour(sentence, temp) if expressive else (1.0, 0.0, temp, [], 0.0)

    # Explicit MOOD is an instruction even in Natural/Short delivery. Half-strength
    # contours keep its character without doubling the bass or exaggerating it.
    speed, pitch, sampling, filters, gain = profile
    cue_speed, cue_pitch, cue_temp, _, cue_gain = _sentence_contour(sentence, temp)
    return (speed * (1 + (cue_speed - 1) * 0.5), pitch + cue_pitch * 0.5,
            max(sampling, cue_temp), filters, gain + cue_gain * 0.5)


def match_loudness(src_wav, dst_wav, gain_db=0.0):
    """Match active RMS loudness of dst_wav to src_wav (+ optional gain_db) without clipping."""
    import numpy as np
    import soundfile as sf

    src, _ = sf.read(str(src_wav), dtype='float32')
    dst, sr = sf.read(str(dst_wav), dtype='float32')
    if not src.size or not dst.size:
        return

    def active_rms(x):
        mask = np.abs(x) > 0.01
        sample = x[mask] if np.any(mask) else x
        return float(np.sqrt(np.mean(sample * sample)))

    src_rms = active_rms(src)
    dst_rms = active_rms(dst)
    if src_rms < 1e-5 or dst_rms < 1e-5:
        return
    scale = (src_rms / dst_rms) * (10.0 ** (gain_db / 20.0))
    scale = max(0.25, min(6.0, scale))
    out = dst * scale
    peak = float(np.max(np.abs(out)))
    if peak > 0.96:
        # Soft-limit only peaks above 0.96 so speech loudness stays matched without harsh clipping.
        out = np.where(np.abs(out) > 0.90,
                       np.sign(out) * (0.90 + 0.06 * np.tanh((np.abs(out) - 0.90) / 0.15)),
                       out)
    sf.write(str(dst_wav), out.astype(np.float32), sr, format='WAV', subtype='PCM_16')


def apply_sentence_filters(ffmpeg, src_wav, dst_wav, sample_rate, speed, pitch_st, extra_filters, gain_db=0.0):
    pitch_factor = 2.0 ** (pitch_st / 12.0) if abs(pitch_st) > 1e-3 else 1.0
    tempo = speed / pitch_factor
    filters = []
    if abs(pitch_st) > 1e-3:
        filters.append(f'asetrate={sample_rate * pitch_factor:.2f}')
        filters.append(f'aresample={sample_rate}')
    filters.extend(atempo_filters(tempo))
    filters.extend(extra_filters)
    if not filters and abs(gain_db) <= 1e-3:
        return src_wav
    if not ffmpeg:
        raise RuntimeError('Cần cài FFmpeg để chỉnh tốc độ, cao độ hoặc sắc thái.')
    if filters:
        run_ffmpeg(ffmpeg, ['-y', '-i', str(src_wav), '-af', ','.join(filters), str(dst_wav)])
    else:
        shutil.copyfile(str(src_wav), str(dst_wav))
    if extra_filters or abs(gain_db) > 1e-3:
        match_loudness(src_wav, dst_wav, gain_db=gain_db)
    return dst_wav


def save_voice_manifest(tts):
    voices = tts.list_preset_voices()
    manifest = [{'label': str(label), 'id': str(voice_id)} for label, voice_id in voices]
    (BASE / 'vieneu_voices.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return voices


def handle_add_voice(tts, spec_path):
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    name = str(spec.get('name', '')).strip()
    audio_path = Path(spec['audio'])
    description = str(spec.get('description') or 'Giọng mẫu custom').strip()
    start_sec = max(0.0, float(spec.get('start_sec', 0.0)))
    denoise = bool(spec.get('denoise', True))
    if not name:
        raise ValueError('Tên giọng mẫu không được để trống.')
    if not audio_path.is_file():
        raise ValueError(f'Không tìm thấy file âm thanh: {audio_path}')

    emit('progress', f'Đang chuẩn bị đoạn mẫu cho giọng "{name}"…')
    ffmpeg = shutil.which('ffmpeg')
    temp_dir = None
    ref_wav = audio_path
    try:
        if ffmpeg:
            temp_dir = tempfile.TemporaryDirectory(prefix='vieneu_ref_')
            ref_wav = Path(temp_dir.name) / 'ref.wav'
            cmd = ['-y']
            if start_sec > 0:
                cmd += ['-ss', f'{start_sec:.3f}']
            cmd += ['-i', str(audio_path), '-t', '10', '-vn', '-ac', '1',
                    '-ar', '48000', '-codec:a', 'pcm_s16le', str(ref_wav)]
            run_ffmpeg(ffmpeg, cmd)
        elif audio_path.suffix.lower() != '.wav':
            raise RuntimeError('Cần cài FFmpeg để nạp file mẫu không phải WAV.')

        emit('progress', f'Đang trích xuất chất giọng & ngữ điệu "{name}"…')
        tts.add_voice(name, str(ref_wav), denoise=denoise,
                      description=description, save=True)
        save_voice_manifest(tts)
        (BASE / '.vieneu_ready').write_text('v3turbo CPU ready', encoding='utf-8')
        emit('done', name)
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def handle_remove_voice(tts, voice_name):
    name = str(voice_name).strip()
    if not name:
        raise ValueError('Thiếu tên giọng cần xóa.')
    tts.remove_voice(name, save=True)
    save_voice_manifest(tts)
    emit('done', name)


def render_vieneu_story(tts, default_voice, job):
    """Load the model once, switching preset voices between character turns."""
    import inspect
    import numpy as np
    import soundfile as sf

    ffmpeg = shutil.which('ffmpeg')
    base_temp = float(job.get('temperature', 0.85))
    default_expressive = bool(job.get('expressive', False))
    infer_params = inspect.signature(tts.infer).parameters
    supports_sampling = ('temperature' in infer_params or
                         any(p.kind == inspect.Parameter.VAR_KEYWORD for p in infer_params.values()))

    def render_sentence(sentence, destination, item=None):
        item = item if isinstance(item, dict) else {}
        selected_voice = item.get('voice', 'vieneu:' + default_voice)
        if not selected_voice.startswith('vieneu:'):
            raise ValueError('Tác vụ VieNeu nhận giọng không đúng loại.')
        selected_voice = selected_voice.split(':', 1)[1]
        if selected_voice == 'default':
            selected_voice = default_voice
        mood = item.get('mood')
        item_expressive = bool(item.get('expressive', default_expressive))
        speed_mul, pitch_st, temp, extra_filters, gain_db = sentence_profile(
            sentence, base_temp, item_expressive, mood=mood)
        infer_kwargs = {'voice': selected_voice}
        if supports_sampling:
            infer_kwargs.update(temperature=temp, top_k=30, top_p=0.95)
        audio = np.asarray(
            tts.infer(unicodedata.normalize('NFC', sentence), **infer_kwargs),
            dtype=np.float32).reshape(-1)
        if not audio.size:
            raise RuntimeError('VieNeu không trả về âm thanh cho câu vừa đọc.')
        raw = destination.with_suffix('.wav')
        tts.save(audio, str(raw))
        info = sf.info(str(raw))
        rate = item.get('rate', job['rate'])
        base_speed = 1 + rate / 100
        final_wav = apply_sentence_filters(
            ffmpeg, raw, destination.with_suffix('.adjusted.wav'),
            info.samplerate, base_speed * speed_mul, pitch_st, extra_filters, gain_db=gain_db)
        duration = sf.info(str(final_wav)).duration
        return final_wav, [(0, duration, sentence)]

    return render_story(job['story_plan'], Path(job['target']), render_sentence,
                        lambda value: emit('progress', value), preview=job.get('audition', False))


def main():
    import numpy as np
    import soundfile as sf
    from vieneu import Vieneu
    emit('progress', 'Đang nạp VieNeu v3 Turbo CPU từ máy.' if (BASE / '.vieneu_ready').exists()
         else 'Đang nạp VieNeu v3 Turbo CPU; lần đầu cần tải model.')
    tts = Vieneu(mode='v3turbo', backend='onnx')
    voices = save_voice_manifest(tts)

    if sys.argv[1] == '--setup':
        emit('done', f'VieNeu sẵn sàng: {len(voices)} giọng.')
        return
    if sys.argv[1] == '--add-voice':
        handle_add_voice(tts, sys.argv[2])
        return
    if sys.argv[1] == '--remove-voice':
        handle_remove_voice(tts, sys.argv[2])
        return

    job = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    target = Path(job['target'])
    voice = job['voice']
    if voice == 'default':
        voice = voices[0][1]
    base_speed = 1 + job['rate'] / 100
    base_temp = float(job.get('temperature', 0.85))
    expressive = bool(job.get('expressive', False))
    ffmpeg = shutil.which('ffmpeg')

    if job.get('story_plan') is not None:
        output = render_vieneu_story(tts, voice, job)
        (BASE / '.vieneu_ready').write_text('v3turbo CPU ready', encoding='utf-8')
        emit('done', str(output))
        return

    if expressive and not ffmpeg:
        raise RuntimeError('Cần cài FFmpeg để dùng cách đọc Kịch tính với VieNeu.')
    beats = narration_beats(job['text'], group_regular=False) if expressive else []
    sentences = ([beat.text for beat in beats] if expressive else
                 [s.strip() for s in re.split(r'(?<=[.!?…])\s+|\n+', job['text']) if s.strip()])
    elapsed, subtitles, chunks = 0.0, [], []
    sample_rate = 48000
    for i, sentence in enumerate(sentences):
        emit('progress', f'VieNeu: câu {i+1}/{len(sentences)} — {sentence[:80]}')
        speed_mul, pitch_st, temp, extra_filters, gain_db = sentence_profile(
            sentence, base_temp, expressive, mood=None)
        spoken_text = unicodedata.normalize('NFC', sentence)
        audio = np.asarray(
            tts.infer(spoken_text, voice=voice, temperature=temp, top_k=30, top_p=0.95),
            dtype=np.float32).reshape(-1)
        probe = target.with_suffix('.chunk.wav')
        adjusted = target.with_suffix('.chunk.adj.wav')
        tts.save(audio, str(probe))
        info = sf.info(str(probe))
        sample_rate = info.samplerate
        try:
            used_wav = apply_sentence_filters(
                ffmpeg, probe, adjusted, sample_rate,
                base_speed * speed_mul if (expressive or abs(base_speed - 1.0) > 1e-3) else 1.0,
                pitch_st, extra_filters, gain_db=gain_db)
            audio, sample_rate = sf.read(str(used_wav), dtype='float32')
        finally:
            probe.unlink(missing_ok=True)
            adjusted.unlink(missing_ok=True)
        if not audio.size:
            raise RuntimeError(f'Không có âm thanh cho câu {i+1}.')
        duration = len(audio) / sample_rate
        subtitles.append((elapsed, elapsed + duration, sentence))
        elapsed += duration
        chunks.append(audio)
        if expressive and i + 1 < len(beats):
            pause = round(sample_rate * beats[i].pause_ms / 1000)
            chunks.append(np.zeros(pause, dtype=np.float32))
            elapsed += pause / sample_rate
    wav = target.with_suffix('.wav.part' if expressive else '.wav')
    sf.write(str(wav), np.concatenate(chunks), sample_rate, format='WAV', subtype='PCM_16')
    output = wav
    if ffmpeg:
        mp3 = target.with_suffix('.mp3.part') if expressive else target
        command = [ffmpeg, '-y', '-v', 'error', '-i', str(wav),
                   '-codec:a', 'libmp3lame', '-q:a', '2', '-f', 'mp3', str(mp3)]
        result = subprocess.run(command, capture_output=True,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace'))
        output = target
    elif job['rate']:
        raise RuntimeError('Cần FFmpeg để chỉnh tốc độ. Đặt tốc độ 0 để xuất WAV.')
    srt = '\n'.join(f'{i+1}\n{stamp(start)} --> {stamp(end)}\n{text}\n'
                    for i, (start, end, text) in enumerate(subtitles))
    target.with_suffix('.srt').write_text(srt, encoding='utf-8-sig')
    target.with_suffix('.txt').write_text(job['text'], encoding='utf-8')
    if expressive:
        wav.unlink()
        mp3.replace(target)
    (BASE / '.vieneu_ready').write_text('v3turbo CPU ready', encoding='utf-8')
    emit('done', str(output))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        emit('error', f'{type(exc).__name__}: {exc}')
        raise SystemExit(1)

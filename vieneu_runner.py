"""VieNeu v3 backend, run exclusively in its own virtual environment."""
import os
from pathlib import Path
import json
import re
import sys
import subprocess
import shutil
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

def main():
    import numpy as np
    import soundfile as sf
    from vieneu import Vieneu
    emit('progress', 'Đang nạp VieNeu v3 Turbo CPU từ máy.' if (BASE / '.vieneu_ready').exists()
         else 'Đang nạp VieNeu v3 Turbo CPU; lần đầu cần tải model.')
    tts = Vieneu(mode='v3turbo', backend='onnx')
    voices = tts.list_preset_voices()
    manifest = [{'label': str(label), 'id': str(voice_id)} for label, voice_id in voices]
    (BASE / 'vieneu_voices.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    if sys.argv[1] == '--setup':
        emit('done', f'VieNeu sẵn sàng: {len(voices)} giọng.')
        return
    job = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    target = Path(job['target'])
    voice = job['voice']
    if voice == 'default':
        voice = voices[0][1]
    ffmpeg = shutil.which('ffmpeg')
    if job.get('story_plan') is not None:
        def render_sentence(sentence, destination):
            audio = np.asarray(tts.infer(unicodedata.normalize('NFC', sentence), voice=voice),
                               dtype=np.float32).reshape(-1)
            if not audio.size:
                raise RuntimeError('VieNeu không trả về âm thanh cho câu vừa đọc.')
            raw = destination.with_suffix('.wav')
            tts.save(audio, str(raw))
            speed = 1 + job['rate'] / 100
            if speed != 1:
                adjusted = destination.with_suffix('.adjusted.wav')
                run_ffmpeg(ffmpeg, ['-y', '-i', str(raw), '-af', f'atempo={speed}', str(adjusted)])
                raw = adjusted
            duration = sf.info(str(raw)).duration
            return raw, [(0, duration, sentence)]
        output = render_story(job['story_plan'], target, render_sentence,
                              lambda value: emit('progress', value), preview=job.get('audition', False))
        emit('done', str(output))
        return
    expressive = job.get('expressive', False)
    if expressive and not ffmpeg:
        raise RuntimeError('Cần cài FFmpeg để dùng cách đọc Kịch tính với VieNeu.')
    beats = narration_beats(job['text'], group_regular=False) if expressive else []
    sentences = ([beat.text for beat in beats] if expressive else
                 [s.strip() for s in re.split(r'(?<=[.!?…])\s+|\n+', job['text']) if s.strip()])
    elapsed, subtitles, chunks = 0.0, [], []
    for i, sentence in enumerate(sentences):
        emit('progress', f'VieNeu: câu {i+1}/{len(sentences)} — {sentence[:80]}')
        spoken_text = unicodedata.normalize('NFC', sentence)
        audio = np.asarray(tts.infer(spoken_text, voice=voice), dtype=np.float32).reshape(-1)
        # Use SDK save to obtain the backend's actual sample rate.
        probe = target.with_suffix('.chunk.wav')
        tts.save(audio, str(probe))
        audio, sample_rate = sf.read(str(probe), dtype='float32')
        probe.unlink(missing_ok=True)
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
    speed = 1 + job['rate'] / 100
    output = wav
    if ffmpeg:
        command = [ffmpeg, '-y', '-v', 'error', '-i', str(wav)]
        if speed != 1:
            command += ['-af', f'atempo={speed}']
        mp3 = target.with_suffix('.mp3.part') if expressive else target
        command += ['-codec:a', 'libmp3lame', '-q:a', '2', '-f', 'mp3', str(mp3)]
        result = subprocess.run(command, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace'))
        output = target
    elif job['rate']:
        raise RuntimeError('Cần FFmpeg để chỉnh tốc độ. Đặt tốc độ 0 để xuất WAV.')
    timing_factor = speed if output == target else 1
    srt = '\n'.join(f'{i+1}\n{stamp(start/timing_factor)} --> {stamp(end/timing_factor)}\n{text}\n'
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

"""Reel Voice: Windows script narration using the online Edge TTS service."""
import asyncio
import os
import sys
from pathlib import Path
import queue
import re
import multiprocessing as mp
import time
import json
import subprocess
import tempfile
import wave
import shutil
import hashlib
import ctypes
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

from expressive_voice import cleanup_expressive, synthesize_expressive
from story_audio import (cleanup_story, read_cues,
                         read_effects, render_story, script_plan, script_excerpt)
from dialogue import CHARACTER_HEADER, INLINE_VOICE, default_characters, inline_turns, read_characters
from short_pacing import STYLE as SHORT_STYLE, VERSION as SHORT_VERSION
from short_pacing import canonical_script, has_headers, short_plan

BASE = Path(__file__).resolve().parent


def use_app_python():
    """Use the app's dependencies even when launched through a file association."""
    executable = 'pythonw.exe' if Path(sys.executable).name.lower() == 'pythonw.exe' else 'python.exe'
    interpreter = BASE / '.venv' / 'Scripts' / executable
    if interpreter.is_file() and Path(sys.executable).resolve() != interpreter.resolve():
        os.execv(str(interpreter), [str(interpreter), str(BASE / 'reel_voice.py'), *sys.argv[1:]])


VOICES = {
    'VieNeu v3 · Tiếng Việt · Mặc định': 'vieneu:default',
    'FREE Offline · Nữ Mỹ · Zira': 'offline:Microsoft Zira Desktop',
    'Tiếng Việt · Nam · Nam Minh': 'vi-VN-NamMinhNeural',
    'Tiếng Việt · Nữ · Hoài My': 'vi-VN-HoaiMyNeural',
    'English US · Male · Guy': 'en-US-GuyNeural',
    'English US · Female · Jenny': 'en-US-JennyNeural',
    'English UK · Male · Ryan': 'en-GB-RyanNeural',
    'English UK · Female · Sonia': 'en-GB-SoniaNeural',
}
try:
    for preset in json.loads((BASE / 'vieneu_voices.json').read_text(encoding='utf-8')):
        VOICES['VieNeu v3 · ' + preset['label']] = 'vieneu:' + preset['id']
except (OSError, ValueError, KeyError):
    pass

def vieneu_synthesize(text, voice, rate, target, events, expressive=False, plan=None, audition=False):
    interpreter = BASE / '.venv-vieneu' / 'Scripts' / 'python.exe'
    if not interpreter.exists():
        raise RuntimeError('Chưa cài VieNeu. Hãy chạy Cai_VieNeu.cmd trong thư mục ứng dụng.')
    job = target.with_suffix('.job.json')
    job.write_text(json.dumps({'text': text, 'voice': voice.split(':', 1)[1],
                              'rate': rate, 'target': str(target), 'expressive': expressive,
                              'story_plan': plan, 'audition': audition}, ensure_ascii=False), encoding='utf-8')
    output = None
    try:
        with target.with_suffix('.log.txt').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([str(interpreter), '-u', str(BASE / 'vieneu_runner.py'), '--job', str(job)],
                stdout=subprocess.PIPE, stderr=log, text=True, encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW)
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('kind') == 'progress':
                    events.put(('progress', event['value']))
                elif event.get('kind') == 'done':
                    output = Path(event['value'])
                elif event.get('kind') == 'error':
                    raise RuntimeError(event['value'])
            code = process.wait()
        if code or not output or not output.exists():
            raise RuntimeError('VieNeu chưa xuất được âm thanh. Xem file .log.txt trong thư mục xuất.')
        return output
    finally:
        job.unlink(missing_ok=True)
        if expressive:
            cleanup_expressive(target)
            target.with_suffix('.chunk.wav').unlink(missing_ok=True)

def paragraphs(text):
    return [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]


def transcript_text(text):
    """Remove leading transcript timestamps and reconnect wrapped speech."""
    text = re.sub(r'\\[ \t]*(?=\r?$)', '', text, flags=re.MULTILINE)
    timestamp = r'^[ \t]*\[(?:\d+:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?\][ \t]*'
    if not re.search(timestamp, text, flags=re.MULTILINE):
        return text
    cleaned = re.sub(timestamp, '', text, flags=re.MULTILINE)
    return '\n\n'.join(' '.join(part.splitlines()) for part in paragraphs(cleaned))

def srt_time(seconds):
    milliseconds = round(seconds * 1000)
    return f'{milliseconds // 3600000:02}:{milliseconds // 60000 % 60:02}:{milliseconds // 1000 % 60:02},{milliseconds % 1000:03}'

def offline_synthesize(text, voice, rate, pitch, target, events):
    if pitch:
        events.put(('progress', 'Giọng offline dùng cao độ mặc định.'))
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text) if s.strip()]
    scratch = BASE / 'work'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='reelvoice_', dir=scratch) as temp:
        folder = Path(temp)
        job = {'voice': voice.split(':', 1)[1], 'rate': max(-10, min(10, round(rate / 10))),
               'sentences': sentences, 'folder': temp}
        (folder / 'job.json').write_text(json.dumps(job), encoding='utf-8-sig')
        script = '''param([string]$JobPath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$job = Get-Content -LiteralPath $JobPath -Raw -Encoding UTF8 | ConvertFrom-Json
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $speaker.SelectVoice($job.voice)
  $speaker.Rate = [int]$job.rate
  for ($i = 0; $i -lt $job.sentences.Count; $i++) {
    $file = Join-Path $job.folder ($i.ToString() + '.wav')
    $speaker.SetOutputToWaveFile($file)
    $speaker.Speak([string]$job.sentences[$i])
    $speaker.SetOutputToNull()
  }
} finally { $speaker.Dispose() }
'''
        (folder / 'speak.ps1').write_text(script, encoding='utf-8-sig')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(folder / 'speak.ps1'), '-JobPath', str(folder / 'job.json')],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=150)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace')[-1500:])
        wav_target = target.with_suffix('.wav')
        subtitles, elapsed = [], 0.0
        with wave.open(str(wav_target), 'wb') as combined:
            for i, sentence in enumerate(sentences):
                with wave.open(str(folder / f'{i}.wav'), 'rb') as audio:
                    if i == 0:
                        combined.setparams(audio.getparams())
                    duration = audio.getnframes() / audio.getframerate()
                    combined.writeframes(audio.readframes(audio.getnframes()))
                subtitles.append(f'{i+1}\n{srt_time(elapsed)} --> {srt_time(elapsed+duration)}\n{sentence}\n')
                elapsed += duration
        target.with_suffix('.srt').write_text('\n'.join(subtitles), encoding='utf-8-sig')
        target.with_suffix('.txt').write_text(text, encoding='utf-8')
        if shutil.which('ffmpeg'):
            conversion = subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(wav_target),
                '-codec:a', 'libmp3lame', '-q:a', '2', str(target)], capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
            if conversion.returncode == 0:
                return target
        return wav_target

async def synthesize(text, voice, rate, pitch, target, progress=None):
    import edge_tts
    subs = edge_tts.SubMaker()
    temporary = target.with_suffix('.mp3.part')
    try:
        with temporary.open('wb') as audio:
            async for event in edge_tts.Communicate(
                text, voice, rate=f'{rate:+d}%', pitch=f'{pitch:+d}Hz',
                boundary='SentenceBoundary', connect_timeout=15, receive_timeout=90
            ).stream():
                if event['type'] == 'audio':
                    audio.write(event['data'])
                elif event['type'] in ('SentenceBoundary', 'WordBoundary'):
                    subs.feed(event)
                    if progress:
                        progress(event.get('text', ''))
        if not temporary.stat().st_size:
            raise RuntimeError('Dịch vụ không trả về âm thanh.')
        subtitle = subs.get_srt()
        if not subtitle.strip():
            raise RuntimeError('Không nhận được mốc thời gian phụ đề. Hãy thử lại.')
        target.with_suffix('.srt').write_text(subtitle, encoding='utf-8-sig')
        temporary.replace(target)
        target.with_suffix('.txt').write_text(text, encoding='utf-8')
    finally:
        temporary.unlink(missing_ok=True)

def worker(events, text, voice, rate, pitch, target, expressive=False, plan=None, audition=False):
    try:
        plan_voices = {item.get('voice', voice) for item in (plan or []) if item['kind'] == 'speech'}
        if plan is not None and plan_voices and all(value.startswith('vieneu:') for value in plan_voices):
            base_voice = voice if voice.startswith('vieneu:') else next(iter(plan_voices))
            output = vieneu_synthesize(text, base_voice, rate, Path(target), events,
                                       expressive, plan, audition)
        elif plan is None and voice.startswith('vieneu:'):
            output = vieneu_synthesize(text, voice, rate, Path(target), events, expressive, plan, audition)
        elif plan is not None:
            def render_sentence(sentence, destination, item):
                selected_voice = item.get('voice', voice)
                selected_rate = item.get('rate', rate)
                selected_pitch = item.get('pitch', pitch)
                selected_expressive = item.get('expressive', expressive)
                if selected_voice.startswith('vieneu:'):
                    audio = vieneu_synthesize(sentence, selected_voice, selected_rate, destination,
                                               events, selected_expressive)
                elif selected_voice.startswith('offline:'):
                    audio = offline_synthesize(sentence, selected_voice, selected_rate,
                                               selected_pitch, destination, events)
                else:
                    render = synthesize_expressive if selected_expressive else synthesize
                    asyncio.run(render(sentence, selected_voice, selected_rate, selected_pitch, destination))
                    audio = destination
                return audio, read_cues(destination.with_suffix('.srt'))
            output = render_story(plan, Path(target), render_sentence,
                                  lambda value: events.put(('progress', value)), preview=audition)
        elif voice.startswith('offline:'):
            output = offline_synthesize(text, voice, rate, pitch, Path(target), events)
        else:
            render = synthesize_expressive if expressive else synthesize
            asyncio.run(render(text, voice, rate, pitch, Path(target),
                lambda sentence: events.put(('progress', sentence))))
            output = target
        events.put(('done', str(output)))
    except Exception as exc:
        events.put(('error', f'{type(exc).__name__}: {exc}'))

class AudioPlayer:
    """Play MP3/WAV through Windows without launching an external app."""
    def __init__(self):
        self.api = ctypes.WinDLL('winmm')
        self.api.mciSendStringW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p,
                                           ctypes.c_uint, ctypes.c_void_p]
        self.api.mciSendStringW.restype = ctypes.c_uint
        self.api.mciGetErrorStringW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
        self.alias = 'reelvoice_audio'
        self.opened = False

    def command(self, command):
        result = ctypes.create_unicode_buffer(512)
        error = self.api.mciSendStringW(command, result, len(result), None)
        if error:
            self.api.mciGetErrorStringW(error, result, len(result))
            raise OSError(result.value or f'Windows audio error {error}')
        return result.value

    def stop(self):
        if self.opened:
            self.command(f'close {self.alias}')
            self.opened = False

    def play(self, path):
        self.stop()
        kind = 'waveaudio' if path.suffix.lower() == '.wav' else 'mpegvideo'
        self.command(f'open "{path.resolve()}" type {kind} alias {self.alias}')
        self.opened = True
        try:
            self.command(f'play {self.alias}')
        except OSError:
            self.stop()
            raise

    def playing(self):
        return self.opened and self.command(f'status {self.alias} mode') == 'playing'


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Reel Voice 2.0 · Short tâm linh · Nhịp đọc 55 giây')
        self.geometry('1000x750')
        self.minsize(800, 600)
        self.events = mp.Queue()
        self.process = None
        self.busy = False
        self.last_audio = None
        self.preview_audio = None
        self.preview_temp = None
        self.player = AudioPlayer()
        self.folder = BASE / 'outputs' / 'audio'
        self.characters_path = BASE / 'outputs' / 'characters.json'
        self.fx_presets_path = BASE / 'outputs' / 'voice_effect_presets.json'
        self.effect_sample_path = BASE / 'samples' / 'voice_effect_sample.mp3'
        character_warning = ''
        try:
            self.characters = read_characters(self.characters_path, VOICES)
        except (OSError, ValueError) as exc:
            self.characters = default_characters(VOICES)
            character_warning = 'Không đọc được thiết lập nhân vật; đang dùng mẫu Nam / Nữ. ' + str(exc)
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TButton', padding=7)
        root = ttk.Frame(self, padding=18)
        root.pack(fill='both', expand=True)
        ttk.Label(root, text='REEL VOICE', font=('Segoe UI', 22, 'bold')).pack(anchor='w')
        ttk.Label(root, text='VieNeu v3: giọng Việt trên máy • Zira: giọng Mỹ offline • Edge: trực tuyến. VieNeu tải model ở lần đầu.').pack(anchor='w', pady=(0, 14))
        settings = ttk.LabelFrame(root, text='Giọng đọc', padding=10)
        settings.pack(fill='x')
        default_voice = next((label for label, value in VOICES.items() if value == 'vieneu:Hải Đăng'), next(iter(VOICES)))
        self.voice = tk.StringVar(value=default_voice)
        ttk.Combobox(settings, textvariable=self.voice, values=list(VOICES), state='readonly', width=48).grid(row=0, column=0, padx=5)
        ttk.Label(settings, text='Tốc độ %').grid(row=0, column=1, padx=5)
        self.rate = tk.StringVar(value='-5')
        self.rate_box = ttk.Spinbox(settings, from_=-50, to=100, textvariable=self.rate, width=6)
        self.rate_box.grid(row=0, column=2)
        ttk.Label(settings, text='Cao độ Hz').grid(row=0, column=3, padx=5)
        self.pitch = tk.StringVar(value='0')
        self.pitch_box = ttk.Spinbox(settings, from_=-50, to=50, textvariable=self.pitch, width=6)
        self.pitch_box.grid(row=0, column=4)
        self.voice_sample = ttk.Button(settings, text='▶ Nghe mẫu giọng',
            command=lambda: self.start(True, voice_sample=True))
        self.voice_sample.grid(row=1, column=0, sticky='w', padx=5, pady=(8, 0))
        self.stop_audio = ttk.Button(settings, text='■ Dừng nghe', command=self.stop_playback, state='disabled')
        self.stop_audio.grid(row=1, column=1, columnspan=2, sticky='w', pady=(8, 0))
        ttk.Label(settings, text='VieNeu: cao độ 0').grid(row=1, column=3, columnspan=2, sticky='w')
        delivery = ttk.Frame(settings)
        delivery.grid(row=2, column=0, columnspan=5, sticky='w', padx=5, pady=(8, 0))
        ttk.Label(delivery, text='Cách đọc').pack(side='left', padx=(0, 8))
        self.delivery = tk.StringVar(value=SHORT_STYLE)
        self._short_selected = False
        self.delivery_box = ttk.Combobox(delivery, textvariable=self.delivery,
            values=('Tự nhiên', 'Kịch tính', SHORT_STYLE), state='readonly', width=23)
        self.delivery_box.pack(side='left')
        self.short_button = ttk.Button(delivery, text='Khung 55 giây…', command=self.configure_short)
        self.short_button.pack(side='left', padx=8)
        ttk.Label(delivery, text='Tự căn tốc độ và nghỉ theo 6 nhịp').pack(side='left')
        self.voice.trace_add('write', self.update_delivery)
        self.delivery.trace_add('write', self.update_delivery)
        pauses = ttk.Frame(settings)
        pauses.grid(row=3, column=0, columnspan=5, sticky='w', padx=5, pady=(8, 0))
        ttk.Label(pauses, text='Nghỉ giữa câu (giây)').pack(side='left')
        self.sentence_pause = tk.StringVar(value='0.35')
        self.sentence_pause_box = ttk.Spinbox(pauses, from_=0, to=5, increment=.05, width=6,
                                             textvariable=self.sentence_pause)
        self.sentence_pause_box.pack(side='left', padx=(8, 18))
        ttk.Label(pauses, text='Nghỉ giữa đoạn (giây)').pack(side='left')
        self.paragraph_pause = tk.StringVar(value='0.8')
        self.paragraph_pause_box = ttk.Spinbox(pauses, from_=0, to=10, increment=.1, width=6,
                                              textvariable=self.paragraph_pause)
        self.paragraph_pause_box.pack(side='left', padx=8)
        self.update_delivery()
        characters = ttk.Frame(settings)
        characters.grid(row=4, column=0, columnspan=5, sticky='w', padx=5, pady=(8, 0))
        self.character_button = ttk.Button(characters, text='Nhân vật / giọng hồn ma…',
                                           command=self.configure_characters)
        self.character_button.pack(side='left')
        self.voice_fx_button = ttk.Button(characters, text='Hiệu ứng hồn ma…',
                                          command=self.configure_ghost_effects)
        self.voice_fx_button.pack(side='left', padx=8)
        self.insert_voice_button = ttk.Button(characters, text='＋ Chèn giọng tại con trỏ',
                                              command=self.insert_voice)
        self.insert_voice_button.pack(side='left')
        toolbar = ttk.Frame(root)
        toolbar.pack(fill='x', pady=10)
        ttk.Button(toolbar, text='Nhập TXT / SRT / MD', command=self.load).pack(side='left')
        ttk.Button(toolbar, text='Chọn thư mục xuất', command=self.choose_folder).pack(side='left', padx=6)
        ttk.Button(toolbar, text='Mở thư mục xuất', command=lambda: self.open_folder()).pack(side='left')
        ttk.Button(toolbar, text='Dựng Reel từ ảnh', command=self.open_reel_editor).pack(side='left', padx=6)
        self.folder_label = ttk.Label(root, text=str(self.folder))
        self.folder_label.pack(anchor='w')
        ttk.Label(root, text='Kịch bản — dòng trống phân chia các đoạn trong bảng').pack(anchor='w', pady=(10, 4))
        script_actions = ttk.Frame(root)
        script_actions.pack(fill='x', pady=(4, 6))
        self.effect_button = ttk.Button(script_actions, text='＋ Hiệu ứng / khoảng nghỉ tại con trỏ',
                                       command=self.insert_effect)
        self.effect_button.pack(side='left')
        ttk.Button(script_actions, text='Lưu kịch bản…', command=self.save_script).pack(side='left', padx=8)
        self.replay_preview = ttk.Button(script_actions, text='▶ Nghe lại đoạn thử',
                                        command=self.play_preview, state='disabled')
        self.replay_preview.pack(side='left')
        editor = ttk.Frame(root)
        editor.pack(fill='both', expand=True)
        self.text = tk.Text(editor, wrap='word', font=('Segoe UI', 11), undo=True, height=10, exportselection=False)
        scroll = ttk.Scrollbar(editor, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.text.tag_configure('voice_marker', foreground='#64748b')
        self.text.tag_configure('dialogue', foreground='#1d4ed8', background='#eff6ff')
        self.text.tag_configure('ghost_dialogue', foreground='#7e22ce', background='#faf5ff')
        self.text.bind('<<Modified>>', self.highlight_voices)
        actions = ttk.Frame(root)
        actions.pack(fill='x', pady=10)
        self.preview = ttk.Button(actions, text='▶ Nghe đoạn đang chọn', command=lambda: self.start(True))
        self.preview.pack(side='left')
        ttk.Label(root, text='Short: nghe trọn nhịp tại con trỏ. Chế độ khác: nghe phần bôi đen hoặc đoạn văn.').pack(anchor='w')
        self.generate = ttk.Button(actions, text='Xuất toàn bộ MP3 + SRT', command=lambda: self.start(False))
        self.generate.pack(side='left', padx=8)
        ttk.Button(actions, text='Nghe file vừa tạo', command=self.play).pack(side='left')
        ttk.Button(actions, text='Mở thư mục MP3', command=self.open_folder).pack(side='left', padx=6)
        self.cancel_button = ttk.Button(actions, text='Hủy', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left', padx=8)
        self.bar = ttk.Progressbar(root, mode='indeterminate')
        self.bar.pack(fill='x')
        self.status = tk.StringVar(value=character_warning or
                                   'Sẵn sàng. Short tâm linh: 6 nhịp / 55 giây. Mở Khung 55 giây để xem cấu hình.')
        ttk.Label(root, textvariable=self.status, wraplength=900).pack(anchor='w', pady=7)
        self.table = ttk.Treeview(root, columns=('id','content'), show='headings', height=5)
        self.table.heading('id', text='Đoạn')
        self.table.heading('content', text='Nội dung kịch bản')
        self.table.column('id', width=55, stretch=False)
        self.table.column('content', width=800)
        self.table.pack(fill='x')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.poll)

    def update_delivery(self, *_):
        offline = VOICES[self.voice.get()].startswith('offline:')
        self.delivery_box.config(state='disabled' if offline else 'readonly')
        if offline and self.delivery.get() != 'Tự nhiên':
            self.delivery.set('Tự nhiên')
        short = self.delivery.get() == SHORT_STYLE
        if short and not self._short_selected:
            self._manual_pacing = (self.rate.get(), self.pitch.get(), self.sentence_pause.get(), self.paragraph_pause.get())
            for variable, value in zip((self.rate, self.pitch, self.sentence_pause, self.paragraph_pause),
                                       ('0', '0', '0.10', '0.18')):
                variable.set(value)
        elif self._short_selected and not short:
            for variable, value in zip((self.rate, self.pitch, self.sentence_pause, self.paragraph_pause),
                                       self._manual_pacing):
                variable.set(value)
        self._short_selected = short
        for control in (self.rate_box, self.pitch_box, self.sentence_pause_box, self.paragraph_pause_box):
            control.config(state='disabled' if short else 'normal')
        self.short_button.config(state='disabled' if offline else 'normal')

    def configure_short(self):
        if self.busy:
            return
        from short_pacing_dialog import ShortPacingDialog
        ShortPacingDialog(self)

    def insert_effect(self):
        if self.busy:
            return
        from sound_dialog import SoundDialog
        try:
            SoundDialog(self, self.text.index('insert'), BASE / 'outputs' / 'effects')
        except (OSError, ValueError) as exc:
            messagebox.showerror('Không mở được thư viện hiệu ứng', str(exc))

    def configure_characters(self):
        if self.busy:
            return
        from character_dialog import CharacterDialog
        CharacterDialog(self, VOICES)

    def configure_ghost_effects(self):
        if self.busy:
            return
        from effect_dialog import GhostEffectDialog
        GhostEffectDialog(self, VOICES)

    def insert_voice(self):
        if self.busy:
            return
        from voice_insert_dialog import VoiceInsertDialog
        VoiceInsertDialog(self)

    def highlight_voices(self, *_):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        text = self.text.get('1.0', 'end-1c')
        for tag in ('voice_marker', 'dialogue', 'ghost_dialogue'):
            self.text.tag_remove(tag, '1.0', 'end')
        for marker in re.finditer(INLINE_VOICE + '|' + CHARACTER_HEADER, text, re.MULTILINE):
            self.text.tag_add('voice_marker', f'1.0+{marker.start()}c', f'1.0+{marker.end()}c')
        try:
            for turn in inline_turns(text):
                tag = 'ghost_dialogue' if 'hồn ma' in turn['voice'].casefold() else 'dialogue'
                self.text.tag_add(tag, f'1.0+{turn["content_start"]}c', f'1.0+{turn["content_end"]}c')
        except ValueError:
            pass  # A partially typed quote is normal while editing.

    def save_script(self):
        name = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Kịch bản', '*.txt')])
        if name:
            try:
                Path(name).write_text(self.text.get('1.0', 'end-1c'), encoding='utf-8')
                self.status.set('Đã lưu kịch bản cùng dấu hiệu ứng và khoảng nghỉ.')
            except OSError as exc:
                messagebox.showerror('Không lưu được kịch bản', str(exc))

    def open_reel_editor(self):
        from reel_editor import ReelEditor
        existing = getattr(self, 'reel_editor', None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        self.reel_editor = ReelEditor(self, audio=self.last_audio)

    def close_when_editor_idle(self):
        editor = getattr(self, 'reel_editor', None)
        if editor is not None and editor.winfo_exists() and editor.busy:
            self.after(300, self.close_when_editor_idle)
        else:
            self.close()

    def close(self):
        editor = getattr(self, 'reel_editor', None)
        if editor is not None and editor.winfo_exists() and editor.busy:
            if messagebox.askyesno('Đang dựng video', 'Hủy dựng video và đóng ứng dụng?'):
                editor.cancel_event.set()
                self.after(300, self.close_when_editor_idle)
            return
        if not self.busy or messagebox.askyesno('Đang tạo âm thanh', 'Đóng ứng dụng sẽ dừng tác vụ đang chạy. Đóng ngay?'):
            self.cancel()
            self.stop_playback()
            self.clear_preview()
            self.destroy()

    def clear_preview(self):
        self.preview_audio = None
        self.replay_preview.config(state='disabled')
        if self.preview_temp:
            self.preview_temp.cleanup()
            self.preview_temp = None

    def finish(self):
        self.busy = False
        self.bar.stop()
        self.preview.config(state='normal')
        self.voice_sample.config(state='normal')
        self.generate.config(state='normal')
        self.effect_button.config(state='normal')
        self.character_button.config(state='normal')
        self.voice_fx_button.config(state='normal')
        self.insert_voice_button.config(state='normal')
        self.short_button.config(state='disabled' if VOICES[self.voice.get()].startswith('offline:') else 'normal')
        self.cancel_button.config(state='disabled')

    def cancel(self, timed_out=False):
        if not self.busy:
            return
        if self.process and self.process.is_alive():
            subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.process.join(timeout=1)
        if not self.process or not self.process.is_alive():
            cleanup_story(self.target)
            if self.is_expressive:
                cleanup_expressive(self.target)
                self.target.with_suffix('.chunk.wav').unlink(missing_ok=True)
            else:
                self.target.with_suffix('.mp3.part').unlink(missing_ok=True)
        self.finish()
        if self.is_preview and not self.is_voice_sample and (not self.process or not self.process.is_alive()):
            self.clear_preview()
        self.status.set('Hết thời gian chờ dịch vụ. Kiểm tra Internet/DNS rồi thử lại.' if timed_out else 'Đã hủy. Bạn có thể thử lại.')

    def load(self):
        if self.busy:
            return
        name = filedialog.askopenfilename(filetypes=[('Kịch bản', '*.txt *.srt *.md')])
        if not name:
            return
        try:
            value = Path(name).read_text(encoding='utf-8-sig')
            if name.lower().endswith('.srt'):
                blocks = re.split(r'\n\s*\n', value.strip())
                value = '\n\n'.join(' '.join(line.strip() for line in b.splitlines()
                    if line.strip() and not line.strip().isdigit() and '-->' not in line) for b in blocks)
            value = transcript_text(value)
            if has_headers(value):
                value = canonical_script(value)
                self.delivery.set(SHORT_STYLE)
            self.text.delete('1.0', 'end')
            self.text.insert('1.0', value)
            self.status.set('Đã nhập lời đọc. Mốc thời gian TXT/SRT được bỏ qua; phụ đề sẽ khớp với audio mới.')
        except Exception as exc:
            messagebox.showerror('Không nhập được', str(exc))

    def choose_folder(self):
        if self.busy:
            return
        folder = filedialog.askdirectory()
        if folder:
            self.folder = Path(folder)
            self.folder_label.config(text=folder)

    def open_folder(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(self.folder))

    def play(self):
        if self.last_audio and self.last_audio.exists():
            self.play_audio(self.last_audio, 'Đang phát: ' + self.last_audio.name)
        else:
            messagebox.showinfo('Chưa có file', 'Hãy xuất MP3 trước hoặc bấm Nghe lại đoạn thử để nghe bản thử gần nhất.')

    def play_preview(self):
        if not self.busy and self.preview_audio and self.preview_audio.exists():
            self.play_audio(self.preview_audio, 'Đang nghe lại bản thử gần nhất, gồm hiệu ứng và khoảng nghỉ.')

    def start(self, preview, voice_sample=False):
        if self.busy:
            return
        self.stop_playback()
        voice = VOICES[self.voice.get()]
        expressive = self.delivery.get() == 'Kịch tính'
        short = self.delivery.get() == SHORT_STYLE
        preview_start = preview_end = None
        if voice_sample:
            if short:
                sample = ('Đây là mẫu giọng đọc. Bạn có nghe rõ không?' if voice.startswith(('vi-', 'vieneu:')) else
                          "Don't open the door after midnight. Even if you hear me.")
                text = '[[BEAT:HOOK]]\n' + sample
            elif voice.startswith('en-'):
                text = 'A ribbon of moonlight slipped under the library door. The clock struck twelve. Silence. Who was there?'
            elif voice.startswith(('vi-', 'vieneu:')):
                text = 'Một vệt trăng lọt qua khe cửa thư viện. Đồng hồ điểm mười hai tiếng. Im lặng. Ai đang ở đó?'
            else:
                text = 'Hello! This is a sample of my voice. Imagine the stories we can tell together.'
        else:
            text = self.text.get('1.0', 'end-1c')
            if has_headers(text):
                short = True
                expressive = False
                self.delivery.set(SHORT_STYLE)
            if preview:
                selection = self.text.tag_ranges('sel')
                begin = selection[0] if selection else 'insert'
                offset = self.text.count('1.0', begin, 'chars')
                start = offset[0] if offset else 0
                end_offset = self.text.count('1.0', selection[1], 'chars') if selection else None
                if short:
                    preview_start, preview_end = start, end_offset[0] if end_offset else None
                else:
                    text = script_excerpt(text, start, end_offset[0] if end_offset else None)
            if not short:
                text = transcript_text(text.strip())
        if not text.strip():
            messagebox.showwarning('Thiếu kịch bản', 'Hãy nhập kịch bản.')
            return
        try:
            rate, pitch = int(self.rate.get()), int(self.pitch.get())
            if not -50 <= rate <= 100 or not -50 <= pitch <= 50:
                raise ValueError()
        except ValueError:
            messagebox.showerror('Thông số chưa đúng', 'Tốc độ: -50 đến 100. Cao độ: -50 đến 50. Nhập số nguyên.')
            return
        try:
            sentence_pause, paragraph_pause = float(self.sentence_pause.get()), float(self.paragraph_pause.get())
            if not (0 <= sentence_pause <= 5 and 0 <= paragraph_pause <= 10):
                raise ValueError('Nghỉ giữa câu từ 0–5 giây, giữa đoạn từ 0–10 giây.')
            plan = None
            if short:
                plan = short_plan(text, read_effects(BASE / 'outputs' / 'effects'), self.characters,
                                  preview_start, preview_end)
                if not plan:
                    raise ValueError('Hãy nhập lời đọc cho Short.')
                if not shutil.which('ffmpeg'):
                    raise ValueError('Cần FFmpeg để căn nhịp Short tâm linh.')
            elif (sentence_pause or paragraph_pause or '[[' in text
                    or re.search(r'(?m)^[ \t]*\[[^\[\]\r\n]+\][ \t]*:', text)
                    or (preview and not voice_sample)):
                plan = script_plan(text, sentence_pause, paragraph_pause,
                                   read_effects(BASE / 'outputs' / 'effects'), self.characters)
                if not plan:
                    raise ValueError('Hãy nhập lời kể hoặc chèn hiệu ứng.')
                if not shutil.which('ffmpeg'):
                    raise ValueError('Cần cài FFmpeg để thêm khoảng nghỉ và hiệu ứng.')
        except (OSError, ValueError) as exc:
            messagebox.showerror('Khoảng nghỉ / hiệu ứng', str(exc))
            return
        if not voice_sample:
            for row in self.table.get_children():
                self.table.delete(row)
            for i, part in enumerate(paragraphs(text), 1):
                self.table.insert('', 'end', values=(i, part))
        default_speech = plan is None or any(
            item['kind'] == 'speech' and 'voice' not in item for item in plan)
        if default_speech and voice.startswith('vieneu:') and pitch:
            messagebox.showwarning('Cao độ VieNeu', 'VieNeu dùng cao độ tự nhiên. Hãy đặt cao độ 0.')
            return
        if preview and not voice_sample:
            self.clear_preview()
            try:
                scratch = BASE / 'work'
                scratch.mkdir(exist_ok=True)
                self.preview_temp = tempfile.TemporaryDirectory(prefix='audition_', dir=scratch)
                folder = Path(self.preview_temp.name)
            except OSError as exc:
                messagebox.showerror('Không tạo được bản nghe thử', str(exc))
                return
        else:
            folder = BASE / 'work' / 'voice_samples' if voice_sample else self.folder
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror('Thư mục xuất', str(exc))
            return
        target = folder / (('preview_' if preview else 'narration_') + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.mp3')
        if preview and not voice_sample:
            target = folder / 'audition.wav'
        if voice_sample:
            settings = [text, voice, rate, pitch]
            if short:
                settings.append(SHORT_VERSION)
            if plan is not None:
                settings.append(['story-v1', sentence_pause, paragraph_pause])
            if expressive:
                settings.append('vieneu-pauses-v2' if voice.startswith('vieneu:') else 'expressive-v1')
            key = hashlib.sha256(json.dumps(settings).encode('utf-8')).hexdigest()
            target = folder / (key + '.mp3')
            cached = next((p for p in (target, target.with_suffix('.wav'))
                           if p.exists() and p.stat().st_size), None)
            if cached:
                self.play_voice_sample(cached)
                return
        self.busy = True
        self.events = mp.Queue()
        self.target = target
        self.is_preview = preview
        self.is_voice_sample = voice_sample
        self.is_expressive = expressive
        self.is_short = short
        self.sample_voice_label = self.voice.get()
        self.started = time.monotonic()
        self.timeout_seconds = (600 if preview else 1800) if voice.startswith('vieneu:') else (30 if preview else 180)
        if expressive and not voice.startswith('vieneu:'):
            self.timeout_seconds = 90 if preview else 900
        if plan is not None:
            self.timeout_seconds = max(self.timeout_seconds, 180 if preview else max(900, len(plan) * 30))
            if any(item.get('voice', voice).startswith('vieneu:') for item in plan
                   if item['kind'] == 'speech'):
                self.timeout_seconds = max(self.timeout_seconds, 600 if preview else len(plan) * 90)
        self.progress_text = 'Đang nạp model / tạo giọng đọc'
        self.preview.config(state='disabled')
        self.voice_sample.config(state='disabled')
        self.generate.config(state='disabled')
        self.effect_button.config(state='disabled')
        self.character_button.config(state='disabled')
        self.voice_fx_button.config(state='disabled')
        self.insert_voice_button.config(state='disabled')
        self.short_button.config(state='disabled')
        self.cancel_button.config(state='normal')
        self.bar.start(12)
        self.status.set('Đang chuẩn bị đoạn nghe thử…' if preview else 'Đang kết nối và tạo giọng đọc…')
        self.process = mp.Process(target=worker,
            args=(self.events, text, voice, rate, pitch, str(target), expressive, plan,
                  preview and not voice_sample), daemon=True)
        try:
            self.process.start()
        except Exception as exc:
            self.finish()
            if preview and not voice_sample:
                self.clear_preview()
            messagebox.showerror('Không khởi chạy được', str(exc))

    def play_voice_sample(self, path, label=None):
        self.play_audio(path, 'Đang nghe mẫu giọng: ' + (label or self.voice.get()))

    def play_audio(self, path, description):
        try:
            self.player.play(path)
            self.stop_audio.config(state='normal')
            self.status.set(description)
        except OSError as exc:
            self.stop_audio.config(state='disabled')
            messagebox.showerror('Không phát được âm thanh', str(exc))

    def stop_playback(self):
        try:
            self.player.stop()
        except OSError as exc:
            messagebox.showerror('Không dừng được âm thanh', str(exc))
        self.stop_audio.config(state='disabled')


    def poll(self):
        if self.player.opened:
            try:
                if not self.player.playing():
                    self.stop_playback()
                    if not self.busy:
                        self.status.set('Đã nghe xong. Bạn có thể chọn giọng khác để nghe thử.')
            except OSError:
                self.stop_playback()
        try:
            while self.busy:
                kind, value = self.events.get_nowait()
                if kind == 'progress':
                    self.progress_text = value[:130]
                    self.status.set('Đang đọc: ' + value[:130])
                    continue
                self.finish()
                if kind == 'done':
                    if self.is_voice_sample:
                        self.play_voice_sample(Path(value), self.sample_voice_label)
                        continue
                    if self.is_preview:
                        self.preview_audio = Path(value)
                        self.replay_preview.config(state='normal')
                        self.play_audio(self.preview_audio, 'Đang nghe thử đoạn đã chọn cùng hiệu ứng và khoảng nghỉ.')
                        continue
                    self.last_audio = Path(value)
                    self.status.set('Đã xuất MP3 + SRT + TXT: ' + str(self.last_audio))
                else:
                    if self.is_preview and not self.is_voice_sample:
                        self.clear_preview()
                    self.status.set('Tạo chưa thành công. Xem thông báo lỗi để biết nguyên nhân.')
                    messagebox.showerror('Lỗi tạo giọng đọc', value)
        except queue.Empty:
            pass
        if self.busy:
            elapsed = int(time.monotonic() - self.started)
            if elapsed >= self.timeout_seconds:
                self.cancel(timed_out=True)
            else:
                self.status.set(f'{self.progress_text} · {elapsed}s / tối đa {self.timeout_seconds}s. Có thể bấm Hủy.')
        self.after(100, self.poll)

if __name__ == '__main__':
    use_app_python()
    mp.freeze_support()
    App().mainloop()

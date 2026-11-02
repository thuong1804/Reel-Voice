"""Reel Voice: Windows script narration using the online Edge TTS service."""
import asyncio
import os
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
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

BASE = Path(__file__).resolve().parent
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

def vieneu_synthesize(text, voice, rate, target, events):
    interpreter = BASE / '.venv-vieneu' / 'Scripts' / 'python.exe'
    if not interpreter.exists():
        raise RuntimeError('Chưa cài VieNeu. Hãy chạy Cai_VieNeu.cmd trong thư mục ứng dụng.')
    job = target.with_suffix('.job.json')
    job.write_text(json.dumps({'text': text, 'voice': voice.split(':', 1)[1],
                              'rate': rate, 'target': str(target)}, ensure_ascii=False), encoding='utf-8')
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

def paragraphs(text):
    return [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]

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

def worker(events, text, voice, rate, pitch, target):
    try:
        if voice.startswith('vieneu:'):
            output = vieneu_synthesize(text, voice, rate, Path(target), events)
        elif voice.startswith('offline:'):
            output = offline_synthesize(text, voice, rate, pitch, Path(target), events)
        else:
            asyncio.run(synthesize(text, voice, rate, pitch, Path(target),
                lambda sentence: events.put(('progress', sentence))))
            output = target
        events.put(('done', str(output)))
    except Exception as exc:
        events.put(('error', f'{type(exc).__name__}: {exc}'))

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Reel Voice 1.7 · Giọng đọc + Dựng Reel từ ảnh')
        self.geometry('1000x750')
        self.minsize(800, 600)
        self.events = mp.Queue()
        self.process = None
        self.busy = False
        self.last_audio = None
        self.folder = BASE / 'outputs' / 'audio'
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
        ttk.Spinbox(settings, from_=-50, to=100, textvariable=self.rate, width=6).grid(row=0, column=2)
        ttk.Label(settings, text='Cao độ Hz').grid(row=0, column=3, padx=5)
        self.pitch = tk.StringVar(value='0')
        ttk.Spinbox(settings, from_=-50, to=50, textvariable=self.pitch, width=6).grid(row=0, column=4)
        ttk.Label(settings, text='VieNeu: cao độ 0').grid(row=1, column=0, sticky='w')
        toolbar = ttk.Frame(root)
        toolbar.pack(fill='x', pady=10)
        ttk.Button(toolbar, text='Nhập TXT / SRT', command=self.load).pack(side='left')
        ttk.Button(toolbar, text='Chọn thư mục xuất', command=self.choose_folder).pack(side='left', padx=6)
        ttk.Button(toolbar, text='Mở thư mục xuất', command=lambda: self.open_folder()).pack(side='left')
        ttk.Button(toolbar, text='Dựng Reel từ ảnh', command=self.open_reel_editor).pack(side='left', padx=6)
        self.folder_label = ttk.Label(root, text=str(self.folder))
        self.folder_label.pack(anchor='w')
        ttk.Label(root, text='Kịch bản — dòng trống phân chia các đoạn trong bảng').pack(anchor='w', pady=(10, 4))
        editor = ttk.Frame(root)
        editor.pack(fill='both', expand=True)
        self.text = tk.Text(editor, wrap='word', font=('Segoe UI', 11), undo=True, height=10)
        scroll = ttk.Scrollbar(editor, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.text.insert('1.0', 'Bạn bị thương giữa thời tiền sử. Không bệnh viện. Không xe cứu thương. Ai sẽ cứu bạn?')
        actions = ttk.Frame(root)
        actions.pack(fill='x', pady=10)
        self.preview = ttk.Button(actions, text='▶ Tạo mẫu nghe thử', command=lambda: self.start(True))
        self.preview.pack(side='left')
        self.generate = ttk.Button(actions, text='Xuất toàn bộ MP3 + SRT', command=lambda: self.start(False))
        self.generate.pack(side='left', padx=8)
        ttk.Button(actions, text='Nghe file vừa tạo', command=self.play).pack(side='left')
        ttk.Button(actions, text='Mở thư mục MP3', command=self.open_folder).pack(side='left', padx=6)
        self.cancel_button = ttk.Button(actions, text='Hủy', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left', padx=8)
        self.bar = ttk.Progressbar(root, mode='indeterminate')
        self.bar.pack(fill='x')
        self.status = tk.StringVar(value='Sẵn sàng. Nghe thử một đoạn trước khi xuất toàn bộ.')
        ttk.Label(root, textvariable=self.status, wraplength=900).pack(anchor='w', pady=7)
        self.table = ttk.Treeview(root, columns=('id','content'), show='headings', height=5)
        self.table.heading('id', text='Đoạn')
        self.table.heading('content', text='Nội dung kịch bản')
        self.table.column('id', width=55, stretch=False)
        self.table.column('content', width=800)
        self.table.pack(fill='x')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.poll)

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
            self.destroy()

    def finish(self):
        self.busy = False
        self.bar.stop()
        self.preview.config(state='normal')
        self.generate.config(state='normal')
        self.cancel_button.config(state='disabled')

    def cancel(self, timed_out=False):
        if not self.busy:
            return
        if self.process and self.process.is_alive():
            subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.process.join(timeout=1)
        self.target.with_suffix('.mp3.part').unlink(missing_ok=True)
        self.finish()
        self.status.set('Hết thời gian chờ dịch vụ. Kiểm tra Internet/DNS rồi thử lại.' if timed_out else 'Đã hủy. Bạn có thể thử lại.')

    def load(self):
        if self.busy:
            return
        name = filedialog.askopenfilename(filetypes=[('Kịch bản', '*.txt *.srt')])
        if not name:
            return
        try:
            value = Path(name).read_text(encoding='utf-8-sig')
            if name.lower().endswith('.srt'):
                blocks = re.split(r'\n\s*\n', value.strip())
                value = '\n\n'.join(' '.join(line.strip() for line in b.splitlines()
                    if line.strip() and not line.strip().isdigit() and '-->' not in line) for b in blocks)
            self.text.delete('1.0', 'end')
            self.text.insert('1.0', value)
            self.status.set('Đã nhập. SRT đầu vào chỉ lấy lời; thời gian sẽ được tạo lại theo giọng đọc.')
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
            os.startfile(str(self.last_audio))
        else:
            messagebox.showinfo('Chưa có file', 'Bấm tạo mẫu nghe thử hoặc xuất toàn bộ trước.')

    def start(self, preview):
        if self.busy:
            return
        text = self.text.get('1.0', 'end').strip()
        if not text:
            messagebox.showwarning('Thiếu kịch bản', 'Hãy nhập kịch bản.')
            return
        try:
            rate, pitch = int(self.rate.get()), int(self.pitch.get())
            if not -50 <= rate <= 100 or not -50 <= pitch <= 50:
                raise ValueError()
        except ValueError:
            messagebox.showerror('Thông số chưa đúng', 'Tốc độ: -50 đến 100. Cao độ: -50 đến 50. Nhập số nguyên.')
            return
        for row in self.table.get_children():
            self.table.delete(row)
        for i, part in enumerate(paragraphs(text), 1):
            self.table.insert('', 'end', values=(i, part))
        if preview:
            sentences = re.split(r'(?<=[.!?])\s+', text)
            text = sentences[0]
            if len(text) > 500:
                text = text[:500].rsplit(' ', 1)[0]
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror('Thư mục xuất', str(exc))
            return
        target = self.folder / (('preview_' if preview else 'narration_') + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.mp3')
        voice = VOICES[self.voice.get()]
        if voice.startswith('vieneu:') and pitch:
            messagebox.showwarning('Cao độ VieNeu', 'VieNeu dùng cao độ tự nhiên. Hãy đặt cao độ 0.')
            return
        self.busy = True
        self.events = mp.Queue()
        self.target = target
        self.is_preview = preview
        self.started = time.monotonic()
        self.timeout_seconds = (600 if preview else 1800) if voice.startswith('vieneu:') else (30 if preview else 180)
        self.progress_text = 'Đang nạp model / tạo giọng đọc'
        self.preview.config(state='disabled')
        self.generate.config(state='disabled')
        self.cancel_button.config(state='normal')
        self.bar.start(12)
        self.status.set('Đang kết nối và tạo giọng đọc…')
        self.process = mp.Process(target=worker,
            args=(self.events, text, voice, rate, pitch, str(target)), daemon=True)
        try:
            self.process.start()
        except Exception as exc:
            self.finish()
            messagebox.showerror('Không khởi chạy được', str(exc))

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'progress':
                    self.progress_text = value[:130]
                    self.status.set('Đang đọc: ' + value[:130])
                    continue
                self.finish()
                if kind == 'done':
                    self.last_audio = Path(value)
                    self.status.set('Đã xuất MP3 + SRT + TXT: ' + str(self.last_audio))
                    if self.is_preview:
                        self.play()
                else:
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
    mp.freeze_support()
    App().mainloop()

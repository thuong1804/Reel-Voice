"""Modal editor for an uploaded sound or a pause at the script caret."""
import json
from pathlib import Path
import re
import shutil
import uuid
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from expressive_voice import run_ffmpeg
from story_audio import read_effects


class SoundDialog(tk.Toplevel):
    def __init__(self, app, index, folder):
        library = read_effects(folder)
        super().__init__(app)
        self.app = app
        self.folder = folder
        self.index = index
        self.title('Chèn âm thanh / khoảng nghỉ')
        self.transient(app)
        self.resizable(False, False)
        self.protocol('WM_DELETE_WINDOW', self.close)
        body = ttk.Frame(self, padding=18)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Chèn tại vị trí con trỏ trong kịch bản', font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        ttk.Label(body, text='Giọng đọc dừng, phát hết hiệu ứng rồi tiếp tục kể.').pack(anchor='w', pady=(4, 12))
        self.library = library
        self.ids = list(self.library)
        self.sounds = ttk.Combobox(body, state='readonly', width=52,
            values=[self.library[key]['name'] for key in self.ids])
        self.sounds.pack(fill='x')
        if self.ids:
            self.sounds.current(0)
        upload_row = ttk.Frame(body)
        upload_row.pack(fill='x', pady=8)
        ttk.Button(upload_row, text='Tải file âm thanh…', command=self.upload).pack(side='left')
        ttk.Button(upload_row, text='▶ Nghe hiệu ứng', command=self.listen).pack(side='left', padx=8)
        ttk.Button(upload_row, text='■ Dừng', command=app.stop_playback).pack(side='left')
        controls = ttk.Frame(body)
        controls.pack(fill='x', pady=8)
        ttk.Label(controls, text='Âm lượng %').pack(side='left')
        self.volume = tk.StringVar(value='80')
        ttk.Spinbox(controls, from_=0, to=150, increment=10, width=6,
                    textvariable=self.volume).pack(side='left', padx=8)
        ttk.Button(controls, text='Chèn hiệu ứng', command=self.insert_sound).pack(side='right')
        ttk.Separator(body).pack(fill='x', pady=12)
        pauses = ttk.Frame(body)
        pauses.pack(fill='x')
        ttk.Label(pauses, text='Khoảng nghỉ (giây)').pack(side='left')
        self.pause = tk.StringVar(value='1.0')
        ttk.Spinbox(pauses, from_=0, to=30, increment=.1, width=6,
                    textvariable=self.pause).pack(side='left', padx=8)
        ttk.Button(pauses, text='Chèn khoảng nghỉ', command=self.insert_pause).pack(side='right')
        ttk.Label(body, text='Xóa dấu [[SFX:…]] hoặc [[PAUSE:…]] trong kịch bản để bỏ hiệu ứng.').pack(anchor='w', pady=(14, 0))
        ttk.Button(body, text='Đóng', command=self.close).pack(anchor='e', pady=(12, 0))
        self.grab_set()
        self.focus_set()

    def selected(self):
        index = self.sounds.current()
        if index < 0:
            raise ValueError('Hãy tải lên hoặc chọn một file âm thanh.')
        return self.ids[index]

    def upload(self):
        name = filedialog.askopenfilename(parent=self, filetypes=[
            ('Âm thanh', '*.mp3 *.wav *.m4a *.ogg *.flac *.aac *.opus'), ('Tất cả', '*.*')])
        if not name:
            return
        temporary = None
        try:
            ffmpeg = shutil.which('ffmpeg')
            if not ffmpeg:
                raise ValueError('Cần cài FFmpeg để tải và kiểm tra hiệu ứng.')
            self.app.stop_playback()
            self.folder.mkdir(parents=True, exist_ok=True)
            label = re.sub(r'[^\w-]', '-', Path(name).stem).strip('-')[:28] or 'am-thanh'
            effect_id = label + '-' + uuid.uuid4().hex[:8]
            temporary = self.folder / (effect_id + '.part')
            # Decode a private copy to PCM WAV so all accepted formats play inside the app.
            run_ffmpeg(ffmpeg, ['-y', '-i', name, '-vn', '-ac', '1', '-ar', '48000',
                                '-codec:a', 'pcm_s16le', '-f', 'wav', str(temporary)])
            if temporary.stat().st_size <= 44:
                raise ValueError('File âm thanh rỗng.')
            target = self.folder / (effect_id + '.wav')
            temporary.replace(target)
            library = dict(self.library)
            library[effect_id] = {'name': Path(name).stem, 'path': str(target.resolve())}
            manifest = self.folder / 'effects.json.part'
            try:
                manifest.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding='utf-8')
                manifest.replace(self.folder / 'effects.json')
            except Exception:
                target.unlink(missing_ok=True)
                manifest.unlink(missing_ok=True)
                raise
            self.library = library
            self.ids = list(library)
            self.sounds.config(values=[library[key]['name'] for key in self.ids])
            self.sounds.current(len(self.ids) - 1)
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror('Không tải được hiệu ứng', str(exc), parent=self)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def listen(self):
        try:
            effect = self.library[self.selected()]
            volume = int(self.volume.get())
            if not 0 <= volume <= 150:
                raise ValueError('Âm lượng từ 0 đến 150%.')
            self.app.stop_playback()
            ffmpeg = shutil.which('ffmpeg')
            if not ffmpeg:
                raise ValueError('Cần cài FFmpeg để nghe hiệu ứng.')
            preview = self.folder / f'preview_{self.selected()}_{volume}.wav'
            if not preview.exists():
                run_ffmpeg(ffmpeg, ['-y', '-i', effect['path'],
                    '-af', f'volume={volume/100}', str(preview)])
            self.app.play_audio(preview, 'Đang nghe hiệu ứng ' + effect['name'])
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror('Không nghe được hiệu ứng', str(exc), parent=self)

    def insert_sound(self):
        try:
            key = self.selected()
            volume = int(self.volume.get())
            if not 0 <= volume <= 150:
                raise ValueError('Âm lượng từ 0 đến 150%.')
            self.insert(f'[[SFX:{key}:{volume}]]')
        except ValueError as exc:
            messagebox.showerror('Chưa chèn được', str(exc), parent=self)

    def insert_pause(self):
        try:
            seconds = float(self.pause.get())
            if not 0 <= seconds <= 30:
                raise ValueError('Khoảng nghỉ từ 0 đến 30 giây.')
            self.insert(f'[[PAUSE:{seconds:g}]]')
        except ValueError as exc:
            messagebox.showerror('Chưa chèn được', str(exc), parent=self)

    def insert(self, marker):
        self.app.text.edit_separator()
        self.app.text.insert(self.index, marker)
        self.app.text.edit_separator()
        self.app.text.mark_set('insert', f'{self.index}+{len(marker)}c')
        self.close()
        self.app.text.focus_set()

    def close(self):
        self.app.stop_playback()
        self.grab_release()
        self.destroy()

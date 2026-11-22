"""Speech effect controls with reusable presets and a short local audition."""
from pathlib import Path
from copy import deepcopy
import shutil
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from expressive_voice import run_ffmpeg
from voice_effects import (BUILTINS, DEFAULTS, LIMITS, read_presets, read_settings, save_preset,
                           settings_for_profile, speech_filter, validate_settings, write_json)


class EffectDialog(tk.Toplevel):
    def __init__(self, owner, app, settings, on_apply):
        super().__init__(owner)
        self.app = app
        self.owner = owner
        self.on_apply = on_apply
        self.source = app.effect_sample_path
        self.preview_temp = None
        self.title('Hiệu ứng hồn ma · Echo / Reverb / Cao độ')
        self.transient(owner)
        self.resizable(False, False)
        self.protocol('WM_DELETE_WINDOW', self.close)
        body = ttk.Frame(self, padding=16)
        self.body = body
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Tự chỉnh hiệu ứng giọng hồn ma', font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(body, text='Chỉ áp dụng cho hồn ma nam / nữ. Giọng kể và đối thoại tự nhiên giữ âm thanh gốc.').pack(
            anchor='w', pady=(4, 10))
        preset_row = ttk.Frame(body)
        preset_row.pack(fill='x')
        ttk.Label(preset_row, text='Preset / tên để lưu').pack(side='left')
        self.preset_name = tk.StringVar(value='Preset của tôi')
        self.preset_box = ttk.Combobox(preset_row, textvariable=self.preset_name, width=25)
        self.preset_box.pack(side='left', padx=8)
        self.preset_box.bind('<<ComboboxSelected>>', self.load_preset)
        ttk.Button(preset_row, text='Lưu preset', command=self.save_preset).pack(side='left')
        ttk.Button(preset_row, text='Nhập JSON…', command=self.import_settings).pack(side='left', padx=6)
        ttk.Button(preset_row, text='Xuất JSON…', command=self.export_settings).pack(side='left')
        self.variables = {key: tk.StringVar(value=str(value)) for key, value in validate_settings(settings).items()}
        groups = ttk.Frame(body)
        groups.pack(fill='x', pady=12)
        tone = ttk.LabelFrame(groups, text='Chất giọng', padding=8)
        tone.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        echo = ttk.LabelFrame(groups, text='Echo · Tiếng lặp', padding=8)
        echo.grid(row=0, column=1, sticky='nsew')
        reverb = ttk.LabelFrame(groups, text='Reverb · Vang phòng mô phỏng', padding=8)
        reverb.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        for parent, fields in [
            (tone, [('pitch_st', 'Cao độ (bán âm)', .5), ('bass_db', 'Âm trầm (dB)', 1),
                    ('treble_db', 'Âm bổng (dB)', 1), ('ghost_mix', 'Lớp hồn ma (%)', 5)]),
            (echo, [('echo_mix', 'Mức tiếng lặp (%)', 5), ('echo_delay_ms', 'Độ trễ (ms)', 10),
                    ('echo_repeats', 'Số lần lặp', 1), ('echo_feedback', 'Giữ tiếng mỗi lần (%)', 5)]),
            (reverb, [('reverb_mix', 'Mức vang (%)', 5), ('room_size', 'Kích thước phòng (%)', 5)]),
        ]:
            for index, (key, label, step) in enumerate(fields):
                low, high = LIMITS[key]
                ttk.Label(parent, text=label).grid(row=index, column=0, sticky='w', pady=5)
                ttk.Scale(parent, from_=low, to=high, variable=self.variables[key], length=130,
                          command=lambda value, key=key, step=step: self.variables[key].set(
                              str(round(round(float(value) / step) * step, 1)))).grid(row=index, column=1, padx=8)
                ttk.Spinbox(parent, from_=low, to=high, increment=step, textvariable=self.variables[key],
                            width=6).grid(row=index, column=2)
        preview = ttk.LabelFrame(body, text='Nghe thử hiệu ứng', padding=8)
        preview.pack(fill='x')
        self.source_label = ttk.Label(preview, text='Mẫu gốc: giọng nữ Trúc Ly · có thể chọn file giọng khác')
        self.source_label.pack(anchor='w', pady=(0, 6))
        controls = ttk.Frame(preview)
        controls.pack(fill='x')
        ttk.Button(controls, text='Chọn file giọng…', command=self.choose_source).pack(side='left')
        ttk.Button(controls, text='▶ Nghe thử', command=self.listen).pack(side='left', padx=8)
        ttk.Button(controls, text='■ Dừng', command=app.stop_playback).pack(side='left')
        self.notice = tk.StringVar(value='Chỉnh thông số rồi nghe thử. Chỉ áp dụng khi bấm Áp dụng.')
        ttk.Label(body, textvariable=self.notice, wraplength=700).pack(anchor='w', pady=8)
        actions = ttk.Frame(body)
        actions.pack(fill='x')
        ttk.Button(actions, text='Bỏ toàn bộ hiệu ứng', command=lambda: self.set_values(DEFAULTS)).pack(side='left')
        ttk.Button(actions, text='Đóng', command=self.close).pack(side='right')
        ttk.Button(actions, text='Áp dụng', command=self.apply).pack(side='right', padx=8)
        self.refresh_presets()
        self.grab_set()
        self.focus_set()

    def values(self):
        try:
            return validate_settings({key: float(variable.get()) for key, variable in self.variables.items()})
        except (ValueError, tk.TclError) as exc:
            raise ValueError('Thông số chưa đúng. ' + str(exc)) from exc

    def set_values(self, settings):
        for key, value in validate_settings(settings).items():
            self.variables[key].set(str(value))

    def refresh_presets(self):
        try:
            self.presets = read_presets(self.app.fx_presets_path)
        except (OSError, ValueError) as exc:
            self.presets = dict(BUILTINS)
            self.notice.set('Không đọc được preset đã lưu: ' + str(exc))
        self.preset_box.config(values=list(self.presets))

    def load_preset(self, *_):
        if self.preset_name.get() in self.presets:
            self.set_values(self.presets[self.preset_name.get()])

    def save_preset(self):
        try:
            save_preset(self.app.fx_presets_path, self.preset_name.get(), self.values())
            self.refresh_presets()
            self.notice.set('Đã lưu preset. Có thể chọn lại trong danh sách ở trên.')
        except (OSError, ValueError) as exc:
            messagebox.showerror('Không lưu được preset', str(exc), parent=self)

    def import_settings(self):
        name = filedialog.askopenfilename(parent=self, filetypes=[('Preset hiệu ứng JSON', '*.json')])
        if name:
            try:
                self.set_values(read_settings(Path(name)))
                self.preset_name.set(Path(name).stem)
                self.notice.set('Đã nhập thông số. Nghe thử rồi bấm Áp dụng.')
            except (OSError, ValueError) as exc:
                messagebox.showerror('Không nhập được preset', str(exc), parent=self)

    def export_settings(self):
        name = filedialog.asksaveasfilename(parent=self, defaultextension='.json',
                                            filetypes=[('Preset hiệu ứng JSON', '*.json')])
        if name:
            try:
                write_json(Path(name), self.values())
                self.notice.set('Đã xuất preset JSON để giữ lại hoặc chia sẻ.')
            except (OSError, ValueError) as exc:
                messagebox.showerror('Không xuất được preset', str(exc), parent=self)

    def choose_source(self):
        name = filedialog.askopenfilename(parent=self, filetypes=[
            ('Giọng gốc', '*.mp3 *.wav *.m4a *.ogg *.flac'), ('Tất cả', '*.*')])
        if name:
            self.source = Path(name)
            self.source_label.config(text='Mẫu gốc: ' + self.source.name)

    def listen(self):
        try:
            ffmpeg = shutil.which('ffmpeg')
            if not ffmpeg:
                raise ValueError('Cần FFmpeg để nghe thử hiệu ứng.')
            if not self.source.is_file():
                raise ValueError('Hãy bấm Chọn file giọng để chọn âm thanh gốc.')
            settings = self.values()
            self.app.stop_playback()
            if self.preview_temp is None:
                self.preview_temp = tempfile.TemporaryDirectory(prefix='reelvoice_effect_')
            target = Path(self.preview_temp.name) / 'preview.wav'
            args = ['-y', '-i', str(self.source), '-t', '12', '-vn']
            effect = speech_filter('custom', 100, settings)
            if effect:
                args += ['-af', effect]
            run_ffmpeg(ffmpeg, [*args, '-ar', '48000', '-ac', '1', '-codec:a', 'pcm_s16le', str(target)])
            self.app.play_audio(target, 'Đang nghe thử cấu hình hiệu ứng.')
            self.notice.set('Đang nghe thử tối đa 12 giây từ file mẫu đã chọn.')
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror('Không nghe thử được', str(exc), parent=self)

    def apply(self):
        try:
            self.on_apply(self.values())
        except (OSError, ValueError) as exc:
            messagebox.showerror('Không áp dụng được hiệu ứng', str(exc), parent=self)
            return
        self.close()

    def close(self):
        self.app.stop_playback()
        if self.preview_temp:
            self.preview_temp.cleanup()
        self.destroy()
        if self.owner != self.app and self.owner.winfo_exists():
            self.owner.grab_set()


class GhostEffectDialog(EffectDialog):
    """Save effects for a character's ghost variant without altering its base voice."""
    def __init__(self, app, voices):
        self.voices = voices
        name = next((name for name in app.characters if name == 'Nữ'), next(iter(app.characters)))
        self.target_name = tk.StringVar(master=app, value=name)
        super().__init__(app, app, settings_for_profile(app.characters[name]), self.save_ghost)
        target_row = ttk.Frame(self.body)
        target_row.pack(fill='x', before=self.body.winfo_children()[0], pady=(0, 10))
        ttk.Label(target_row, text='Hồn ma của nhân vật').pack(side='left')
        target = ttk.Combobox(target_row, textvariable=self.target_name,
                              values=list(app.characters), state='readonly', width=24)
        target.pack(side='left', padx=8)
        target.bind('<<ComboboxSelected>>', self.load_target)
        self.load_target()

    def load_target(self, *_):
        name = self.target_name.get()
        self.set_values(settings_for_profile(self.app.characters[name]))
        self.preset_name.set(name + ' hồn ma')
        self.title('Hiệu ứng hồn ma · ' + name)
        self.notice.set('Đang chỉnh hồn ma của ' + name + '. Chọn vai này — hồn ma khi chèn lời thoại.')

    def save_ghost(self, settings):
        from dialogue import save_characters
        name = self.target_name.get()
        characters = deepcopy(self.app.characters)
        characters[name]['ghost_settings'] = validate_settings(settings)
        save_characters(self.app.characters_path, characters, self.voices)
        self.app.characters = characters
        self.app.status.set('Đã lưu hiệu ứng hồn ma của ' + name + '. Giọng kể và giọng tự nhiên giữ nguyên.')

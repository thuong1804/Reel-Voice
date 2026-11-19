"""Configure the voices and speech effects used by character headers."""
import tkinter as tk
from tkinter import ttk, messagebox

from dialogue import EFFECTS, example_script, save_characters, validate_characters
from voice_effects import settings_for_profile


class CharacterDialog(tk.Toplevel):
    def __init__(self, app, voices):
        super().__init__(app)
        self.app = app
        self.voices = voices
        self.title('Nhân vật / giọng hồn ma')
        self.transient(app)
        self.resizable(False, False)
        body = ttk.Frame(self, padding=18)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Mỗi nhân vật một giọng và hiệu ứng riêng',
                  font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(body, text='Viết [Nam]: lời thoại và [Nữ]: lời thoại. Tên vai không được đọc thành tiếng.').pack(
            anchor='w', pady=(4, 12))
        self.rows = []
        for name, profile in app.characters.items():
            card = ttk.LabelFrame(body, text=name, padding=10)
            card.pack(fill='x', pady=(0, 10))
            row = {
                'name': tk.StringVar(value=name),
                'voice': tk.StringVar(value=next(label for label, value in voices.items()
                                                if value == profile['voice'])),
                'rate': tk.StringVar(value=str(profile['rate'])),
                'delivery': tk.StringVar(value='Kịch tính' if profile['expressive'] else 'Tự nhiên'),
                'effect': tk.StringVar(value='Tự nhiên' if profile['voice_effect'] == 'none' else 'Hồn ma'),
                'strength': tk.StringVar(value=str(profile['effect_strength'])),
                'ghost_settings': settings_for_profile(profile),
                'ghost_configured': 'ghost_settings' in profile or profile['voice_effect'] == 'custom',
            }
            ttk.Label(card, text='Tên vai').grid(row=0, column=0, sticky='w')
            ttk.Entry(card, textvariable=row['name'], width=12).grid(row=0, column=1, sticky='w', padx=8)
            ttk.Label(card, text='Giọng đọc').grid(row=0, column=2, sticky='w')
            ttk.Combobox(card, textvariable=row['voice'], values=list(voices),
                         state='readonly', width=53).grid(row=0, column=3, columnspan=3, sticky='ew', padx=8)
            ttk.Label(card, text='Tốc độ %').grid(row=1, column=0, sticky='w', pady=8)
            ttk.Spinbox(card, from_=-50, to=100, textvariable=row['rate'], width=6).grid(
                row=1, column=1, sticky='w', padx=8)
            ttk.Label(card, text='Cách đọc').grid(row=1, column=2, sticky='w')
            delivery = ttk.Combobox(card, textvariable=row['delivery'],
                                    values=('Tự nhiên', 'Kịch tính'), state='readonly', width=13)
            delivery.grid(row=1, column=3, sticky='w', padx=8)
            row['delivery_box'] = delivery
            ttk.Label(card, text='Kiểu giọng').grid(row=2, column=0, sticky='w')
            effect_box = ttk.Combobox(card, textvariable=row['effect'], values=('Tự nhiên', 'Hồn ma'),
                                     state='readonly', width=12)
            effect_box.grid(row=2, column=1, sticky='w', padx=8)
            ttk.Label(card, text='Mức hiệu ứng %').grid(row=2, column=2, sticky='w')
            strength_box = ttk.Spinbox(card, from_=0, to=100, increment=5,
                                      textvariable=row['strength'], width=6)
            strength_box.grid(row=2, column=3, sticky='w', padx=8)
            row['strength_box'] = strength_box
            ttk.Button(card, text='Hiệu ứng hồn ma…', command=lambda row=row: self.configure_effects(row)).grid(
                row=2, column=4, padx=8)
            row['voice'].trace_add('write', lambda *_, row=row: self.update_controls(row))
            row['effect'].trace_add('write', lambda *_, row=row: self.update_controls(row))
            self.update_controls(row)
            self.rows.append(row)
        ttk.Label(body, text='Cấu hình hiệu ứng chỉ dùng khi chọn Hồn ma. Giọng Tự nhiên giữ âm thanh gốc.').pack(anchor='w')
        ttk.Label(body, text='Có thể đổi riêng một lượt: [Nữ — hồn ma]: … hoặc [Nữ — tự nhiên]: …').pack(
            anchor='w', pady=4)
        ttk.Label(body, text='Lời trước tên vai đầu tiên dùng giọng ở cửa sổ chính. Mỗi lượt giữ vai đến tên vai kế tiếp.').pack(
            anchor='w', pady=(0, 12))
        actions = ttk.Frame(body)
        actions.pack(fill='x')
        ttk.Button(actions, text='Chèn mẫu đối thoại & lưu',
                   command=lambda: self.save(insert_example=True)).pack(side='left')
        ttk.Button(actions, text='Đóng', command=self.destroy).pack(side='right')
        ttk.Button(actions, text='Lưu thiết lập', command=self.save).pack(side='right', padx=8)
        self.grab_set()
        self.focus_set()

    def update_controls(self, row):
        offline = self.voices[row['voice'].get()].startswith('offline:')
        row['delivery_box'].config(state='disabled' if offline else 'readonly')
        if offline:
            row['delivery'].set('Tự nhiên')
        row['strength_box'].config(state='normal' if row['effect'].get() == 'Hồn ma'
                                   and not row['ghost_configured'] else 'disabled')

    def configure_effects(self, row):
        from effect_dialog import EffectDialog
        try:
            profile = dict(voice_effect='ghost', effect_strength=int(row['strength'].get()))
            if row['ghost_configured']:
                profile['ghost_settings'] = row['ghost_settings']
        except ValueError:
            messagebox.showerror('Thông số chưa đúng', 'Mức hiệu ứng phải là số nguyên từ 0 đến 100%.', parent=self)
            return
        def apply(settings):
            row['ghost_settings'] = settings
            row['ghost_configured'] = True
            self.update_controls(row)
            self.app.status.set('Đã chỉnh hiệu ứng hồn ma. Bấm Lưu thiết lập để giữ lại; giọng tự nhiên giữ nguyên.')
        EffectDialog(self, self.app, settings_for_profile(profile), apply)

    def save(self, insert_example=False):
        try:
            characters = {}
            for row in self.rows:
                name = row['name'].get().strip()
                if name in characters:
                    raise ValueError('Tên các nhân vật phải khác nhau.')
                characters[name] = dict(
                    voice=self.voices[row['voice'].get()], rate=int(row['rate'].get()), pitch=0,
                    expressive=row['delivery'].get() == 'Kịch tính',
                    voice_effect=EFFECTS[row['effect'].get()], effect_strength=int(row['strength'].get()))
                if row['ghost_configured']:
                    characters[name]['ghost_settings'] = dict(row['ghost_settings'])
            validate_characters(characters, self.voices)
            if insert_example and len(characters) < 2:
                raise ValueError('Mẫu đối thoại cần ít nhất hai nhân vật.')
            save_characters(self.app.characters_path, characters, self.voices)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Không lưu được nhân vật', str(exc), parent=self)
            return
        self.app.characters = characters
        if insert_example:
            editor = self.app.text
            editor.edit_separator()
            selection = editor.tag_ranges('sel')
            if selection:
                editor.delete(selection[0], selection[1])
            editor.insert('insert', '\n\n' + example_script(characters) + '\n\n')
            editor.edit_separator()
            editor.see('insert')
        self.app.status.set('Đã lưu nhân vật. Dùng [tên vai]: lời thoại; bôi đen đoạn rồi bấm Nghe đoạn đang chọn.')
        self.destroy()

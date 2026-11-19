"""Assign a character to a quoted turn at the script caret."""
import tkinter as tk
from tkinter import ttk, messagebox
import re

from dialogue import inline_turns


class VoiceInsertDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.index = app.text.index('insert')
        self.selection = app.text.tag_ranges('sel')
        self.existing_text = None
        initial_voice = None
        text = app.text.get('1.0', 'end-1c')
        begin = self.selection[0] if self.selection else self.index
        count = app.text.count('1.0', begin, 'chars')
        offset = count[0] if count else 0
        count = app.text.count('1.0', self.selection[1], 'chars') if self.selection else None
        ending = count[0] if count else offset
        try:
            turns = inline_turns(text)
        except ValueError:
            turns = []
        for turn in turns:
            if turn['start'] <= offset < turn['end'] and ending <= turn['end']:
                self.selection = (f'1.0+{turn["start"]}c', f'1.0+{turn["end"]}c')
                self.existing_text = text[turn['content_start']:turn['content_end']]
                initial_voice = turn['voice']
                break
        if not self.selection:
            for quote in re.finditer(r'"(?:\\.|[^"\\])*"|“[^”]*”', text):
                if quote.start() <= offset < quote.end():
                    self.selection = (f'1.0+{quote.start()}c', f'1.0+{quote.end()}c')
                    self.existing_text = quote.group(0)[1:-1]
                    break
        self.title('Chèn giọng cho câu đối thoại')
        self.transient(app)
        self.resizable(False, False)
        body = ttk.Frame(self, padding=18)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Gán giọng tại con trỏ hoặc cho phần đang bôi đen',
                  font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        choices = ['Người kể']
        for name in app.characters:
            choices.extend((name + ' — tự nhiên', name + ' — hồn ma', name))
        self.voice = tk.StringVar(value=initial_voice or (choices[1] if len(choices) > 1 else choices[0]))
        ttk.Combobox(body, textvariable=self.voice, values=choices, state='readonly', width=40).pack(
            fill='x', pady=12)
        ttk.Label(body, text='Lời thoại nằm trong "...". Hết câu thoại sẽ trở lại giọng trước đó.').pack(anchor='w')
        ttk.Label(body, text='Tự nhiên: giọng gốc. Tên vai không kèm chỉ dẫn: dùng cấu hình đã lưu.').pack(anchor='w')
        ttk.Label(body, text='Có thể chọn giọng nam / nữ và cấu hình Echo, Reverb trong thiết lập Nhân vật.').pack(
            anchor='w', pady=(4, 12))
        actions = ttk.Frame(body)
        actions.pack(fill='x')
        ttk.Button(actions, text='Đóng', command=self.destroy).pack(side='right')
        ttk.Button(actions, text='Chèn giọng', command=self.insert).pack(side='right', padx=8)
        self.grab_set()
        self.focus_set()

    def insert(self):
        editor = self.app.text
        value = (self.existing_text if self.existing_text is not None else
                 editor.get(*self.selection).strip() if self.selection else 'Lời thoại ở đây…')
        if '[[VOICE:' in value:
            messagebox.showerror('Chọn một câu thoại', 'Đặt con trỏ trong một câu thoại để đổi vai; không chọn nhiều dấu gán giọng cùng lúc.', parent=self)
            return
        if len(value) >= 2 and (value[0], value[-1]) in (('"', '"'), ('“', '”')):
            value = value[1:-1]
        # Escape embedded straight quotes so they cannot end the assigned turn.
        value = value.replace('\\"', '"').replace('"', '\\"')
        marker = f'[[VOICE:{self.voice.get()}]]'
        text = marker + '"' + value + '"'
        editor.edit_separator()
        start = self.selection[0] if self.selection else self.index
        if self.selection:
            editor.delete(*self.selection)
        editor.insert(start, text)
        editor.edit_separator()
        editor.tag_remove('sel', '1.0', 'end')
        editor.tag_add('sel', f'{start}+{len(marker)+1}c', f'{start}+{len(marker)+1+len(value)}c')
        editor.mark_set('insert', f'{start}+{len(text)}c')
        editor.see('insert')
        self.app.status.set('Đã gán giọng cho phần trong ngoặc kép. Lời bên ngoài giữ giọng kể.')
        self.destroy()
        editor.focus_set()

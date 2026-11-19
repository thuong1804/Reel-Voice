"""Show the six timing windows and apply the story narration preset."""
import tkinter as tk
from tkinter import ttk

from short_pacing import SPECS, STYLE, template


class ShortPacingDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title('Nhịp đọc Short tâm linh · 55 giây')
        self.transient(app)
        self.resizable(False, False)
        body = ttk.Frame(self, padding=18)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='6 nhịp · Nén, lạnh, không gào', font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        table = ttk.Treeview(body, columns=('beat', 'time', 'sentence', 'paragraph'),
                            show='headings', height=6)
        for column, title, width in [('beat', 'Nhịp', 100), ('time', 'Mốc giây', 90),
                                     ('sentence', 'Nghỉ câu', 90), ('paragraph', 'Nghỉ đoạn', 90)]:
            table.heading(column, text=title)
            table.column(column, width=width, stretch=False)
        for spec in SPECS:
            table.insert('', 'end', values=(spec['label'], f'{spec["start"]}–{spec["end"]}',
                                            f'{spec["sentence"]:.2f}s', f'{spec["paragraph"]:.2f}s'))
        table.pack(fill='x', pady=12)
        for text in [
            'HOOK → NEO: chỉ 0.08s chuyển nhịp, không ngắt dài ở giây 4–6.',
            'LEO 2: câu ngắn dồn. Cao trào: dừng 0.18–0.24s trước các câu lộ bí mật.',
            'Tốc độ được căn từ âm thanh thực để khớp mỗi nhịp; giữ cao độ giọng.',
            'Nhấn nhẹ bằng thời lượng và âm lượng câu, không tự thêm echo hay hiệu ứng hồn ma.',
            'Chia 6 đoạn trống hoặc dùng tiêu đề [[BEAT:HOOK]] … [[BEAT:END]].',
            'Bản nháp chưa chia nhịp dùng khoảng 2.8 từ/giây, chưa ép vào khung 55 giây.',
            'Nghe thử sẽ nghe trọn nhịp tại con trỏ. SFX và cấu hình hồn ma vẫn giữ riêng.',
        ]:
            ttk.Label(body, text=text, wraplength=640).pack(anchor='w', pady=2)
        actions = ttk.Frame(body)
        actions.pack(fill='x', pady=(14, 0))
        ttk.Button(actions, text='Chèn khung trống 6 nhịp', command=self.insert_outline).pack(side='left')
        ttk.Button(actions, text='Đóng', command=self.destroy).pack(side='right')
        ttk.Button(actions, text='Áp dụng preset', command=self.apply).pack(side='right', padx=8)
        self.grab_set()

    def apply(self):
        self.app.delivery.set(STYLE)
        self.app.status.set('Đã áp dụng Short tâm linh: 6 nhịp / 55 giây; tốc độ và khoảng nghỉ tự căn theo từng nhịp.')
        self.destroy()

    def insert_outline(self):
        editor = self.app.text
        editor.edit_separator()
        selection = editor.tag_ranges('sel')
        if selection:
            editor.delete(*selection)
        editor.insert('insert', template())
        editor.edit_separator()
        editor.see('insert')
        self.apply()

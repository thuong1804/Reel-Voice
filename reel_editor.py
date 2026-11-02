"""Offline still-image reel editor and FFmpeg renderer. No cloud services."""
from pathlib import Path
import json
import math
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

BASE = Path(__file__).resolve().parent
FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
MOTIONS = ['Zoom gần', 'Zoom xa', 'Lia sang phải', 'Lia sang trái', 'Lia xuống', 'Lia lên', 'Đứng yên']

def natural_key(value):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r'(\d+)', str(value))]

def probe_duration(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'json', str(path)], capture_output=True, text=True, creationflags=FLAGS, timeout=20)
    if result.returncode:
        raise ValueError('Không đọc được âm thanh: ' + str(path))
    value = float(json.loads(result.stdout)['format']['duration'])
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Thời lượng âm thanh không hợp lệ.')
    return value

def seconds(value):
    fields = value.replace(',', '.').split(':')
    return sum(float(x) * 60 ** i for i, x in enumerate(reversed(fields)))

def read_srt(path):
    if not path:
        return []
    text = Path(path).read_text(encoding='utf-8-sig')
    cues = []
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = block.strip().splitlines()
        for i, line in enumerate(lines):
            match = re.match(r'(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)', line)
            if match:
                start, end = seconds(match[1]), seconds(match[2])
                caption = re.sub(r'<[^>]*>', '', ' '.join(lines[i+1:])).strip()
                if end > start and caption:
                    cues.append((start, end, caption))
                break
    if not cues:
        raise ValueError('File SRT không có mốc thời gian hợp lệ.')
    return sorted(cues)

def read_prompts(path):
    text = Path(path).read_text(encoding='utf-8-sig')
    matches = list(re.finditer(r'(?m)^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*', text))
    result = []
    for i, match in enumerate(matches):
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        result.append((seconds(match[1]), text[match.end():end].strip()))
    if not result:
        raise ValueError('Prompt cần định dạng [00:00] nội dung, mỗi cảnh một mốc.')
    times = [x[0] for x in result]
    if times[0] != 0 or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Mốc prompt phải bắt đầu 00:00 và tăng dần.')
    return result

def motion_from_prompt(text, fallback='Zoom gần'):
    text = text.lower()
    for keys, effect in [(['pullback', 'pull back', 'pull the camera back', 'ease backward', 'zoom out', 'zoom xa'], 'Zoom xa'),
        (['pan right', 'lia phải', 'sang phải'], 'Lia sang phải'),
        (['pan left', 'lia trái', 'sang trái'], 'Lia sang trái'),
        (['pan down', 'lia xuống'], 'Lia xuống'), (['pan up', 'lia lên'], 'Lia lên'),
        (['static camera', 'fixed camera', 'đứng yên'], 'Đứng yên')]:
        if any(key in text for key in keys):
            return effect
    return fallback

def make_plan(images, duration, cues=(), prompts=()):
    if not images:
        return []
    if prompts and len(prompts) != len(images):
        raise ValueError(f'Có {len(images)} ảnh nhưng {len(prompts)} prompt. Cần một prompt cho mỗi ảnh; gộp hoặc sửa file prompt trước.')
    if prompts and prompts[-1][0] >= duration:
        raise ValueError('Mốc prompt cuối nằm ngoài thời lượng MP3.')
    starts = [p[0] for p in prompts] if prompts else [duration*i/len(images) for i in range(len(images))]
    ends = starts[1:] + [duration]
    rows = []
    for i, (image, start, end) in enumerate(zip(images, starts, ends)):
        caption = ' '.join(c[2] for c in cues if c[0] < end and c[1] > start)
        prompt = prompts[i][1] if prompts else ''
        rows.append({'image': str(image), 'duration': end-start,
                     'motion': motion_from_prompt(prompt, MOTIONS[i % 6]),
                     'note': prompt or caption})
    return rows

def ass_time(value):
    cs = max(0, round(value * 100))
    return f'{cs//360000}:{cs//6000%60:02}:{cs//100%60:02}.{cs%100:02}'

def wrap_caption(text, width=30):
    text = text.replace('\\', '').replace('{', '').replace('}', '')
    lines, current = [], ''
    for word in text.split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = (current + ' ' + word).strip()
    if current:
        lines.append(current)
    return lines

def write_ass(path, cues):
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,58,&H00FFFFFF,&H00FFFFFF,&H00141414,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,70,70,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = []
    for start, end, caption in cues:
        lines = wrap_caption(caption)
        pages = [lines[i:i+2] for i in range(0, len(lines), 2)]
        counts = [sum(len(line.split()) for line in page) for page in pages]
        total = sum(counts)
        offset = start
        for page, count in zip(pages, counts):
            finish = offset + (end-start) * count / total
            text = r'\N'.join(page)
            events.append(f'Dialogue: 0,{ass_time(offset)},{ass_time(finish)},Default,,0,0,0,,{text}')
            offset = finish
    path.write_text(header + '\n'.join(events), encoding='utf-8-sig')

class Cancelled(Exception):
    pass

def run_command(command, cancel, log, cwd=None):
    if cancel.is_set():
        raise Cancelled()
    with subprocess.Popen(command, cwd=cwd, stdout=log, stderr=log, creationflags=FLAGS) as process:
        while True:
            try:
                code = process.wait(timeout=.2)
                break
            except subprocess.TimeoutExpired:
                if cancel.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise Cancelled()
        if code:
            raise RuntimeError('FFmpeg không xuất được video. Xem file .log.txt đi kèm để biết lỗi.')

def zoom_filter(motion, frames, width, height, fps):
    progress = f'min(on/{max(frames-1,1)},1)'
    zoom, x, y = '1', '(iw-iw/zoom)/2', '(ih-ih/zoom)/2'
    if motion == 'Zoom gần':
        zoom = f'1+0.10*{progress}'
    elif motion == 'Zoom xa':
        zoom = f'1.10-0.10*{progress}'
    elif motion in ('Lia sang phải', 'Lia sang trái'):
        zoom = '1.12'
        x = f'(iw-iw/zoom)*{progress}' if motion == 'Lia sang phải' else f'(iw-iw/zoom)*(1-{progress})'
    elif motion in ('Lia xuống', 'Lia lên'):
        zoom = '1.12'
        y = f'(ih-ih/zoom)*{progress}' if motion == 'Lia xuống' else f'(ih-ih/zoom)*(1-{progress})'
    return f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps},setsar=1,format=yuv420p"

def render_project(project, output, cancel, notify, preview=False):
    from PIL import Image, ImageOps
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('Cần FFmpeg và FFprobe trong PATH để dựng video.')
    duration = probe_duration(project['audio'])
    rows = project['scenes']
    if not rows:
        raise ValueError('Chưa có ảnh.')
    if any(not math.isfinite(float(row['duration'])) or float(row['duration']) <= 0 for row in rows):
        raise ValueError('Thời lượng mỗi ảnh phải là số dương.')
    if abs(sum(float(r['duration']) for r in rows) - duration) > .15:
        raise ValueError('Tổng thời lượng ảnh chưa khớp MP3. Bấm Căn đều theo MP3 hoặc sửa thời lượng.')
    cues = read_srt(project.get('srt', ''))
    fps = 30
    width, height = (360, 640) if preview else (1080, 1920)
    length = min(duration, 12) if preview else duration
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch = BASE / 'work'
    scratch.mkdir(exist_ok=True)
    output.with_suffix('.project.json').write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding='utf-8')
    with output.with_suffix('.log.txt').open('w', encoding='utf-8') as log:
        with tempfile.TemporaryDirectory(prefix='reel_render_', dir=scratch) as temporary:
            folder = Path(temporary)
            elapsed, previous_frame, parts = 0.0, 0, []
            for i, row in enumerate(rows):
                if elapsed >= length:
                    break
                end = min(elapsed + float(row['duration']), length)
                final_frame = round(end * fps)
                frames = final_frame - previous_frame
                previous_frame = final_frame
                elapsed = end
                if frames < 1:
                    continue
                notify(f'Dựng ảnh {i+1}/{len(rows)}: {Path(row["image"]).name}', min(85, 85*end/length))
                image = ImageOps.exif_transpose(Image.open(row['image'])).convert('RGB')
                size = (width*2, height*2)
                if project.get('fit') == 'Lấp đầy khung':
                    canvas = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
                else:
                    canvas = Image.new('RGB', size, '#202020')
                    fitted = ImageOps.contain(image, size, method=Image.Resampling.LANCZOS)
                    canvas.paste(fitted, ((size[0]-fitted.width)//2, (size[1]-fitted.height)//2))
                still = folder / f'image_{i:03}.jpg'
                canvas.save(still, quality=96)
                part = folder / f'part_{i:03}.mp4'
                filters = zoom_filter(row['motion'], frames, width, height, fps)
                run_command(['ffmpeg', '-y', '-v', 'error', '-loop', '1', '-framerate', str(fps), '-i', str(still),
                    '-vf', filters, '-frames:v', str(frames), '-an', '-c:v', 'libx264', '-preset', 'veryfast',
                    '-crf', '20', '-threads', '2', str(part)], cancel, log)
                parts.append(part)
            (folder / 'parts.txt').write_text('\n'.join(f"file '{p.name}'" for p in parts), encoding='utf-8')
            if cues:
                write_ass(folder / 'captions.ass', cues)
            notify('Ghép giọng đọc, phụ đề và xuất MP4…', 90)
            command = ['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', 'parts.txt', '-i', str(Path(project['audio']).resolve())]
            music = project.get('music')
            if music:
                command += ['-stream_loop', '-1', '-i', str(Path(music).resolve()), '-filter_complex',
                    f'[2:a]volume={float(project.get("music_volume",12))/100}[bg];[1:a][bg]amix=inputs=2:duration=first:normalize=0[a]',
                    '-map', '0:v:0', '-map', '[a]']
            else:
                command += ['-map', '0:v:0', '-map', '1:a:0']
            if cues:
                command += ['-vf', 'subtitles=filename=captions.ass', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-threads', '2']
            else:
                command += ['-c:v', 'copy']
            command += ['-c:a', 'aac', '-b:a', '192k', '-t', f'{length:.6f}', '-movflags', '+faststart', 'final.mp4']
            run_command(command, cancel, log, cwd=folder)
            if cancel.is_set():
                raise Cancelled()
            shutil.copyfile(folder / 'final.mp4', output)
    notify('Đã xuất: ' + str(output), 100)
    return output

class ReelEditor(tk.Toplevel):
    def __init__(self, master=None, audio=None):
        super().__init__(master)
        self.title('Dựng Reel từ ảnh · 1.7')
        self.geometry('1150x820')
        self.minsize(950, 720)
        self.rows = []
        self.audio = tk.StringVar(value=str(audio or ''))
        self.srt = tk.StringVar()
        if audio and Path(audio).with_suffix('.srt').exists():
            self.srt.set(str(Path(audio).with_suffix('.srt')))
        self.music = tk.StringVar()
        self.duration = 0
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.last_video = None
        self.output_folder = BASE / 'outputs' / 'video'
        body = ttk.Frame(self, padding=14)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='DỰNG REEL TỪ ẢNH', font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        ttk.Label(body, text='Ảnh có sẵn + MP3 + SRT → zoom/lia + phụ đề → MP4 dọc. Mỗi ảnh tương ứng một cảnh.').pack(anchor='w', pady=(0,8))
        inputs = ttk.Frame(body)
        inputs.pack(fill='x')
        inputs.columnconfigure(1, weight=1)
        for i, (label, var, command) in enumerate([('MP3 / WAV', self.audio, self.choose_audio), ('Phụ đề SRT', self.srt, self.choose_srt), ('Nhạc nền (tùy chọn)', self.music, self.choose_music)]):
            ttk.Button(inputs, text=label, command=command, width=23).grid(row=i,column=0,pady=3,sticky='w')
            ttk.Entry(inputs,textvariable=var).grid(row=i,column=1,padx=7,sticky='ew')
        tools = ttk.Frame(body)
        tools.pack(fill='x', pady=8)
        for label, command in [('Thêm ảnh', self.add_images), ('Nhập prompt có mốc', self.import_prompts), ('Căn đều theo MP3', self.distribute), ('Lưu dự án', self.save_project), ('Mở dự án', self.load_project)]:
            ttk.Button(tools,text=label,command=command).pack(side='left',padx=(0,5))
        self.info = tk.StringVar(value='Chọn MP3 và ảnh. Căn đều là điểm khởi đầu; kiểm tra nội dung từng cảnh trước khi xuất.')
        ttk.Label(body,textvariable=self.info,wraplength=1080).pack(anchor='w',pady=5)
        table_frame = ttk.Frame(body)
        table_frame.pack(fill='both',expand=True)
        self.table = ttk.Treeview(table_frame, columns=('n','image','start','end','motion','note'),show='headings',height=10,selectmode='browse')
        for key,label,width in [('n','#',35),('image','Ảnh',170),('start','Bắt đầu',70),('end','Kết thúc',70),('motion','Chuyển động',115),('note','Lời đọc / prompt ngữ cảnh',500)]:
            self.table.heading(key,text=label)
            self.table.column(key,width=width,stretch=key in ('image','note'))
        self.table.pack(side='left',fill='both',expand=True)
        scrollbar = ttk.Scrollbar(table_frame,orient='vertical',command=self.table.yview)
        scrollbar.pack(side='right',fill='y')
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind('<<TreeviewSelect>>',self.select_row)
        edit = ttk.Frame(body)
        edit.pack(fill='x',pady=7)
        ttk.Label(edit,text='Độ dài cảnh (giây)').pack(side='left')
        self.scene_duration = tk.StringVar()
        ttk.Entry(edit,textvariable=self.scene_duration,width=9).pack(side='left',padx=5)
        self.motion = tk.StringVar(value=MOTIONS[0])
        ttk.Combobox(edit,textvariable=self.motion,values=MOTIONS,state='readonly',width=16).pack(side='left',padx=5)
        for label,command in [('Lưu chỉnh sửa ảnh',self.apply_row),('↑',lambda:self.move(-1)),('↓',lambda:self.move(1)),('Xóa ảnh',self.remove_row),('Xem ảnh',self.show_image)]:
            ttk.Button(edit,text=label,command=command).pack(side='left',padx=3)
        self.note = tk.Text(body,height=3,wrap='word',font=('Segoe UI',10))
        self.note.pack(fill='x')
        ttk.Label(body,text='Prompt chỉ gợi ý zoom/lia bằng từ khóa; không sửa nội dung ảnh và không tự hiểu ảnh nào khớp lời nào.').pack(anchor='w',pady=3)
        settings = ttk.Frame(body)
        settings.pack(fill='x',pady=6)
        self.fit = tk.StringVar(value='Giữ trọn ảnh')
        ttk.Combobox(settings,textvariable=self.fit,values=['Giữ trọn ảnh','Lấp đầy khung'],state='readonly',width=19).pack(side='left')
        ttk.Label(settings,text='Nhạc nền %').pack(side='left',padx=(12,4))
        self.music_volume = tk.StringVar(value='12')
        ttk.Spinbox(settings,from_=0,to=30,textvariable=self.music_volume,width=5).pack(side='left')
        ttk.Label(body,text='TẠO VIDEO: bấm Dựng thử hoặc Bắt đầu xuất MP4 bên dưới. Lưu chỉnh sửa ảnh chỉ cập nhật bảng.').pack(anchor='w',pady=(3,0))
        actions = ttk.Frame(body)
        actions.pack(fill='x',pady=5)
        self.preview_button = ttk.Button(actions,text='▶ Dựng thử 12 giây',command=lambda:self.export(True))
        self.preview_button.pack(side='left')
        self.export_button = ttk.Button(actions,text='▶ Bắt đầu xuất MP4',command=lambda:self.export(False))
        self.export_button.pack(side='left',padx=7)
        ttk.Button(actions,text='Hủy dựng',command=self.cancel_event.set).pack(side='left')
        ttk.Button(actions,text='Mở video vừa xuất',command=self.play).pack(side='left',padx=7)
        ttk.Button(actions,text='Mở thư mục video',command=self.open_output).pack(side='left')
        self.bar = ttk.Progressbar(body,maximum=100)
        self.bar.pack(fill='x',pady=5)
        self.status = tk.StringVar(value='Chưa dựng video. Chọn ảnh/âm thanh, rồi bấm Dựng thử hoặc Bắt đầu xuất MP4. Xuất vào: ' + str(self.output_folder))
        ttk.Label(body,textvariable=self.status,wraplength=1080).pack(anchor='w')
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.after(150,self.poll)

    def error(self, exc):
        messagebox.showerror('Dựng Reel', str(exc), parent=self)

    def choose_audio(self):
        if self.busy: return
        path=filedialog.askopenfilename(parent=self,filetypes=[('Âm thanh','*.mp3 *.wav *.m4a *.aac')])
        if path:
            self.audio.set(path)
            sibling=Path(path).with_suffix('.srt')
            self.srt.set(str(sibling) if sibling.exists() else '')
            self.distribute()

    def choose_srt(self):
        if self.busy: return
        path=filedialog.askopenfilename(parent=self,filetypes=[('Phụ đề','*.srt')])
        if path: self.srt.set(path)

    def choose_music(self):
        if self.busy: return
        path=filedialog.askopenfilename(parent=self,filetypes=[('Âm thanh','*.mp3 *.wav *.m4a')])
        if path: self.music.set(path)

    def add_images(self):
        if self.busy: return
        paths=filedialog.askopenfilenames(parent=self,filetypes=[('Ảnh','*.png *.jpg *.jpeg *.webp *.bmp')])
        if paths:
            self.rows.extend({'image':p,'duration':5,'motion':MOTIONS[0],'note':''} for p in sorted(paths,key=natural_key))
            self.distribute()

    def distribute(self):
        if self.busy: return
        try:
            if not self.audio.get():
                self.refresh(); return
            self.duration=probe_duration(self.audio.get())
            cues=read_srt(self.srt.get())
            self.rows=make_plan([r['image'] for r in self.rows],self.duration,cues)
            self.refresh()
        except Exception as exc: self.error(exc)

    def import_prompts(self):
        if self.busy: return
        path=filedialog.askopenfilename(parent=self,filetypes=[('Prompt theo mốc','*.txt')])
        if not path: return
        try:
            self.duration=probe_duration(self.audio.get())
            rows=make_plan([r['image'] for r in self.rows],self.duration,read_srt(self.srt.get()),read_prompts(path))
            if not rows: raise ValueError('Thêm ảnh trước khi nhập prompt.')
            self.rows=rows
            self.refresh()
        except Exception as exc: self.error(exc)

    def refresh(self, selected=None):
        self.table.delete(*self.table.get_children())
        start=0
        for i,row in enumerate(self.rows):
            end=start+float(row['duration'])
            self.table.insert('', 'end',iid=str(i),values=(i+1,Path(row['image']).name,f'{start:.2f}',f'{end:.2f}',row['motion'],row.get('note','')))
            start=end
        self.info.set(f'{len(self.rows)} ảnh · Tổng ảnh: {start:.2f}s · MP3: {self.duration:.2f}s · Chênh lệch: {start-self.duration:+.2f}s. Chọn cảnh để sửa thời lượng / chuyển động.')
        if self.rows:
            index = min(max(selected if selected is not None else 0, 0),len(self.rows)-1)
            self.table.selection_set(str(index))
            self.table.focus(str(index))
            self.table.see(str(index))
            self.select_row()
        else:
            self.scene_duration.set('')
            self.note.delete('1.0','end')

    def selected(self):
        selected=self.table.selection()
        return int(selected[0]) if selected else None

    def select_row(self,event=None):
        index=self.selected()
        if index is None: return
        row=self.rows[index]
        self.scene_duration.set(f'{row["duration"]:.4f}')
        self.motion.set(row['motion'])
        self.note.delete('1.0','end')
        self.note.insert('1.0',row.get('note',''))

    def apply_row(self, notify=True):
        if self.busy: return False
        index=self.selected()
        if index is None:
            if notify:
                messagebox.showinfo('Chưa chọn ảnh', 'Chọn một dòng ảnh trong bảng để lưu chỉnh sửa.\n\nĐể dựng video, bấm Dựng thử hoặc Bắt đầu xuất MP4.', parent=self)
            return False
        try:
            duration=float(self.scene_duration.get().replace(',','.'))
            if not math.isfinite(duration) or duration < .1: raise ValueError('Mỗi cảnh phải dài ít nhất 0,1 giây.')
            self.rows[index].update(duration=duration,motion=self.motion.get(),note=self.note.get('1.0','end').strip())
            self.refresh(index)
            if notify:
                self.status.set(f'Đã lưu chỉnh sửa ảnh {index+1}. Để chạy video, bấm Dựng thử hoặc Bắt đầu xuất MP4.')
            return True
        except Exception as exc:
            self.error(exc)
            return False

    def move(self,step):
        if self.busy: return
        i=self.selected()
        if i is not None and 0 <= i+step < len(self.rows):
            self.rows[i],self.rows[i+step]=self.rows[i+step],self.rows[i]
            self.refresh(i+step)

    def remove_row(self):
        if self.busy: return
        i=self.selected()
        if i is not None:
            self.rows.pop(i)
            self.refresh(i)

    def show_image(self):
        i=self.selected()
        if i is not None: os.startfile(self.rows[i]['image'])

    def project(self):
        volume=float(self.music_volume.get())
        if not 0 <= volume <= 30: raise ValueError('Âm lượng nhạc nền từ 0 đến 30%.')
        return {'version':1,'audio':self.audio.get(),'srt':self.srt.get(),'music':self.music.get(),
                'music_volume':volume,'fit':self.fit.get(),'scenes':[dict(r) for r in self.rows]}

    def save_project(self):
        if self.selected() is not None and not self.apply_row(notify=False): return
        try:
            path=filedialog.asksaveasfilename(parent=self,defaultextension='.json',filetypes=[('Dự án Reel','*.json')])
            if path: Path(path).write_text(json.dumps(self.project(),ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception as exc: self.error(exc)

    def load_project(self):
        if self.busy: return
        path=filedialog.askopenfilename(parent=self,filetypes=[('Dự án Reel','*.json')])
        if not path: return
        try:
            p=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            duration=probe_duration(p['audio'])
            for row in p['scenes']:
                if not Path(row['image']).is_file(): raise ValueError('Thiếu ảnh: '+row['image'])
                if row['motion'] not in MOTIONS or float(row['duration']) <= 0: raise ValueError('Cảnh không hợp lệ.')
            self.rows=p['scenes']; self.duration=duration
            for var,key in [(self.audio,'audio'),(self.srt,'srt'),(self.music,'music'),(self.fit,'fit')]: var.set(p.get(key,''))
            self.music_volume.set(str(p.get('music_volume',12)))
            self.refresh()
        except Exception as exc: self.error(exc)

    def export(self,preview):
        if self.busy: return
        if self.selected() is not None and not self.apply_row(notify=False): return
        try:
            project=self.project()
            if not project['audio'] or not self.rows: raise ValueError('Chọn MP3 và thêm ảnh trước.')
            if project['srt']: read_srt(project['srt'])
            if project['music'] and not Path(project['music']).is_file(): raise ValueError('Không tìm thấy nhạc nền.')
            output=self.output_folder / (('preview_' if preview else 'reel_') + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.mp4')
            self.busy=True
            self.cancel_event.clear()
            self.preview_button.config(state='disabled'); self.export_button.config(state='disabled')
            self.bar['value']=0
            self.status.set('Chuẩn bị dựng video…')
            def work():
                try:
                    result=render_project(project,output,self.cancel_event,lambda msg,pct:self.events.put(('progress',(msg,pct))),preview)
                    self.events.put(('done',str(result)))
                except Cancelled: self.events.put(('cancelled','Đã hủy dựng.'))
                except Exception as exc: self.events.put(('error',str(exc)))
            threading.Thread(target=work,daemon=True).start()
        except Exception as exc: self.error(exc)

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='progress':
                    self.status.set(value[0]); self.bar['value']=value[1]
                else:
                    self.busy=False
                    self.preview_button.config(state='normal'); self.export_button.config(state='normal')
                    if kind=='done':
                        self.last_video=Path(value)
                        self.status.set('Đã xuất: '+value)
                        self.bar['value']=100
                        messagebox.showinfo('Dựng xong','Video đã sẵn sàng. Bấm Mở video vừa xuất để xem.',parent=self)
                    elif kind=='error': self.status.set('Xuất chưa thành công.'); self.error(value)
                    else: self.status.set(value)
        except queue.Empty: pass
        self.after(150,self.poll)

    def play(self):
        if self.last_video and self.last_video.exists(): os.startfile(str(self.last_video))

    def open_output(self):
        self.output_folder.mkdir(parents=True,exist_ok=True)
        os.startfile(str(self.output_folder))

    def close(self):
        if self.busy:
            if messagebox.askyesno('Đang dựng','Hủy dựng và đóng cửa sổ?',parent=self):
                self.cancel_event.set()
                self.status.set('Đang hủy, chờ tác vụ dừng rồi đóng cửa sổ.')
                self.after(300,self.close_after_cancel)
        else: self.destroy()

    def close_after_cancel(self):
        if self.busy: self.after(300,self.close_after_cancel)
        else: self.destroy()

if __name__ == '__main__':
    root=tk.Tk()
    root.withdraw()
    editor=ReelEditor(root)
    editor.bind('<Destroy>',lambda e:root.destroy() if e.widget is editor else None)
    root.mainloop()

"""Character settings and script headers shared by the editor and renderer."""
import json
from pathlib import Path
import re
import unicodedata
from voice_effects import validate_settings


CHARACTER_HEADER = r'^[ \t]*\[(?P<character>[^\[\]\r\n]+)\][ \t]*:[ \t]*'
EFFECTS = {'Tự nhiên': 'none', 'Hồn ma': 'ghost', 'Tùy chỉnh': 'custom'}
INLINE_VOICE = r'\[\[VOICE:(?P<inline_voice>[^\]\r\n]+)\]\][ \t]*'


def normalized(value):
    return unicodedata.normalize('NFC', value).strip().casefold()


def default_characters(voices):
    available = set(voices.values())
    male = 'vieneu:Hải Đăng' if 'vieneu:Hải Đăng' in available else 'vi-VN-NamMinhNeural'
    female = 'vieneu:Trúc Ly' if 'vieneu:Trúc Ly' in available else 'vi-VN-HoaiMyNeural'
    return {
        'Nam': dict(voice=male, rate=-5, pitch=0, expressive=False,
                    voice_effect='none', effect_strength=65),
        'Nữ': dict(voice=female, rate=-12, pitch=0, expressive=False,
                   voice_effect='ghost', effect_strength=65),
    }


def validate_characters(characters, voices=None):
    if not isinstance(characters, dict) or not 1 <= len(characters) <= 8:
        raise ValueError('Thiết lập cần từ 1 đến 8 nhân vật.')
    names = set()
    for name, profile in characters.items():
        if (not isinstance(name, str) or name != name.strip()
                or not re.fullmatch(r'[^\[\]:\r\n—–]{1,40}', name)
                or re.search(r'\s-\s', name)):
            raise ValueError('Tên nhân vật dài 1–40 ký tự; không dùng dấu ngoặc, dấu hai chấm hay dấu gạch phân cách.')
        if normalized(name) in names:
            raise ValueError('Tên các nhân vật phải khác nhau.')
        names.add(normalized(name))
        if not isinstance(profile, dict):
            raise ValueError(f'Thiết lập nhân vật {name} không hợp lệ.')
        voice = profile.get('voice')
        if not isinstance(voice, str) or not voice:
            raise ValueError(f'Hãy chọn giọng cho nhân vật {name}.')
        if voices is not None and voice not in voices.values():
            raise ValueError(f'Giọng của {name} không còn trong danh sách. Hãy chọn lại.')
        for key, low, high in [('rate', -50, 100), ('pitch', -50, 50), ('effect_strength', 0, 100)]:
            value = profile.get(key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'Thông số {key} của {name} phải từ {low} đến {high}.')
        if voice.startswith('vieneu:') and profile['pitch']:
            raise ValueError(f'Giọng VieNeu của {name} cần cao độ 0.')
        if type(profile.get('expressive')) is not bool or profile.get('voice_effect') not in EFFECTS.values():
            raise ValueError(f'Cách đọc / hiệu ứng của {name} không hợp lệ.')
        if profile.get('voice_effect') == 'custom':
            validate_settings(profile.get('effect_settings', {}))
        if 'ghost_settings' in profile:
            validate_settings(profile['ghost_settings'])
    return characters


def read_characters(path, voices):
    if not path.exists():
        return default_characters(voices)
    return validate_characters(json.loads(path.read_text(encoding='utf-8-sig')), voices)


def save_characters(path, characters, voices):
    validate_characters(characters, voices)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + '.part')
    try:
        temporary.write_text(json.dumps(characters, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_character(header, characters):
    parts = re.split(r'\s+[—–-]\s+', header.strip(), maxsplit=1)
    name = next((name for name in characters if normalized(name) == normalized(parts[0])), None)
    if name is None:
        raise ValueError(f'Chưa thiết lập nhân vật [{parts[0]}]. Mở “Nhân vật / giọng hồn ma” để đặt tên và chọn giọng.')
    profile = dict(characters[name])
    if len(parts) == 2:
        effect = next((effect for label, effect in EFFECTS.items()
                       if normalized(label) == normalized(parts[1])), None)
        if effect is None:
            raise ValueError(f'Chỉ dẫn [{header}] chưa hỗ trợ. Dùng [{name}], [{name} — hồn ma] hoặc [{name} — tự nhiên].')
        profile['voice_effect'] = effect
    if profile['voice_effect'] in ('ghost', 'custom'):
        if 'ghost_settings' in profile:
            profile.update(voice_effect='custom', effect_settings=validate_settings(profile['ghost_settings']))
        elif 'effect_settings' in profile:
            # Read previous custom ghost presets without changing their sound.
            profile.update(voice_effect='custom', effect_settings=validate_settings(profile['effect_settings']))
    elif profile['voice_effect'] == 'none':
        profile.pop('effect_settings', None)
    return dict(profile, character=name, character_header=header.strip())


def inline_turns(text):
    """Find one quoted turn after each caret-inserted voice marker."""
    turns = []
    for match in re.finditer(INLINE_VOICE, text):
        if turns and match.start() < turns[-1]['end']:
            raise ValueError('Không lồng dấu gán giọng bên trong một câu thoại.')
        start = match.end()
        if start >= len(text) or text[start] not in ('"', '“'):
            raise ValueError('Sau [[VOICE:…]] cần lời thoại trong dấu "..." hoặc “...”.')
        closing = '”' if text[start] == '“' else '"'
        ending = re.search(r'(?<!\\)' + re.escape(closing), text[start + 1:])
        if not ending:
            raise ValueError('Câu thoại chưa có dấu ngoặc kép đóng.')
        end = start + 1 + ending.start()
        turns.append(dict(start=match.start(), content_start=start + 1, content_end=end,
                          end=end + 1, voice=match.group('inline_voice').strip()))
    return turns


def example_script(names):
    male, female = list(names)[:2]
    return (f'[{male}]: Ai đang ở ngoài cửa vậy?\n\n'
            f'[{female}]: Anh… không nhớ em sao?\n\n'
            f'[{male}]: Nhưng em đã mất rồi mà…\n\n'
            f'[{female}]: Em vẫn luôn ở đây. Chờ anh trở về.')

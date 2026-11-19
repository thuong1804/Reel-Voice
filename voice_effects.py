"""Validated speech effects and reusable presets, independent of the TTS voice."""
import json
import math
from pathlib import Path


DEFAULTS = dict(pitch_st=0, bass_db=0, treble_db=0, ghost_mix=0,
                echo_mix=0, echo_delay_ms=250, echo_repeats=3, echo_feedback=45,
                reverb_mix=0, room_size=50)
LIMITS = dict(pitch_st=(-12, 12), bass_db=(-12, 12), treble_db=(-12, 12),
              ghost_mix=(0, 100), echo_mix=(0, 100), echo_delay_ms=(50, 1000),
              echo_repeats=(1, 6), echo_feedback=(0, 85), reverb_mix=(0, 100), room_size=(0, 100))
BUILTINS = {
    'Không hiệu ứng': dict(DEFAULTS),
    'Hồn ma nhẹ': dict(DEFAULTS, ghost_mix=65),
    'Vang hang động': dict(DEFAULTS, echo_mix=25, echo_delay_ms=350, echo_repeats=4,
                          reverb_mix=35, room_size=80),
}


def validate_settings(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('Cấu hình hiệu ứng không đúng định dạng.')
    result = dict(DEFAULTS, **value)
    for key, (low, high) in LIMITS.items():
        number = result[key]
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'{key} phải từ {low} đến {high}.')
        if key in ('echo_repeats', 'echo_delay_ms') and int(number) != number:
            raise ValueError(f'{key} phải là số nguyên.')
    return result


def has_effects(settings):
    settings = validate_settings(settings)
    return any(settings[key] for key in ('pitch_st', 'bass_db', 'treble_db',
                                         'ghost_mix', 'echo_mix', 'reverb_mix'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.part')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_settings(path):
    path = Path(path)
    return validate_settings(json.loads(path.read_text(encoding='utf-8-sig'))) if path.exists() else dict(DEFAULTS)


def read_presets(path):
    path = Path(path)
    custom = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    if not isinstance(custom, dict):
        raise ValueError('Thư viện preset hiệu ứng không đúng định dạng.')
    return dict(BUILTINS, **{name: validate_settings(value) for name, value in custom.items()})


def save_preset(path, name, settings):
    name = name.strip()
    if not name or len(name) > 80:
        raise ValueError('Tên preset cần từ 1 đến 80 ký tự.')
    presets = read_presets(path)
    presets[name] = validate_settings(settings)
    write_json(path, presets)


def settings_for_profile(profile):
    """Return the ghost variant's settings, independent of its ordinary voice."""
    if 'ghost_settings' in profile:
        return validate_settings(profile['ghost_settings'])
    if profile.get('voice_effect') == 'custom':
        return validate_settings(profile.get('effect_settings', {}))
    return dict(DEFAULTS, ghost_mix=profile.get('effect_strength', 65))


def speech_filter(effect='none', strength=65, settings=None):
    if effect not in ('none', 'ghost', 'custom'):
        raise ValueError('Hiệu ứng giọng nói không hợp lệ.')
    if type(strength) is not int or not 0 <= strength <= 100:
        raise ValueError('Mức hiệu ứng giọng nói phải từ 0 đến 100%.')
    if effect == 'none' or (effect == 'ghost' and strength == 0):
        return None
    if effect == 'custom':
        return custom_filter(validate_settings(settings if settings is not None else {}))
    amount = strength / 100
    # A quiet detuned double and diffuse echoes sit behind the unshifted voice.
    # aecho emits its tail; the caller counts those frames before the next turn.
    delays = '79|137|211|307|419|563|733|947|1193'
    decays = '|'.join(f'{value * amount:.4f}' for value in
                      (.18, .15, .13, .11, .09, .075, .06, .04, .025))
    return (
        'aresample=48000,asplit=2[dry][double];'
        '[double]asetrate=46560,aresample=48000,atempo=1.030927835,'
        'highpass=f=180,lowpass=f=3500,adelay=35:all=1[shade];'
        f"[dry][shade]amix=inputs=2:duration=longest:normalize=0:weights='0.82 {0.22 * amount:.4f}',"
        f'aecho=0.85:1:{delays}:{decays},'
        'alimiter=limit=0.95:level=0:latency=1'
    )


def custom_filter(settings):
    if not has_effects(settings):
        return None
    chain = ['aresample=48000']
    if settings['pitch_st']:
        factor = 2 ** (settings['pitch_st'] / 12)
        chain.append(f'rubberband=tempo=1:pitch={factor:.8f}')
    if settings['bass_db']:
        chain.append(f'bass=g={settings["bass_db"]}:f=180')
    if settings['treble_db']:
        chain.append(f'treble=g={settings["treble_db"]}:f=3500')
    if settings['ghost_mix']:
        chain.append(speech_filter('ghost', max(1, round(settings['ghost_mix']))))
    if settings['reverb_mix']:
        # Two banks of diffuse reflections approximate room reverb.
        size = .35 + settings['room_size'] / 100 * 1.65
        amount = settings['reverb_mix'] / 100
        for times in ((31, 53, 79, 113, 157, 211), (43, 97, 173, 281, 419)):
            delays = '|'.join(str(round(value * size)) for value in times)
            decays = '|'.join(f'{amount * .17 * (.78 ** index):.5f}' for index in range(len(times)))
            chain.append(f'aecho=1:1:{delays}:{decays}')
    if settings['echo_mix']:
        amount = settings['echo_mix'] / 100
        feedback = settings['echo_feedback'] / 100
        repeats = int(settings['echo_repeats'])
        delays = '|'.join(str(int(settings['echo_delay_ms']) * (index + 1)) for index in range(repeats))
        decays = '|'.join(f'{min(.9, amount * feedback ** index):.5f}' for index in range(repeats))
        chain.append(f'aecho=1:1:{delays}:{decays}')
    chain.append('alimiter=limit=0.95:level=0:latency=1')
    return ','.join(chain)

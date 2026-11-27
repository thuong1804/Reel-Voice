"""Verify the supplied structure, measured timing and isolation of sound effects."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np
import reel_voice
from dialogue import default_characters
from short_pacing import (BY_KEY, SPECS, STYLE, canonical_script, extract_sections,
                          short_plan, template, word_count)
from story_audio import plain_script, read_cues, render_story
from test_dialogue import VOICES, write_tone

SAMPLE = (Path(__file__).resolve().parent / 'examples' / 'vai_do_6_nhip.txt').read_text(encoding='utf-8')
EXAMPLE = tuple(section['text'] for section in extract_sections(SAMPLE))


def tone(path, seconds):
    frames = round(seconds * 48000)
    samples = (np.sin(2*np.pi*180*np.arange(frames)/48000) * 5000).astype('<i2')
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        audio.writeframes(samples.tobytes())


class SectionTests(unittest.TestCase):
    def test_runtime_outline_has_only_empty_beat_labels(self):
        lines = [line.strip() for line in template().splitlines() if line.strip()]
        self.assertEqual(lines, [f'[[BEAT:{spec["key"]}]]' for spec in SPECS])

    def test_custom_six_paragraph_story_is_used_without_replacing_its_words(self):
        parts = ['Tôi đứng cạnh giếng.', 'Chiếc gương quay vào tường.', 'Đêm đầu có một vệt sáng.',
                 'Tôi chạm vào thành giếng.', 'Cái bóng ngẩng đầu nhìn tôi.', 'Ai đứng sau lưng bạn?']
        text = '\n\n'.join(parts)
        plan = short_plan(text, {}, default_characters(VOICES))
        self.assertEqual([item['text'] for item in plan if item['kind'] == 'speech'], parts)
        self.assertNotIn('vải đỏ', plain_script(plan).lower())

    def test_sample_data_has_157_words_and_the_six_windows(self):
        sections = extract_sections(SAMPLE)
        self.assertEqual([item['key'] for item in sections], list(BY_KEY))
        self.assertEqual(sum(word_count(item['text']) for item in sections), 157)
        self.assertEqual([spec['end'] for spec in SPECS], [4, 14, 24, 35, 47, 55])

    def test_six_unlabelled_paragraphs_use_the_same_order(self):
        sections = extract_sections('\n\n'.join(EXAMPLE))
        self.assertEqual([item['key'] for item in sections], list(BY_KEY))
        self.assertEqual([item['text'] for item in sections], list(EXAMPLE))

    def test_markdown_reads_only_voice_blocks_and_excludes_visuals_and_cta(self):
        text = '# Hướng dẫn\nKhông đọc phần này.\n\n'
        for index, (spec, voice) in enumerate(zip(SPECS, EXAMPLE), 1):
            text += f'### NHỊP {index} — {spec["label"]} (0:00–0:55)\n*Hình:* Tiếng gõ cửa.\n\n> {voice}\n\n'
        text += '## 7. MẪU ĐĂNG BÀI\n> Like và follow.\n'
        self.assertEqual(canonical_script(text), SAMPLE)

    def test_invalid_order_or_unassigned_prefix_is_rejected(self):
        for text in ['[[BEAT:END]]\nKết.\n[[BEAT:HOOK]]\nBắt đầu.',
                     '[[BEAT:HOOK]]\nA.\n[[BEAT:HOOK]]\nB.',
                     'Lời thừa.\n[[BEAT:HOOK]]\nBắt đầu.']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                extract_sections(text)

    def test_draft_uses_2_point_8_words_per_second_without_inventing_six_beats(self):
        text = 'Tôi vừa nghe thấy tiếng ai gọi tên mình.'
        plan = short_plan(text, {}, default_characters(VOICES))
        self.assertEqual({item['short_section'] for item in plan}, {'DRAFT'})
        self.assertAlmostEqual(plan[0]['short_duration'], word_count(text)/2.8)

    def test_staccato_climax_and_ghost_settings_are_independent(self):
        characters = default_characters(VOICES)
        before = deepcopy(characters)
        plan = short_plan(SAMPLE, {}, characters)
        self.assertEqual(characters, before)
        self.assertEqual(SPECS[3]['sentence'], .06)
        climax = [item for item in plan if item['short_section'] == 'CLIMAX']
        self.assertIn(.24, [item['seconds'] for item in climax if item['kind'] == 'pause'])
        speech = [item for item in plan if item['kind'] == 'speech']
        self.assertTrue(all(item['rate'] == 0 and item['pitch'] == 0 and not item['expressive'] for item in speech))
        self.assertTrue(all('voice_effect' not in item for item in speech))

    def test_preview_uses_only_the_current_whole_beat(self):
        text = SAMPLE
        plan = short_plan(text, {}, default_characters(VOICES), text.index('Tóc tôi đen'))
        self.assertEqual({item['short_section'] for item in plan}, {'LEO2'})
        self.assertEqual(plan[0]['short_duration'], 11)

    def test_export_preserves_beat_metadata_and_roles(self):
        text = '[[BEAT:HOOK]]\nTôi hỏi. [[VOICE:Nữ — hồn ma]]"Em đây."'
        plan = short_plan(text, {}, default_characters(VOICES))
        restored = short_plan(plain_script(plan), {}, default_characters(VOICES))
        self.assertEqual([item.get('voice') for item in plan if item['kind'] == 'speech'],
                         [item.get('voice') for item in restored if item['kind'] == 'speech'])
        self.assertEqual(restored[0]['short_duration'], 4)


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class TimingTests(unittest.TestCase):
    def test_render_hits_all_six_boundaries_with_real_decoded_frames(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            script = '\n\n'.join(f'[[BEAT:{spec["key"]}]]\nMột câu thoại ngắn.' for spec in SPECS)
            plan = short_plan(script, {}, default_characters(VOICES))
            def render(text, destination, item):
                path = destination.with_suffix('.wav')
                duration = item['short_duration'] * .8
                tone(path, duration)
                return path, [(0, duration, text)]
            target = folder / 'short.mp3'
            render_story(plan, target, render)
            timing = json.loads(target.with_suffix('.timing.json').read_text(encoding='utf-8'))
            self.assertEqual(timing['total_seconds'], 55)
            self.assertEqual([row['actual_start'] for row in timing['sections']], [0, 4, 14, 24, 35, 47])
            self.assertEqual([row['actual_end'] for row in timing['sections']], [4, 14, 24, 35, 47, 55])
            cues = read_cues(target.with_suffix('.srt'))
            self.assertEqual([cue[0] for cue in cues], [0, 4, 14, 24, 35, 47])
            self.assertTrue(all('BEAT' not in cue[2] for cue in cues))

    def test_sfx_is_not_time_stretched_and_explicit_pause_is_preserved(self):
        import story_audio
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            sfx = folder / 'door.wav'
            write_tone(sfx)
            effects = {'door': dict(name='Door', path=str(sfx))}
            script = '[[BEAT:HOOK]]\nTôi nói. [[SFX:door:80]][[PAUSE:0.7]] Tôi đáp.'
            plan = short_plan(script, effects, default_characters(VOICES))
            effect = next(item for item in plan if item['kind'] == 'effect')
            self.assertEqual(effect['volume'], 80)
            self.assertTrue(any(item['kind'] == 'pause' and item['seconds'] == .7 and not item.get('auto') for item in plan))
            def render(text, destination, item):
                path = destination.with_suffix('.wav')
                tone(path, 1.3)
                return path, [(0, 1.3, text)]
            original = story_audio.run_ffmpeg
            with patch.object(story_audio, 'run_ffmpeg', wraps=original) as ffmpeg:
                target = folder / 'short.mp3'
                render_story(plan, target, render)
            call = next(call for call in ffmpeg.call_args_list if str(sfx) in call.args[1])
            self.assertEqual(call.args[1][call.args[1].index('-af')+1], 'volume=0.8')
            timing = json.loads(target.with_suffix('.timing.json').read_text(encoding='utf-8'))
            self.assertAlmostEqual(timing['total_seconds'], 4.3, places=3)

    def test_impossible_explicit_pause_fails_without_synthesizing(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = short_plan('[[BEAT:HOOK]]\nLời đọc.[[PAUSE:5]]', {}, default_characters(VOICES))
            with patch('short_pacing.run_ffmpeg'), self.assertRaises(ValueError):
                render_story(plan, Path(temp) / 'bad.mp3', lambda *args: self.fail('Must reject before TTS'))

    def test_ghost_tail_and_settings_are_preserved_outside_the_voice_window(self):
        from voice_effects import DEFAULTS
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            characters = default_characters(VOICES)
            characters['Nữ']['ghost_settings'] = dict(DEFAULTS, echo_mix=30, echo_delay_ms=300, echo_repeats=2)
            before = deepcopy(characters)
            plan = short_plan('[[BEAT:HOOK]]\n[[VOICE:Nữ — hồn ma]]"Em vẫn ở đây."', {}, characters)
            def render(text, destination, item):
                path = destination.with_suffix('.wav')
                tone(path, 3.5)
                return path, [(0, 3.5, text)]
            target = folder / 'ghost.mp3'
            render_story(plan, target, render)
            timing = json.loads(target.with_suffix('.timing.json').read_text(encoding='utf-8'))
            self.assertAlmostEqual(timing['total_seconds'], 4.6, places=2)
            self.assertEqual(characters, before)


class EditorTests(unittest.TestCase):
    def test_default_preset_controls_and_preview_keep_beat_context(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(reel_voice, 'BASE', Path(temp)):
            app = reel_voice.App()
            app.withdraw()
            try:
                self.assertEqual(app.delivery.get(), 'Kịch tính')
                self.assertEqual(str(app.rate_box['state']), 'normal')
                self.assertEqual(app.rate.get(), '-12')
                self.assertEqual(app.sentence_pause.get(), '0.45')
                self.assertEqual(app.text.get('1.0', 'end-1c'), '')
                app.delivery.set(STYLE)
                self.assertEqual(str(app.rate_box['state']), 'disabled')
                app.text.insert('1.0', SAMPLE)
                text = app.text.get('1.0', 'end-1c')
                offset = text.index('Tóc tôi đen')
                app.text.mark_set('insert', f'1.0+{offset}c')
                with patch.object(reel_voice.mp, 'Process') as process:
                    app.start(True)
                    plan = process.call_args.kwargs['args'][7]
                    self.assertEqual({item['short_section'] for item in plan}, {'LEO2'})
                    process.return_value.is_alive.return_value = False
                    app.cancel()
                app.delivery.set('Tự nhiên')
                self.assertEqual(str(app.rate_box['state']), 'normal')
                self.assertEqual(app.sentence_pause.get(), '0.45')
            finally:
                app.destroy()


if __name__ == '__main__':
    unittest.main()

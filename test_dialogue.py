"""Regression checks for role routing, preview context and decoded audio timing."""
from copy import deepcopy
import math
from pathlib import Path
import queue
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

from dialogue import default_characters, read_characters, save_characters, validate_characters
from story_audio import SAMPLE_RATE, plain_script, read_cues, render_story, script_excerpt, script_plan
from voice_effects import speech_filter
import reel_voice
import vieneu_runner


VOICES = {'Male': 'vi-VN-NamMinhNeural', 'Female': 'vi-VN-HoaiMyNeural'}
SCRIPT = '[Nam]: Ai đó?\n[Nữ — hồn ma]: Em đây.\n[nam]: Ai?'


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.characters = default_characters(VOICES)

    def plan(self, text, sentence=.1, paragraph=.2):
        return script_plan(text, sentence, paragraph, {}, self.characters)

    def test_roles_never_enter_spoken_text_and_do_not_leak(self):
        speech = [item for item in self.plan(SCRIPT) if item['kind'] == 'speech']
        self.assertEqual([item['text'] for item in speech], ['Ai đó?', 'Em đây.', 'Ai?'])
        self.assertEqual([item['voice'] for item in speech],
                         [VOICES['Male'], VOICES['Female'], VOICES['Male']])
        self.assertEqual([item['voice_effect'] for item in speech], ['none', 'ghost', 'none'])

    def test_unlabelled_narrator_and_multiline_turn(self):
        speech = [item for item in self.plan('Đêm tối.\n[Nữ]: Em đây.\n\nVẫn chờ anh.')
                  if item['kind'] == 'speech']
        self.assertNotIn('voice', speech[0])
        self.assertEqual([item['character'] for item in speech[1:]], ['Nữ', 'Nữ'])

    def test_unknown_role_and_unsupported_direction_fail_early(self):
        for value in ['[Khách]: Xin chào.', '[Nữ — hét]: Anh ơi.']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.plan(value)

    def test_explicit_pause_and_inline_effect_override(self):
        plan = self.plan('[Nữ — tự nhiên]: Em đây.[[PAUSE:1.3]]\n[Nam]: Ai đó?')
        speech = [item for item in plan if item['kind'] == 'speech']
        self.assertEqual(speech[0]['voice_effect'], 'none')
        self.assertEqual([item['seconds'] for item in plan if item['kind'] == 'pause'], [1.3])

    def test_preview_inherits_role_and_does_not_duplicate_headers(self):
        start = SCRIPT.index('Em đây.')
        excerpt = script_excerpt(SCRIPT, start, start + len('Em đây.'))
        self.assertEqual(self.plan(excerpt)[0]['voice_effect'], 'ghost')
        start = SCRIPT.index('[Nữ')
        excerpt = script_excerpt(SCRIPT, start, SCRIPT.index('\n[nam]'))
        self.assertEqual(self.plan(excerpt)[0]['text'], 'Em đây.')
        excerpt = script_excerpt(SCRIPT, start + 2, SCRIPT.index('\n[nam]'))
        self.assertEqual(self.plan(excerpt)[0]['character'], 'Nữ')

    def test_preview_current_paragraph_inherits_prior_turn(self):
        text = '[Nữ]: Em đây.\n\nVẫn chờ anh.\n\n[Nam]: Ai đó?'
        excerpt = script_excerpt(text, text.index('chờ'))
        self.assertEqual(self.plan(excerpt)[0]['voice'], VOICES['Female'])
        self.assertEqual(self.plan(excerpt)[0]['text'], 'Vẫn chờ anh.')

    def test_exported_script_can_be_loaded_with_same_roles(self):
        exported = plain_script(self.plan(SCRIPT))
        speech = [item for item in self.plan(exported) if item['kind'] == 'speech']
        self.assertEqual([item['voice_effect'] for item in speech], ['none', 'ghost', 'none'])

    def test_export_does_not_turn_every_sentence_into_a_character_change(self):
        exported = plain_script(self.plan('[Nữ]: Em đây. Vẫn chờ anh.'))
        self.assertEqual(exported, '[Nữ]: Em đây. Vẫn chờ anh.')

    def test_plain_script_keeps_existing_behaviour(self):
        plan = self.plan('Một câu.\n\nMột đoạn khác.')
        self.assertTrue(all('voice' not in item for item in plan))
        self.assertEqual(plain_script(plan), 'Một câu. Một đoạn khác.')

    def test_settings_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'characters.json'
            save_characters(path, self.characters, VOICES)
            self.assertEqual(read_characters(path, VOICES), self.characters)
            self.assertFalse(Path(str(path) + '.part').exists())
        invalid = deepcopy(self.characters)
        invalid['NAM'] = invalid['Nam']
        with self.assertRaises(ValueError):
            validate_characters(invalid, VOICES)
        invalid = deepcopy(self.characters)
        invalid['Nữ']['effect_strength'] = 101
        with self.assertRaises(ValueError):
            validate_characters(invalid, VOICES)


def write_tone(path, duration=.3, amplitude=5000):
    frames = round(SAMPLE_RATE * duration)
    # A short voiced section followed by silence makes the echo tail measurable.
    pcm = b''.join(struct.pack('<h', round(amplitude * math.sin(2 * math.pi * 180 * index / SAMPLE_RATE)))
                   if index < frames * .8 else b'\0\0' for index in range(frames))
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, SAMPLE_RATE, 0, 'NONE', 'not compressed'))
        audio.writeframes(pcm)
    return pcm


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class AudioTests(unittest.TestCase):
    def test_fx_tail_is_counted_and_next_natural_turn_is_unprocessed(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / 'source.wav'
            original = write_tone(source)
            characters = default_characters(VOICES)
            plan = script_plan('[Nữ]: Em đây.\n[Nam]: Ai đó?', 0, 0, {}, characters)
            seen = []
            def render(text, destination, item):
                seen.append(item['voice'])
                return source, [(0, .3, text)]
            target = folder / 'preview.wav'
            render_story(plan, target, render, preview=True)
            with wave.open(str(target), 'rb') as result:
                pcm = result.readframes(result.getnframes())
            self.assertGreater(len(pcm), 2 * len(original))
            self.assertEqual(pcm[-len(original):], original)
            ghost = pcm[:-len(original)]
            tail = struct.unpack('<' + 'h' * ((len(ghost) - len(original)) // 2), ghost[len(original):])
            self.assertGreater(sum(value * value for value in tail), 0)
            self.assertLessEqual(max(abs(value) for value in struct.unpack('<' + 'h' * (len(pcm)//2), pcm)), 32767)
            self.assertEqual(seen, [VOICES['Female'], VOICES['Male']])
            self.assertFalse(target.with_suffix('.story.part').exists())
            # Full export uses the actual processed duration to offset the next subtitle.
            target = folder / 'export.mp3'
            render_story(plan, target, render)
            cues = read_cues(target.with_suffix('.srt'))
            self.assertEqual(cues[0], (0, .3, 'Em đây.'))
            self.assertAlmostEqual(cues[1][0], len(ghost) / 2 / SAMPLE_RATE, places=3)
            self.assertEqual(cues[1][2], 'Ai đó?')
            self.assertNotIn('[Nữ]', target.with_suffix('.srt').read_text(encoding='utf-8-sig'))
            self.assertIn('[Nữ]', target.with_suffix('.txt').read_text(encoding='utf-8'))

    def test_zero_strength_is_identical_to_natural_audio(self):
        self.assertIsNone(speech_filter('ghost', 0))
        self.assertIsNone(speech_filter('none', 100))

    def test_failure_removes_staging_and_published_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'failed.mp3'
            def fail(*args):
                raise RuntimeError('test backend failure')
            with self.assertRaises(RuntimeError):
                render_story([{'kind': 'speech', 'text': 'Hello.'}], target, fail)
            self.assertFalse(target.with_suffix('.story.part').exists())
            self.assertFalse(target.exists())

    def test_sfx_is_not_routed_through_ghost_filter(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'effect.wav'
            original = write_tone(source)
            characters = default_characters(VOICES)
            effects = {'door': {'path': str(source), 'name': 'Door'}}
            plan = script_plan('[Nữ]: [[SFX:door:100]]', 0, 0, effects, characters)
            target = Path(temp) / 'preview.wav'
            render_story(plan, target, lambda *args: self.fail('SFX must not request TTS'), preview=True)
            with wave.open(str(target), 'rb') as result:
                self.assertEqual(result.readframes(result.getnframes()), original)


class RoutingTests(unittest.TestCase):
    def test_vieneu_dialogue_uses_one_model_job_and_keeps_narrator(self):
        events = queue.Queue()
        characters = default_characters({'Male': 'vieneu:Hải Đăng', 'Female': 'vieneu:Trúc Ly'})
        plan = script_plan('Lời kể.\n[Nữ]: Em đây.', 0, 0, {}, characters)
        with patch.object(reel_voice, 'vieneu_synthesize', return_value=Path('result.mp3')) as backend:
            reel_voice.worker(events, SCRIPT, 'vieneu:Hải Đăng', -5, 0, 'result.mp3', plan=plan)
        self.assertEqual(backend.call_count, 1)
        self.assertEqual(backend.call_args.args[1], 'vieneu:Hải Đăng')
        self.assertEqual(events.get_nowait(), ('done', 'result.mp3'))

    def test_mixed_backends_route_each_turn_with_its_settings(self):
        events = queue.Queue()
        plan = [
            dict(kind='speech', text='Edge.', voice='vi-VN-HoaiMyNeural', rate=-12, pitch=0, expressive=False),
            dict(kind='speech', text='Local.', voice='vieneu:Trúc Ly', rate=-8, pitch=0, expressive=False),
            dict(kind='speech', text='Offline.', voice='offline:Zira', rate=0, pitch=0, expressive=False)]
        seen = []
        def edge(text, voice, rate, pitch, destination):
            seen.append((voice, rate))
        def local(text, voice, rate, destination, *args):
            seen.append((voice, rate))
            return destination
        def offline(text, voice, rate, pitch, destination, *args):
            seen.append((voice, rate))
            return destination
        def story(items, target, render, *args, **kwargs):
            for i, item in enumerate(items):
                render(item['text'], Path(f'{i}.mp3'), item)
            return target
        with patch.object(reel_voice, 'synthesize', edge), patch.object(reel_voice, 'vieneu_synthesize', local), \
                patch.object(reel_voice, 'offline_synthesize', offline), patch.object(reel_voice, 'render_story', story), \
                patch.object(reel_voice, 'read_cues', return_value=[]), patch.object(reel_voice.asyncio, 'run'):
            reel_voice.worker(events, '', 'vieneu:Hải Đăng', -5, 0, 'result.mp3', plan=plan)
        self.assertEqual(seen, [('vi-VN-HoaiMyNeural', -12), ('vieneu:Trúc Ly', -8), ('offline:Zira', 0)])
        self.assertEqual(events.get_nowait(), ('done', 'result.mp3'))

    def test_vieneu_story_switches_voices_without_loading_sdk(self):
        try:
            import numpy as np
            import soundfile as sf
        except ImportError:
            self.skipTest('VieNeu environment required')
        calls = []
        class FakeTTS:
            def infer(self, text, voice):
                calls.append((text, voice))
                return np.zeros(2400, dtype=np.float32)
            def save(self, audio, filename):
                sf.write(filename, audio, 24000)
        with tempfile.TemporaryDirectory() as temp:
            characters = default_characters({'Male': 'vieneu:Hải Đăng', 'Female': 'vieneu:Trúc Ly'})
            plan = script_plan(SCRIPT, 0, 0, {}, characters)
            job = dict(story_plan=plan, target=str(Path(temp) / 'story.mp3'), rate=0)
            with patch.object(vieneu_runner, 'emit'):
                vieneu_runner.render_vieneu_story(FakeTTS(), 'Hải Đăng', job)
            self.assertEqual([voice for _, voice in calls], ['Hải Đăng', 'Trúc Ly', 'Hải Đăng'])


@unittest.skipUnless(sys.platform == 'win32', 'Windows Tk application')
class EditorTests(unittest.TestCase):
    def test_character_editor_and_preview_selected_inside_female_turn(self):
        from character_dialog import CharacterDialog
        with tempfile.TemporaryDirectory() as temp, patch.object(reel_voice, 'BASE', Path(temp)):
            app = reel_voice.App()
            app.withdraw()
            app.delivery.set('Tự nhiên')
            try:
                app.characters_path = Path(temp) / 'characters.json'
                app.characters = default_characters(VOICES)
                dialog = CharacterDialog(app, reel_voice.VOICES)
                dialog.withdraw()
                app.text.tag_add('sel', '1.0', 'end-1c')
                dialog.save(insert_example=True)
                self.assertTrue(app.characters_path.exists())
                script = app.text.get('1.0', 'end-1c')
                self.assertIn('[Nữ]:', script)
                self.assertNotIn('thời tiền sử', script)
                start = script.index('không nhớ')
                app.text.tag_remove('sel', '1.0', 'end')
                app.text.tag_add('sel', f'1.0+{start}c', f'1.0+{start + 12}c')
                # No pauses still needs character parsing.
                app.sentence_pause.set('0')
                app.paragraph_pause.set('0')
                app.voice.set('Tiếng Việt · Nam · Nam Minh')
                with patch.object(reel_voice.mp, 'Process') as process:
                    app.start(True)
                    self.assertTrue(app.busy)
                    plan = process.call_args.kwargs['args'][7]
                    speech = [item for item in plan if item['kind'] == 'speech']
                    self.assertEqual(speech[0]['voice'], VOICES['Female'])
                    self.assertEqual(speech[0]['voice_effect'], 'ghost')
                    self.assertNotIn('[Nữ', speech[0]['text'])
                    process.return_value.is_alive.return_value = False
                    app.cancel()
                self.assertIsNone(app.preview_audio)
                self.assertIsNone(app.preview_temp)
                self.assertEqual(str(app.character_button['state']), 'normal')
            finally:
                app.destroy()


if __name__ == '__main__':
    unittest.main()

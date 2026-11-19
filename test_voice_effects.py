"""Audio, preset, caret insertion and quoted-turn regression tests."""
from copy import deepcopy
import math
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

import reel_voice
from dialogue import default_characters, inline_turns, save_characters
from expressive_voice import run_ffmpeg
from story_audio import plain_script, read_cues, render_story, script_excerpt, script_plan
from voice_effects import (BUILTINS, DEFAULTS, has_effects, read_presets, read_settings, save_preset,
                           speech_filter, validate_settings, write_json)
from test_dialogue import VOICES, write_tone


class QuotedTurnTests(unittest.TestCase):
    def setUp(self):
        self.characters = default_characters(VOICES)

    def plan(self, text):
        return script_plan(text, .1, .2, {}, self.characters)

    def test_female_ghost_then_narrator_then_male_ghost(self):
        plan = self.plan('Tôi hỏi. [[VOICE:Nữ — hồn ma]]"Em đây." Tôi nhìn lại. '
                         '[[VOICE:Nam — hồn ma]]“Đừng đi.” Trời tối.')
        speech = [item for item in plan if item['kind'] == 'speech']
        self.assertEqual([item['text'] for item in speech],
                         ['Tôi hỏi.', 'Em đây.', 'Tôi nhìn lại.', 'Đừng đi.', 'Trời tối.'])
        self.assertEqual([item.get('voice') for item in speech],
                         [None, VOICES['Female'], None, VOICES['Male'], None])
        self.assertEqual([item.get('voice_effect') for item in speech],
                         [None, 'ghost', None, 'ghost', None])

    def test_quote_returns_to_previous_character_and_explicit_narrator(self):
        plan = self.plan('[Nam]: Tôi nói. [[VOICE:Nữ]]"Em đây." Tôi đáp. '
                         '[[VOICE:Người kể]]"Trời tối."')
        speech = [item for item in plan if item['kind'] == 'speech']
        self.assertEqual([item.get('voice') for item in speech],
                         [VOICES['Male'], VOICES['Female'], VOICES['Male'], None])

    def test_preview_inside_quote_keeps_assignment(self):
        text = 'Tôi hỏi. [[VOICE:Nữ — hồn ma]]"Em vẫn đang chờ anh." Tôi đáp.'
        start = text.index('đang')
        excerpt = script_excerpt(text, start, start + len('đang chờ anh'))
        speech = [item for item in self.plan(excerpt) if item['kind'] == 'speech']
        self.assertEqual(speech[0]['text'], 'đang chờ anh')
        self.assertEqual(speech[0]['voice'], VOICES['Female'])

    def test_export_roundtrip_preserves_return_to_narrator(self):
        original = self.plan('Tôi hỏi. [[VOICE:Nữ]]"Em đây." Tôi đáp.')
        restored = self.plan(plain_script(original))
        self.assertEqual([item.get('voice') for item in restored if item['kind'] == 'speech'],
                         [None, VOICES['Female'], None])

    def test_bad_quotes_and_nested_markers_fail_before_tts(self):
        for text in ['[[VOICE:Nữ]]Không có ngoặc.', '[[VOICE:Nữ]]"Chưa đóng.',
                     '[[VOICE:Nữ]]"[[VOICE:Nam]]“Lồng nhau.”"', '[[VOICE:Khách]]"Xin chào."']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.plan(text)

    def test_escaped_inner_quotes_are_not_end_of_turn(self):
        text = r'[[VOICE:Nữ]]"Em nói \"xin chào\" với anh." Tôi đáp.'
        self.assertEqual(len(inline_turns(text)), 1)
        speech = [item for item in self.plan(text) if item['kind'] == 'speech']
        self.assertEqual(speech[-1]['text'], 'Tôi đáp.')
        self.assertEqual(speech[0]['voice'], VOICES['Female'])
        self.assertNotIn('\\', speech[0]['text'])
        restored = [item for item in self.plan(plain_script(self.plan(text))) if item['kind'] == 'speech']
        self.assertEqual(speech[0]['text'], restored[0]['text'])


class PresetTests(unittest.TestCase):
    def test_neutral_custom_has_no_processing_even_if_dormant_knobs_change(self):
        self.assertFalse(has_effects(dict(DEFAULTS, echo_delay_ms=500, room_size=90)))
        self.assertIsNone(speech_filter('custom', 100, DEFAULTS))
        self.assertIsNotNone(speech_filter('custom', 0, dict(DEFAULTS, echo_mix=30)))
        self.assertIsNotNone(speech_filter('custom', 100, dict(DEFAULTS, ghost_mix=.2)))

    def test_validate_settings_rejects_nonfinite_and_out_of_range(self):
        for value in [dict(echo_mix=float('nan')), dict(pitch_st=13), dict(echo_repeats=1.5),
                      dict(echo_delay_ms=50.5), dict(echo_mix='0,volume=100'), dict(other=10)]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_settings(value)

    def test_preset_save_reload_and_json_export(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'presets.json'
            settings = dict(DEFAULTS, echo_mix=40, echo_delay_ms=400, pitch_st=-2)
            save_preset(path, 'Nữ hồn ma của tôi', settings)
            self.assertEqual(read_presets(path)['Nữ hồn ma của tôi'], settings)
            self.assertIn('Không hiệu ứng', read_presets(path))
            exported = Path(temp) / 'share.json'
            write_json(exported, settings)
            self.assertEqual(read_settings(exported), settings)

    def test_per_character_settings_survive_save_and_ghost_override(self):
        characters = default_characters(VOICES)
        settings = dict(DEFAULTS, ghost_mix=30, echo_mix=20, pitch_st=-1)
        characters['Nữ'].update(voice_effect='custom', effect_settings=settings)
        with tempfile.TemporaryDirectory() as temp:
            save_characters(Path(temp) / 'characters.json', characters, VOICES)
        speech = script_plan('[[VOICE:Nữ — hồn ma]]"Em đây."', 0, 0, {}, characters)[0]
        self.assertEqual(speech['effect_settings'], settings)
        self.assertEqual(speech['voice_effect'], 'custom')

    def test_ghost_settings_never_affect_natural_variant_and_zero_is_honoured(self):
        characters = default_characters(VOICES)
        characters['Nam']['ghost_settings'] = dict(DEFAULTS, echo_mix=35)
        natural = script_plan('[[VOICE:Nam — tự nhiên]]"Xin chào."', 0, 0, {}, characters)[0]
        ghost = script_plan('[[VOICE:Nam — hồn ma]]"Xin chào."', 0, 0, {}, characters)[0]
        self.assertEqual(natural['voice_effect'], 'none')
        self.assertEqual(ghost['effect_settings']['echo_mix'], 35)
        self.assertEqual(ghost['effect_settings']['ghost_mix'], 0)
        characters['Nam']['ghost_settings'] = dict(DEFAULTS)
        ghost = script_plan('[[VOICE:Nam — hồn ma]]"Xin chào."', 0, 0, {}, characters)[0]
        self.assertIsNone(speech_filter(ghost['voice_effect'], ghost['effect_strength'], ghost['effect_settings']))

    def test_updated_ghost_settings_override_legacy_custom_profile(self):
        characters = default_characters(VOICES)
        characters['Nữ'].update(voice_effect='custom', effect_settings=dict(DEFAULTS, echo_mix=10),
                                 ghost_settings=dict(DEFAULTS, echo_mix=60))
        speech = script_plan('[Nữ]: Em đây.', 0, 0, {}, characters)[0]
        self.assertEqual(speech['effect_settings']['echo_mix'], 60)


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class ConfiguredAudioTests(unittest.TestCase):
    def test_pitch_changes_frequency_while_preserving_duration(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source.wav'
            original = write_tone(source, duration=1)
            effect = speech_filter('custom', 100, dict(DEFAULTS, pitch_st=12))
            pcm = run_ffmpeg(shutil.which('ffmpeg'), ['-i', str(source), '-af', effect,
                             '-f', 's16le', '-ar', '48000', '-ac', '1', 'pipe:1'])
            self.assertLess(abs(len(pcm) - len(original)), 960)
            samples = np.frombuffer(pcm, dtype='<i2')[4800:28800].astype(float)
            spectrum = np.abs(np.fft.rfft(samples))
            frequency = np.argmax(spectrum) * 48000 / len(samples)
            self.assertAlmostEqual(frequency, 360, delta=5)

    def test_limiter_handles_loud_combined_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source.wav'
            write_tone(source, amplitude=30000)
            effect = speech_filter('custom', 100, dict(DEFAULTS, bass_db=12, treble_db=12,
                echo_mix=100, echo_feedback=85, echo_repeats=6, ghost_mix=100))
            pcm = run_ffmpeg(shutil.which('ffmpeg'), ['-i', str(source), '-af', effect,
                             '-f', 'f32le', '-ar', '48000', '-ac', '1', 'pipe:1'])
            samples = struct.unpack('<' + 'f' * (len(pcm) // 4), pcm)
            self.assertLessEqual(max(abs(value) for value in samples), .951)

    def test_builtin_and_combined_effects_decode_without_clipping(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source.wav'
            original = write_tone(source)
            settings_list = list(BUILTINS.values()) + [dict(DEFAULTS, pitch_st=-3, bass_db=3,
                treble_db=-3, ghost_mix=40, echo_mix=35, echo_delay_ms=220, echo_repeats=2,
                reverb_mix=30, room_size=75)]
            for settings in settings_list:
                with self.subTest(settings=settings):
                    effect = speech_filter('custom', 100, settings)
                    args = ['-i', str(source)]
                    if effect:
                        args += ['-af', effect]
                    pcm = run_ffmpeg(shutil.which('ffmpeg'), [*args, '-f', 's16le', '-ar', '48000', '-ac', '1', 'pipe:1'])
                    self.assertGreaterEqual(len(pcm), len(original) - 2000)
                    if has_effects(settings):
                        self.assertNotEqual(pcm, original)

    def test_custom_echo_duration_offsets_next_narrator_caption(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / 'source.wav'
            write_tone(source)
            characters = default_characters(VOICES)
            characters['Nữ'].update(voice_effect='custom',
                effect_settings=dict(DEFAULTS, echo_mix=35, echo_delay_ms=400, echo_repeats=3))
            plan = script_plan('[[VOICE:Nữ]]"Em đây." Tôi đáp.', 0, 0, {}, characters)
            target = folder / 'story.mp3'
            render_story(plan, target, lambda text, dest, item: (source, [(0, .3, text)]))
            cues = read_cues(target.with_suffix('.srt'))
            self.assertAlmostEqual(cues[1][0], 1.5, places=2)
            self.assertNotIn('VOICE', cues[0][2])


class EffectEditorTests(unittest.TestCase):
    def make_app(self, temp):
        with patch.object(reel_voice, 'BASE', Path(temp)):
            app = reel_voice.App()
        app.withdraw()
        app.delivery.set('Tự nhiên')
        app.characters = default_characters(VOICES)
        return app

    def test_caret_menu_wraps_selected_dialogue_and_keeps_narration(self):
        from voice_insert_dialog import VoiceInsertDialog
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            try:
                app.text.delete('1.0', 'end')
                app.text.insert('1.0', 'Tôi hỏi. "Em đây." Tôi đáp.')
                app.text.tag_add('sel', '1.9', '1.18')
                dialog = VoiceInsertDialog(app)
                dialog.withdraw()
                dialog.voice.set('Nữ — hồn ma')
                dialog.insert()
                script = app.text.get('1.0', 'end-1c')
                plan = script_plan(script, 0, 0, {}, app.characters)
                speech = [item for item in plan if item['kind'] == 'speech']
                self.assertEqual([item['text'] for item in speech], ['Tôi hỏi.', 'Em đây.', 'Tôi đáp.'])
                self.assertEqual(speech[1]['voice'], VOICES['Female'])
                self.assertNotIn('voice', speech[2])
                app.highlight_voices()
                self.assertTrue(app.text.tag_ranges('ghost_dialogue'))
            finally:
                app.destroy()

    def test_ghost_menu_saves_effects_only_for_selected_character(self):
        from effect_dialog import GhostEffectDialog
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            try:
                female_before = deepcopy(app.characters['Nữ'])
                dialog = GhostEffectDialog(app, reel_voice.VOICES)
                dialog.withdraw()
                dialog.target_name.set('Nam')
                dialog.load_target()
                dialog.variables['echo_mix'].set('35')
                dialog.variables['echo_delay_ms'].set('300')
                dialog.preset_name.set('My ghost')
                dialog.save_preset()
                dialog.apply()
                self.assertEqual(app.characters['Nam']['ghost_settings']['echo_mix'], 35)
                self.assertEqual(app.characters['Nam']['voice_effect'], 'none')
                self.assertEqual(app.characters['Nữ'], female_before)
                self.assertEqual(read_presets(app.fx_presets_path)['My ghost']['echo_delay_ms'], 300)
                self.assertIn('hồn ma', str(app.voice_fx_button['text']))
            finally:
                app.destroy()

    def test_old_global_effect_file_is_ignored_and_narrator_audio_stays_dry(self):
        with tempfile.TemporaryDirectory() as temp:
            write_json(Path(temp) / 'outputs' / 'voice_effect.json', dict(DEFAULTS, echo_mix=100, ghost_mix=100))
            app = self.make_app(temp)
            try:
                app.characters['Nữ']['ghost_settings'] = dict(DEFAULTS, echo_mix=40, echo_delay_ms=300,
                                                              echo_repeats=2)
                app.text.delete('1.0', 'end')
                app.text.insert('1.0', 'Tôi hỏi. [[VOICE:Nữ — hồn ma]]"Em đây." Tôi đáp.')
                app.sentence_pause.set('0')
                app.paragraph_pause.set('0')
                with patch.object(reel_voice.mp, 'Process') as process:
                    app.start(False)
                    plan = process.call_args.kwargs['args'][7]
                    speech = [item for item in plan if item['kind'] == 'speech']
                    self.assertNotIn('voice_effect', speech[0])
                    self.assertEqual(speech[1]['effect_settings']['echo_mix'], 40)
                    self.assertNotIn('voice_effect', speech[2])
                    process.return_value.is_alive.return_value = False
                    app.cancel()
                source = Path(temp) / 'raw.wav'
                raw = write_tone(source)
                target = Path(temp) / 'output.wav'
                render_story(plan, target, lambda text, dest, item: (source, [(0, .3, text)]), preview=True)
                with wave.open(str(target), 'rb') as audio:
                    pcm = audio.readframes(audio.getnframes())
                self.assertEqual(pcm[:len(raw)], raw)
                self.assertEqual(pcm[-len(raw):], raw)
                self.assertGreater(len(pcm), len(raw) * 3)
                app.text.delete('1.0', 'end')
                app.text.insert('1.0', 'Chỉ có giọng kể.')
                with patch.object(reel_voice.mp, 'Process') as process:
                    app.start(False)
                    self.assertIsNone(process.call_args.kwargs['args'][7])
                    process.return_value.is_alive.return_value = False
                    app.cancel()
            finally:
                app.destroy()

    def test_editing_ghost_effects_does_not_switch_natural_character_to_ghost(self):
        from character_dialog import CharacterDialog
        from effect_dialog import EffectDialog
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            try:
                characters = CharacterDialog(app, reel_voice.VOICES)
                characters.withdraw()
                row = characters.rows[0]
                self.assertEqual(row['effect'].get(), 'Tự nhiên')
                characters.configure_effects(row)
                effect = next(child for child in characters.winfo_children() if isinstance(child, EffectDialog))
                effect.withdraw()
                effect.variables['echo_mix'].set('20')
                effect.apply()
                self.assertEqual(row['effect'].get(), 'Tự nhiên')
                characters.save()
                self.assertEqual(app.characters['Nam']['voice_effect'], 'none')
                self.assertEqual(app.characters['Nam']['ghost_settings']['echo_mix'], 20)
            finally:
                app.destroy()

    def test_effect_dialog_previews_real_audio_and_cleans_temporary_file(self):
        from effect_dialog import EffectDialog
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            try:
                source = Path(temp) / 'raw.wav'
                write_tone(source)
                app.effect_sample_path = source
                dialog = EffectDialog(app, app, dict(DEFAULTS, echo_mix=20), lambda value: None)
                dialog.withdraw()
                with patch.object(app, 'play_audio') as play, patch('effect_dialog.messagebox.showerror') as error:
                    dialog.listen()
                    error.assert_not_called()
                    self.assertEqual(play.call_count, 1)
                    target = play.call_args.args[0]
                    with wave.open(str(target), 'rb') as audio:
                        self.assertGreater(audio.getnframes(), 14400)
                dialog.close()
                self.assertFalse(target.exists())
            finally:
                app.destroy()

    def test_caret_inside_existing_quotes_assigns_then_changes_role_without_nesting(self):
        from voice_insert_dialog import VoiceInsertDialog
        with tempfile.TemporaryDirectory() as temp:
            app = self.make_app(temp)
            try:
                app.text.delete('1.0', 'end')
                app.text.insert('1.0', 'Tôi hỏi. "Em đây." Tôi đáp.')
                app.text.mark_set('insert', '1.12')
                dialog = VoiceInsertDialog(app)
                dialog.withdraw()
                dialog.voice.set('Nữ — hồn ma')
                dialog.insert()
                script = app.text.get('1.0', 'end-1c')
                start = script.index('Em đây')
                app.text.tag_remove('sel', '1.0', 'end')
                app.text.mark_set('insert', f'1.0+{start+2}c')
                dialog = VoiceInsertDialog(app)
                dialog.withdraw()
                self.assertEqual(dialog.voice.get(), 'Nữ — hồn ma')
                dialog.voice.set('Nam — hồn ma')
                dialog.insert()
                script = app.text.get('1.0', 'end-1c')
                self.assertEqual(script.count('[[VOICE:'), 1)
                speech = [item for item in script_plan(script, 0, 0, {}, app.characters) if item['kind'] == 'speech']
                self.assertEqual(speech[1]['voice'], VOICES['Male'])
                self.assertEqual(speech[1]['text'], 'Em đây.')
            finally:
                app.destroy()


if __name__ == '__main__':
    unittest.main()

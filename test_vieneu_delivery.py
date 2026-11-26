"""Regression checks for ReelVoice mood delivery and preview context."""
import unittest

from story_audio import script_excerpt, script_plan
from vieneu_runner import sentence_profile


class MoodDeliveryTests(unittest.TestCase):
    def test_explicit_moods_keep_sentence_contours_even_with_natural_delivery(self):
        for mood in ('tram', 'tham', 'gap', 'ma'):
            with self.subTest(mood=mood):
                steady = sentence_profile('Toi nghe thay tieng dong o phia sau.', .9, False, mood)
                question = sentence_profile('Co ai dang dung o phia sau toi?', .9, False, mood)
                startled = sentence_profile('Co nguoi dang dung o phia sau toi!', .9, False, mood)
                self.assertNotEqual(steady[:2], question[:2])
                self.assertNotEqual(steady[:2], startled[:2])
                self.assertEqual(steady[3], question[3])

    def test_ellipsis_is_not_treated_as_a_generic_short_sentence(self):
        waiting = sentence_profile('Ngay sat chan toi...', .9, True)
        statement = sentence_profile('Ngay sat chan toi.', .9, True)
        self.assertNotEqual(waiting[:2], statement[:2])

    def test_plain_natural_delivery_is_unchanged(self):
        self.assertEqual(sentence_profile('Ai dang o do?', .9, False),
                         (1.0, 0.0, .9, [], 0.0))

    def test_emphasis_preserves_mood_identity_and_bounded_sampling(self):
        for mood in ('tram', 'tham', 'gap', 'ma'):
            with self.subTest(mood=mood):
                speed, pitch, temp, filters, gain = sentence_profile(
                    'Co ai dang dung o phia sau toi?!', 1.2, False, mood)
                self.assertTrue(.7 <= speed <= 1.25)
                self.assertTrue(-3 <= pitch <= 2)
                self.assertTrue(.5 <= temp <= 1.2)
                if mood == 'ma':
                    self.assertTrue(any(f.startswith('aecho=') for f in filters))


class PreviewMoodTests(unittest.TestCase):
    def assert_preview_mood(self, text, selected, expected):
        start = text.index(selected)
        excerpt = script_excerpt(text, start, start + len(selected))
        speech = [item for item in script_plan(excerpt, 0, 0, {})
                  if item['kind'] == 'speech']
        self.assertEqual(speech[0].get('mood'), expected)
        self.assertEqual(speech[0]['text'], selected)

    def test_selection_inherits_active_mood(self):
        self.assert_preview_mood(
            '[[MOOD:tham]] Toi dung lai. Con ai trong phong?',
            'Con ai trong phong?', 'tham')

    def test_reset_before_selection_does_not_leak_previous_mood(self):
        self.assert_preview_mood(
            '[[MOOD:ma]] Em day. [[MOOD:binhthuong]] Toi lui lai.',
            'Toi lui lai.', None)

    def test_paragraph_preview_inherits_mood_without_copying_old_words(self):
        text = '[[MOOD:gap]] Toi quay lai.\n\nCanh cua da dong.'
        excerpt = script_excerpt(text, text.index('Canh cua'))
        speech = [item for item in script_plan(excerpt, 0, 0, {})
                  if item['kind'] == 'speech']
        self.assertEqual(speech[0].get('mood'), 'gap')
        self.assertEqual(speech[0]['text'], 'Canh cua da dong.')


    def test_inline_mood_scope_matches_full_export(self):
        from dialogue import default_characters
        from test_dialogue import VOICES
        characters = default_characters(VOICES)
        female = 'N\u1eef'
        cases = [
            (f'[[VOICE:{female}]]"[[MOOD:ma]] Em day. Cau sau."', 'Cau sau.', 'ma'),
            (f'[[MOOD:tram]] Toi hoi. [[VOICE:{female}]]"Em day. Cau sau."', 'Cau sau.', None),
            (f'[[MOOD:tram]] Toi hoi. [[VOICE:{female}]]"[[MOOD:ma]] Em day." Toi dap.', 'Toi dap.', 'tram'),
            (f'[[VOICE:{female}]]"[[MOOD:ma]] Em day. [[MOOD:binhthuong]] Cau sau."', 'Cau sau.', None),
        ]
        for text, selected, expected in cases:
            with self.subTest(text=text):
                start = text.index(selected)
                full = script_plan(text, 0, 0, {}, characters)
                excerpt = script_excerpt(text, start, start + len(selected))
                preview = script_plan(excerpt, 0, 0, {}, characters)
                original = next(i for i in full if i.get('text') == selected)
                item = next(i for i in preview if i['kind'] == 'speech')
                self.assertEqual(item.get('mood'), expected)
                self.assertEqual(item.get('mood'), original.get('mood'))
                self.assertEqual(item.get('voice'), original.get('voice'))



if __name__ == '__main__':
    unittest.main()

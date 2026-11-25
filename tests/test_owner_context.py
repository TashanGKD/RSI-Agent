import unittest

from trigger.owner_context import assemble


def message(role, content):
    return {'role': role, 'content': content}


class OwnerContextTests(unittest.TestCase):
    def test_empty_context_stays_empty(self):
        self.assertEqual(assemble(), [])

    def test_priority_keeps_base_then_memory_then_knowledge_then_history(self):
        base = [message('system', 'identity')]
        memory = [message('system', 'memory rule'), message('user', '{"owner_named_memory":[]}')]
        knowledge = [message('system', 'knowledge rule'), message('user', '{"knowledge_snippets":[]}')]
        history = [message('user', 'earlier'), message('assistant', 'earlier reply')]
        result = assemble(base, memory, knowledge, history)
        self.assertEqual(result, base + memory + knowledge + history)

    def test_oldest_history_is_dropped_before_newer_turns_with_a_note(self):
        history = [message('user', 'OLD' * 100), message('assistant', 'OLD_REPLY' * 100),
                   message('user', 'NEW'), message('assistant', 'NEW_REPLY')]
        result = assemble([], [], [], history, max_bytes=600)
        self.assertEqual(result[:-1], history[2:])
        self.assertEqual(result[-1]['role'], 'system')
        self.assertIn('省略', result[-1]['content'])

    def test_memory_unit_is_not_split_when_it_does_not_fit(self):
        memory = [message('system', 'rule ' + 'M' * 200), message('user', 'M' * 200)]
        result = assemble([], memory, [], [], max_bytes=400)
        self.assertFalse(any(item in result for item in memory))
        self.assertIn('省略', result[-1]['content'])

    def test_required_base_is_kept_even_when_it_exceeds_the_budget(self):
        base = [message('system', 'BASE ' + 'B' * 400)]
        result = assemble(base, [message('user', 'memory')], [], [], max_bytes=400)
        self.assertEqual(result[0], base[0])
        self.assertFalse(any(item['content'] == 'memory' for item in result))
        self.assertIn('省略', result[-1]['content'])

    def test_duplicate_messages_are_injected_once(self):
        duplicate = message('user', 'same')
        result = assemble([duplicate], [], [], [duplicate, message('assistant', 'reply')],
                          max_bytes=2000)
        self.assertEqual(result.count(duplicate), 1)
        self.assertEqual(result[-1], message('assistant', 'reply'))

    def test_history_order_stays_chronological_when_everything_fits(self):
        history = [message('user', '1'), message('assistant', '1r'),
                   message('user', '2'), message('assistant', '2r')]
        self.assertEqual(assemble([], [], [], history, max_bytes=4000), history)

    def test_budget_must_exceed_the_note_reserve(self):
        with self.assertRaises(ValueError):
            assemble(max_bytes=256)


if __name__ == '__main__':
    unittest.main()
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import locale_check as checker


HERE = Path(__file__).resolve().parent
EXAMPLES = HERE / 'ejemplos'


class LocaleCheckTests(unittest.TestCase):
    def findings(self, source, translation, kind):
        return checker.compare(source, translation)['findings'][kind]

    def cli(self, source, translation, *options):
        return subprocess.run(
            [sys.executable, str(HERE / 'locale_check.py'), str(source),
             str(translation), *options],
            capture_output=True, text=True, encoding='utf-8', timeout=10,
        )

    def test_rails_wrappers_are_removed(self):
        source = checker.load_file(EXAMPLES / 'origen.yml')
        translation = checker.load_file(EXAMPLES / 'traduccion.yml')
        self.assertEqual(list(source), ['shop'])
        self.assertEqual(list(translation), ['shop'])
        report = checker.compare(source, translation)
        self.assertEqual(report['summary'], {
            'missing': 1, 'extra': 1, 'variables': 3, 'html': 1,
            'plural_forms': 1, 'identical': 1,
        })

    def test_missing_and_extra_keys(self):
        report = checker.compare({'a': 'Hello'}, {'b': 'Olá'})
        self.assertEqual(report['findings']['missing'][0]['key'], 'a')
        self.assertEqual(report['findings']['extra'][0]['key'], 'b')
        self.assertTrue(checker.has_errors(report))

    def test_renamed_ruby_count(self):
        self.assertEqual(len(self.findings(
            {'x': '%{count} items'}, {'x': '%{total} itens'}, 'variables')), 1)

    def test_unnumbered_printf_order_must_match(self):
        items = self.findings({'x': '%s %d'}, {'x': '%d %s'}, 'variables')
        self.assertEqual(len(items), 1)
        self.assertIn('fuera de orden', items[0]['reason'])

    def test_numbered_printf_may_move(self):
        self.assertFalse(self.findings(
            {'x': '%1$s %2$s'}, {'x': '%2$s %1$s'}, 'variables'))
        self.assertFalse(self.findings(
            {'x': '%1$s %2$d'}, {'x': '%2$d %1$s'}, 'variables'))

    def test_link_markers_may_be_translated_inside(self):
        self.assertFalse(self.findings(
            {'x': 'See __Docs__ for more'}, {'x': 'Consulta la __documentación__'}, 'variables'))

    def test_lost_or_unclosed_link_marker_fails(self):
        self.assertTrue(self.findings(
            {'x': 'See __Docs__'}, {'x': 'Ver Docs'}, 'variables'))
        self.assertTrue(self.findings(
            {'x': 'See __Docs__'}, {'x': 'Ver __Docs'}, 'variables'))
        self.assertTrue(self.findings(
            {'x': '__Top up__ or __add a key__'}, {'x': '__Recarga o añade una clave__'}, 'variables'))

    def test_numbered_printf_change_or_loss_fails(self):
        for translated in ['%1$s', '%1$s %2$s', '%1$s %1$s %2$d']:
            with self.subTest(translated=translated):
                self.assertTrue(self.findings(
                    {'x': '%1$s %2$d'}, {'x': translated}, 'variables'))

    def test_printf_precision_and_escaped_percent(self):
        self.assertEqual(checker.positional('%% %s %5.2f'), ['%s', '%5.2f'])
        self.assertFalse(self.findings(
            {'x': 'Value %5.2f %%'}, {'x': 'Valor %5.2f %%'}, 'variables'))
        self.assertTrue(self.findings(
            {'x': '%5.2f'}, {'x': '%5.1f'}, 'variables'))

    def test_lost_double_brace_variable(self):
        self.assertTrue(self.findings(
            {'x': 'Hello {{name}}'}, {'x': 'Olá'}, 'variables'))

    def test_simple_brace_variable_and_named_printf(self):
        for source, translated in [
            ('Hello {name}', 'Olá {person}'),
            ('%<name>s arrived', '%<person>s chegou'),
        ]:
            with self.subTest(source=source):
                self.assertTrue(self.findings(
                    {'x': source}, {'x': translated}, 'variables'))
        self.assertFalse(self.findings(
            {'x': '{{ name }} {count} %<user>s'},
            {'x': '%<user>s {count} {{name}}'}, 'variables'))

    def test_variable_occurrences_are_counted(self):
        self.assertTrue(self.findings(
            {'x': '{{name}} {{name}}'}, {'x': '{{name}}'}, 'variables'))

    def test_named_printf_is_not_html(self):
        report = checker.compare(
            {'x': '%<name>s arrived'}, {'x': '%<person>s chegou'})
        self.assertEqual(report['summary']['variables'], 1)
        self.assertEqual(report['summary']['html'], 0)
        unchanged = checker.compare(
            {'x': '%<name>s arrived'}, {'x': '%<name>s chegou'})
        self.assertFalse(checker.has_errors(unchanged))
        self.assertTrue(self.findings(
            {'x': '<b>%<name>s arrived</b>'},
            {'x': '<b>%<name>s chegou'}, 'html'))

    def test_unclosed_anchor(self):
        items = self.findings(
            {'x': '<a>Help</a>'}, {'x': '<a>Ajuda'}, 'html')
        self.assertEqual(len(items), 1)
        self.assertIn('sin cerrar', items[0]['reason'])

    def test_equal_tag_inventory_does_not_hide_bad_nesting(self):
        self.assertTrue(self.findings(
            {'x': '<b><i>Ready</i></b>'},
            {'x': '<b><i>Pronto</b></i>'}, 'html'))

    def test_html_attributes_and_void_tags(self):
        self.assertFalse(self.findings(
            {'x': '<p>Ready<br><img src="a"></p>'},
            {'x': '<p>Pronto<br><img src="a"></p>'}, 'html'))
        self.assertTrue(self.findings(
            {'x': '<a href="/a">Go</a>'},
            {'x': '<a href="/b">Ir</a>'}, 'html'))

    def test_bad_source_html_is_reported(self):
        items = self.findings({'x': '<b>Hello'}, {'x': '<b>Olá'}, 'html')
        self.assertIn('origen', items[0]['reason'])

    def test_identical_text_needs_three_letters(self):
        source = {'brand': 'Harbor', 'short': 'OK', 'digits': '123',
                  'mixed': 'A1B2C', 'accented': 'Áéí'}
        report = checker.compare(source, dict(source))
        self.assertEqual(
            {item['key'] for item in report['findings']['identical']},
            {'brand', 'mixed', 'accented'},
        )
        self.assertFalse(checker.has_errors(report))

    def test_plural_differences_are_advisory(self):
        report = checker.compare(
            {'cart': {'one': 'One item', 'few': 'Few items', 'other': 'Items'}},
            {'cart': {'one': 'Um item', 'many': 'Muitos itens', 'other': 'Itens'}},
        )
        self.assertFalse(report['findings']['missing'])
        self.assertFalse(report['findings']['extra'])
        self.assertEqual(len(report['findings']['plural_forms']), 1)
        self.assertIn('few', report['findings']['plural_forms'][0]['reason'])
        self.assertIn('many', report['findings']['plural_forms'][0]['reason'])
        self.assertFalse(checker.has_errors(report))

    def test_shared_plural_leaves_still_check_variables(self):
        report = checker.compare(
            {'cart': {'one': '%{count} item', 'other': '%{count} items'}},
            {'cart': {'one': '%{total} item', 'other': '%{count} itens'}},
        )
        self.assertEqual(report['findings']['variables'][0]['key'], 'cart.one')

    def test_added_plural_form_with_broken_html_fails(self):
        report = checker.compare(
            {'cart': {'one': '<b>%{count}</b> item', 'other': '<b>%{count}</b> items'}},
            {'cart': {'one': '<b>%{count}</b> produkt', 'few': '<b>%{count} produkty',
                      'other': '<b>%{count}</b> produktów'}},
        )
        self.assertEqual([item['key'] for item in report['findings']['html']], ['cart.few'])
        self.assertTrue(checker.has_errors(report))

    def test_added_plural_form_with_different_tags_fails(self):
        report = checker.compare(
            {'cart': {'one': '<b>%{count}</b> item', 'other': '<b>%{count}</b> items'}},
            {'cart': {'one': '<b>%{count}</b> produkt', 'few': '<i>%{count}</i> produkty',
                      'other': '<b>%{count}</b> produktów'}},
        )
        self.assertEqual(report['findings']['html'][0]['key'], 'cart.few')
        self.assertIn('other', report['findings']['html'][0]['reason'])

    def test_correct_added_plural_form_is_advisory_only(self):
        report = checker.compare(
            {'cart': {'one': '<b>%{count}</b> item', 'other': '<b>%{count}</b> items'}},
            {'cart': {'one': '<b>%{count}</b> produkt', 'few': '<b>%{count}</b> produkty',
                      'many': '<b>%{count}</b> produktów', 'other': '<b>%{count}</b> produktu'}},
        )
        self.assertFalse(report['findings']['html'])
        self.assertEqual(report['summary']['plural_forms'], 1)
        self.assertFalse(checker.has_errors(report))

    def test_added_plural_form_with_invented_named_variable_fails(self):
        report = checker.compare(
            {'cart': {'one': '%{count} item', 'other': '%{count} items'}},
            {'cart': {'one': '%{count} produkt', 'few': '%{total} produkty',
                      'other': '%{count} produktów'}},
        )
        self.assertEqual([item['key'] for item in report['findings']['variables']], ['cart.few'])
        self.assertIn('total', report['findings']['variables'][0]['reason'])
        self.assertTrue(checker.has_errors(report))

    def test_added_plural_form_with_invented_numbered_variable_fails(self):
        report = checker.compare(
            {'cart': {'one': '%1$d item in %2$s', 'other': '%1$d items in %2$s'}},
            {'cart': {'one': '%1$d produkt w %2$s', 'few': '%1$d produkty w %3$s',
                      'other': '%1$d produktów w %2$s'}},
        )
        self.assertEqual([item['key'] for item in report['findings']['variables']], ['cart.few'])
        self.assertTrue(checker.has_errors(report))

    def test_added_plural_form_may_drop_or_reuse_source_variables(self):
        report = checker.compare(
            {'cart': {'one': 'One item in %{cart_name}', 'other': '%{count} items in %{cart_name}'}},
            {'cart': {'one': 'Jeden produkt w %{cart_name}', 'few': '%{count} produkty w %{cart_name}',
                      'many': 'Wiele produktów', 'other': '%{count} produktu w %{cart_name}'}},
        )
        self.assertFalse(report['findings']['variables'])
        self.assertFalse(checker.has_errors(report))

    def test_entire_missing_plural_group_is_not_suppressed(self):
        report = checker.compare({'cart': {'one': 'One', 'other': 'Several'}}, {})
        self.assertEqual(report['summary']['missing'], 2)
        self.assertEqual(report['summary']['plural_forms'], 0)

    def test_nonplural_sibling_prevents_plural_classification(self):
        report = checker.compare(
            {'cart': {'one': 'One', 'label': 'Cart'}},
            {'cart': {'label': 'Carrinho'}},
        )
        self.assertEqual(report['findings']['missing'][0]['key'], 'cart.one')

    def test_nested_json_and_arrays(self):
        source = checker.load_file(EXAMPLES / 'origen.json')
        translation = checker.load_file(EXAMPLES / 'traduccion.json')
        leaves, _ = checker.flatten(source)
        self.assertIn('checkout.labels.0', leaves)
        report = checker.compare(source, translation)
        self.assertEqual(report['summary'], {
            'missing': 0, 'extra': 0, 'variables': 1, 'html': 1,
            'plural_forms': 0, 'identical': 1,
        })

    def test_json_cli_and_failure_exit_code(self):
        result = self.cli(EXAMPLES / 'origen.json', EXAMPLES / 'traduccion.json',
                          '--format', 'json')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['summary']['variables'], 1)
        self.assertEqual(report['findings']['html'][0]['key'], 'checkout.html')

    def test_yaml_cli_markdown(self):
        result = self.cli(EXAMPLES / 'origen.yml', EXAMPLES / 'traduccion.yml')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('## Resumen', result.stdout)
        self.assertIn('shop.count', result.stdout)
        self.assertIn('Formas plurales distintas, revisar', result.stdout)

    def test_invalid_yaml_has_clear_error_without_traceback(self):
        result = self.cli(EXAMPLES / 'invalido.yml', EXAMPLES / 'traduccion.yml')
        self.assertEqual(result.returncode, 2)
        self.assertIn('YAML inválido', result.stderr)
        self.assertIn('línea', result.stderr)
        self.assertNotIn('Traceback', result.stderr + result.stdout)

    def test_advisories_alone_have_zero_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.json'
            target = Path(directory) / 'target.json'
            source.write_text(json.dumps({'brand': 'Harbor', 'cart': {
                'one': 'One', 'few': 'A few', 'other': 'Several'}}), encoding='utf-8')
            target.write_text(json.dumps({'brand': 'Harbor', 'cart': {
                'one': 'Um', 'many': 'Muitos', 'other': 'Vários'}}), encoding='utf-8')
            result = self.cli(source, target, '--format', 'json')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['summary']['plural_forms'], 1)

    def test_invalid_json_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'
            for text, expected in [('{} trailing', 'JSON inválido'),
                                   ('{"x":1,"x":2}', 'duplicada')]:
                with self.subTest(text=text):
                    path.write_text(text, encoding='utf-8')
                    with self.assertRaisesRegex(checker.InputError, expected):
                        checker.load_file(path)
            path = Path(directory) / 'bad.yaml'
            path.write_text('title: First\ntitle: Second\n', encoding='utf-8')
            with self.assertRaisesRegex(checker.InputError, 'duplicada'):
                checker.load_file(path)

    def test_json_locale_namespace_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.json'
            path.write_text('{"en": {"title": "Hello"}}', encoding='utf-8')
            self.assertIn('en.title', checker.flatten(checker.load_file(path))[0])

    def test_yaml_namespace_is_not_a_locale_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.yaml'
            path.write_text('screens:\n  title: Hello\n', encoding='utf-8')
            self.assertIn('screens.title', checker.flatten(checker.load_file(path))[0])

    def test_ambiguous_flattened_keys_and_recursive_aliases_fail(self):
        with self.assertRaisesRegex(checker.InputError, 'ambiguas'):
            checker.flatten({'a.b': 'first', 'a': {'b': 'second'}})
        recursive = {}
        recursive['loop'] = recursive
        with self.assertRaisesRegex(checker.InputError, 'recursiva'):
            checker.flatten(recursive)

    def test_cli_does_not_modify_inputs(self):
        paths = [EXAMPLES / 'origen.yml', EXAMPLES / 'traduccion.yml']
        before = [path.read_bytes() for path in paths]
        result = self.cli(*paths)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(before, [path.read_bytes() for path in paths])


if __name__ == '__main__':
    unittest.main()

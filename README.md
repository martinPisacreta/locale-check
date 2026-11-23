# locale-check

A small command-line check that compares a translated locale file with its source file and reports what usually breaks at runtime:

- **missing and extra keys** (nested keys are flattened with dots; arrays use their index)
- **placeholders**: Rails/i18n `%{name}` and `%<name>s`, Mustache/i18next `{{name}}`, ICU-style `{name}`, numbered printf `%1$s` (may move), unnumbered printf `%s`/`%d`/`%.1f` (order must match); occurrences are counted, `%%` is ignored
- **HTML tags**: same tags and attributes, and correct nesting in both files (void tags like `<br>` are allowed)
- **link markers** `__text__`: the text inside may be translated, but each marker has to survive and be closed
- **plural forms** (`one`, `other`, `few`…) that differ: reported for review, not as an error, because languages need different forms
- **identical text**: reported for review, since it may be intentional ("OK", brand names)

It reads JSON and YAML (`.json`, `.yml`, `.yaml`), removes a single top-level locale wrapper such as `en:` / `de:` in YAML, rejects duplicate keys, and never modifies the input files.

## Usage

Python 3.11 or newer with PyYAML:

```sh
pip install pyyaml
python locale_check.py en.yml de.yml              # Markdown report
python locale_check.py en.json es.json --format json
```

Exit codes: `0` no blocking findings (advisories only), `1` missing/extra keys, placeholder or HTML problems, `2` invalid input (bad YAML/JSON, duplicate keys).
That makes it usable as a CI step.

The report labels are currently in Spanish (for example "Claves que faltan" = missing keys, "Variables distintas" = different placeholders). The JSON output uses English field names: `missing`, `extra`, `variables`, `html`, `plural_forms`, `identical`.

## Example

`samples/en.yml` and `samples/de.yml` contain a few deliberate mistakes. Running

```sh
python locale_check.py samples/en.yml samples/de.yml
```

reports, among others:

- `checkout.total`: `%{amount}` became `%{betrag}` (a translated placeholder name)
- `checkout.welcome`: `%2$d` became `%1$d`
- `checkout.terms_html`: the `<a>` tag is not closed in the translation
- `checkout.empty` missing, `errors.obsolete` extra

and exits with code 1.

## Tests

```sh
python -m unittest -v test_locale_check
```

32 tests, including the examples in `ejemplos/`.

## Limits

It checks structure, not meaning: a placeholder moved to the wrong part of the sentence, a wrong translation, or a key that the app never uses will not be found. Pluralization rules are not validated against CLDR.

## Want it run on your files?

I also do a fixed-price check of one locale file against its source, with the findings explained: [details and price](https://dev.to/martinpisacreta/a-technical-check-for-your-locale-files-placeholders-tags-and-missing-keys-555b).

Written with the help of AI coding assistants and reviewed and tested by me.

## License

MIT

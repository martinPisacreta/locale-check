#!/usr/bin/env python3
"""Compare JSON/YAML locale files without modifying them. Python 3.11 + PyYAML."""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

import yaml


POSITIONAL = re.compile(r"%(?![{<%])(?!\d+\$)[-+ 0#]?\d*(?:\.\d+)?[sdif]")


def positional(text):
    return POSITIONAL.findall(text.replace("%%", ""))


TAGS = re.compile(r"</?[A-Za-z][^>]*>")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
TAG_PARTS = re.compile(r"<(/?)([A-Za-z][\w-]*)[^>]*?(/?)>")


def nesting_ok(text):
    """True when every non-void tag closes in the reverse order it opened (22/11/2026)."""
    stack = []
    for closing, name, self_closing in TAG_PARTS.findall(text):
        name = name.lower()
        if self_closing or name in VOID:
            continue
        if not closing:
            stack.append(name)
        elif not stack or stack.pop() != name:
            return False
    return not stack


NAMED = re.compile(
    r"%\{[A-Za-z_]\w*\}|%<[A-Za-z_]\w*>[A-Za-z]"
    r"|\{\{\s*[A-Za-z_]\w*\s*\}\}"
    r"|(?<!\{)\{[A-Za-z_]\w*\}(?!\})"
)
NUMBERED = re.compile(r"%\d+\$[-+ 0#]?\d*(?:\.\d+)?[sdif]")
LINK_MARKER = re.compile(r"__(?=\S)(.+?)(?<=\S)__")
LOCALE = re.compile(r"[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*")
PLURALS = {"one", "other", "few", "many", "zero", "two"}
HARD_TYPES = ("missing", "extra", "variables", "html")
LABELS = {
    "missing": "Claves que faltan",
    "extra": "Claves que sobran",
    "variables": "Variables distintas",
    "html": "Etiquetas HTML distintas o mal anidadas",
    "plural_forms": "Formas plurales distintas, revisar",
    "identical": "Sin traducir o intencionales",
}


class InputError(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise InputError("las claves YAML deben ser cadenas entre comillas cuando sea necesario")
            if key in result:
                raise InputError(f"clave YAML duplicada: {key!r}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"clave JSON duplicada: {key!r}")
        result[key] = value
    return result


def load_file(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in {".json", ".yml", ".yaml"}:
        raise InputError(f"{path}: extensión no admitida; use .json, .yml o .yaml")
    try:
        text = path.read_text(encoding="utf-8-sig")
        if suffix == ".json":
            data = json.loads(text, object_pairs_hook=unique_pairs)
        else:
            data = yaml.load(text, Loader=UniqueLoader)
        if not isinstance(data, dict):
            raise InputError("la raíz debe ser un objeto o mapa")
        # Only YAML locale wrappers are removed; JSON namespaces are preserved.
        if suffix != ".json" and len(data) == 1:
            key = next(iter(data))
            if LOCALE.fullmatch(key) and isinstance(data[key], dict):
                data = data[key]
        return data
    except json.JSONDecodeError as exc:
        raise InputError(f"{path}: JSON inválido, línea {exc.lineno}, columna {exc.colno}: {exc.msg}") from None
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f", línea {mark.line + 1}, columna {mark.column + 1}" if mark else ""
        problem = getattr(exc, "problem", None) or "sintaxis no válida"
        raise InputError(f"{path}: YAML inválido{location}: {problem}") from None
    except (OSError, UnicodeError, InputError) as exc:
        raise InputError(f"{path}: {exc}") from None


def flatten(data):
    leaves, groups, active = {}, {}, set()

    def visit(value, parts):
        key = ".".join(parts)
        if isinstance(value, (dict, list)):
            identity = id(value)
            if identity in active:
                raise InputError(f"estructura recursiva en {key!r}")
            active.add(identity)
            try:
                if isinstance(value, dict):
                    if any(not isinstance(k, str) for k in value):
                        raise InputError(f"clave no textual en {key!r}")
                    if value and set(value) <= PLURALS and all(isinstance(v, str) for v in value.values()):
                        groups[key] = set(value)
                    children = value.items()
                else:
                    children = ((str(i), v) for i, v in enumerate(value))
                for child, item in children:
                    visit(item, parts + (child,))
            finally:
                active.remove(identity)
        else:
            if key in leaves:
                raise InputError(f"claves ambiguas al aplanar con puntos: {key!r}")
            leaves[key] = value

    visit(data, ())
    return leaves, groups


def variables(text):
    rest = text.replace("%%", "")
    named = collections.Counter(
        re.sub(r"\s+", "", token) if token.startswith("{{") else token
        for token in NAMED.findall(rest)
    )
    rest = NAMED.sub("", rest)
    numbered = collections.Counter(NUMBERED.findall(rest))
    return named, numbered, positional(rest)


def compare(source, translation):
    src, src_groups = flatten(source)
    dst, dst_groups = flatten(translation)
    findings = {kind: [] for kind in LABELS}

    def add(kind, key, reason):
        findings[kind].append({"key": key, "reason": reason})

    plural_keys = set()
    added_forms = {}  # plural form that only the translation has -> (parent, form)
    for parent in sorted(src_groups.keys() & dst_groups.keys()):
        only_src = src_groups[parent] - dst_groups[parent]
        only_dst = dst_groups[parent] - src_groups[parent]
        if only_src or only_dst:
            for form in only_src | only_dst:
                plural_keys.add(f"{parent}.{form}" if parent else form)
            for form in only_dst:
                added_forms[f"{parent}.{form}" if parent else form] = (parent, form)
            add("plural_forms", parent,
                f"Solo en origen: {', '.join(sorted(only_src)) or 'ninguna'}; "
                f"solo en traducción: {', '.join(sorted(only_dst)) or 'ninguna'}; "
                "revisar las formas requeridas por el idioma de destino.")

    for key in sorted(src.keys() - dst.keys() - plural_keys):
        add("missing", key, "La clave del origen no existe en la traducción.")
    for key in sorted(dst.keys() - src.keys() - plural_keys):
        add("extra", key, "La clave de la traducción no existe en el origen.")
    for key in sorted(src.keys() & dst.keys()):
        original, translated = src[key], dst[key]
        if isinstance(original, str) != isinstance(translated, str):
            add("variables", key, "No se pueden comparar variables: solo uno de los valores es texto.")
            continue
        if not isinstance(original, str):
            continue
        before, after = variables(original), variables(translated)
        reasons = []
        if before[0] != after[0]:
            reasons.append(f"variables con nombre distintas: {dict(before[0])!r} → {dict(after[0])!r}")
        if before[1] != after[1]:
            reasons.append(f"printf numerados distintos: {dict(before[1])!r} → {dict(after[1])!r}")
        if before[2] != after[2]:
            reasons.append(f"printf sin número distintos o fuera de orden: {before[2]!r} → {after[2]!r}")
        # Link markers (__Docs__) are replaced by the app at runtime: the text inside may be translated,
        # but each span has to survive and every "__" needs its pair (Codex audit 23/11 07:53Z).
        spans_before, spans_after = len(LINK_MARKER.findall(original)), len(LINK_MARKER.findall(translated))
        if spans_before != spans_after:
            reasons.append(f"marcadores de enlace __…__ distintos: {spans_before} → {spans_after}")
        if translated.count("__") % 2 and not original.count("__") % 2:
            reasons.append("marcador de enlace __ sin cerrar en la traducción")
        if reasons:
            add("variables", key, "; ".join(reasons))
        html_reasons = []
        # Ruby named printf markers contain angle brackets but are not HTML.
        html_original = NAMED.sub('', original)
        html_translated = NAMED.sub('', translated)
        if collections.Counter(TAGS.findall(html_original)) != collections.Counter(TAGS.findall(html_translated)):
            html_reasons.append("las etiquetas HTML o sus atributos difieren")
        if not nesting_ok(html_original):
            html_reasons.append("HTML mal anidado o sin cerrar en el origen")
        if not nesting_ok(html_translated):
            html_reasons.append("HTML mal anidado o sin cerrar en la traducción")
        if html_reasons:
            add("html", key, "; ".join(html_reasons))
        if original == translated and sum(c.isalpha() for c in original) >= 3:
            add("identical", key, "Texto idéntico al origen; puede ser intencional.")
    # Plural forms that only the target language needs (few, many...) have no source
    # leaf of their own, so their HTML is checked against the source "other" form
    # (or the first shared form) and for nesting (Codex audit 23/11 13:17Z).
    for key in sorted(added_forms):
        translated = dst.get(key)
        if not isinstance(translated, str):
            continue
        parent, _ = added_forms[key]
        reference = None
        for form in ("other", *sorted(src_groups[parent])):
            ref_key = f"{parent}.{form}" if parent else form
            if isinstance(src.get(ref_key), str):
                reference = (form, src[ref_key])
                break
        html_translated = NAMED.sub('', translated)
        html_reasons = []
        if reference is not None:
            html_reference = NAMED.sub('', reference[1])
            if collections.Counter(TAGS.findall(html_reference)) != collections.Counter(TAGS.findall(html_translated)):
                html_reasons.append(f"las etiquetas HTML o sus atributos difieren de la forma «{reference[0]}» del origen")
        if not nesting_ok(html_translated):
            html_reasons.append("HTML mal anidado o sin cerrar en la traducción")
        if html_reasons:
            add("html", key, "; ".join(html_reasons) + " (forma plural que solo tiene la traducción)")
    return {"findings": findings, "summary": {kind: len(items) for kind, items in findings.items()}}


def has_errors(report):
    return any(report["summary"][kind] for kind in HARD_TYPES)


def one_line(value):
    return str(value).replace("\r", r"\r").replace("\n", r"\n")


def render_md(report):
    lines = ["# Informe de archivos de idioma", "",
             "Las formas plurales distintas y los textos idénticos requieren revisión manual.", ""]
    for kind, label in LABELS.items():
        lines.extend([f"## {label}", ""])
        for item in report["findings"][kind]:
            key = json.dumps(item["key"], ensure_ascii=False)
            lines.append(f"- {one_line(key)}: {one_line(item['reason'])}")
        if not report["findings"][kind]:
            lines.append("Sin hallazgos.")
        lines.append("")
    lines.extend(["## Resumen", ""])
    lines.extend(f"- {label}: {report['summary'][kind]}" for kind, label in LABELS.items())
    lines.extend(["", f"Código de salida: {int(has_errors(report))}"])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", metavar="ORIGEN")
    parser.add_argument("translation", metavar="TRADUCCION")
    parser.add_argument("--format", choices=("md", "json"), default="md")
    args = parser.parse_args(argv)
    try:
        report = compare(load_file(args.source), load_file(args.translation))
    except (InputError, RecursionError) as exc:
        message = str(exc) if isinstance(exc, InputError) else "estructura demasiado profunda o recursiva"
        if args.format == "json":
            print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"Error: {one_line(message)}", file=sys.stderr)
        return 2
    report["source"] = args.source
    report["translation"] = args.translation
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.format == "json" else render_md(report))
    return int(has_errors(report))


if __name__ == "__main__":
    # Windows consoles default to a legacy code page; the report has accents, so always write UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())

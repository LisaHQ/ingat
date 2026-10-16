"""Raw-text rules over an app's Compose files (ARCHITECTURE §9.5), for what the merged model never shows: Compose reads
`include` files, fetching remote OCI and git ones during `config`, and `extends` files before the policy sees the model,
and it reads them again at every call. Neither may appear. The rules are conservative: a construct the line rules
cannot read for certain (a document that does not start at column 0, a top-level key Compose does not define, a flow
mapping at the top, a second line-break convention, explicit or alias keys, escaped quoted keys, `!!` tags, an
`extends:` whose value is not on its line or in a block below it) is refused too."""

import re

# Top-level keys Compose defines, without `include`; sequence entries (a top-level key's value); document markers.
TOP = re.compile(
    r"(?:version|name|services|networks|volumes|secrets|configs|x-[A-Za-z0-9._-]*)\s*:(?:\s.*)?|-(?:\s.*)?"
)
MARKER = re.compile(r"(?:---|\.\.\.)\s*(?:#.*)?")
NAME = r"""["']?[A-Za-z0-9._-]+["']?"""
EXTENDS = re.compile(r"""(?:^|(?<=[\s{,\[]))["']?extends["']?\s*:""")
# `extends: <service>` or `extends: {service: <service>}` on its line; else a block of `service: <service>` only.
INLINE = re.compile(rf"""\s*(?:{NAME}|\{{\s*["']?service["']?\s*:\s*{NAME}\s*\}})(?:\s*[,}}\]].*|\s+#.*|\s*)""")
BLOCK = re.compile(rf"""\s+["']?service["']?\s*:\s*{NAME}\s*(?:#.*)?""")
# An explicit key (`? k`), a `!!` or verbatim tag, an alias as a key (`*a :`), an escape in a double-quoted key.
UNREADABLE = re.compile(
    r"""(?:^|[\s{,\[])(?:\?(?:\s|$)|!!|!<|\*[^\s,\[\]{}]+\s*:)|"(?:[^"\\]|\\.)*\\.(?:[^"\\]|\\.)*"\s*:"""
)
# Characters YAML reads as line breaks besides \n and \r, a byte-order mark past the start, other controls.
BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029\ufeff]")
ONLY = "extends may name only a service of the same file"


def errors(name: str, data: bytes) -> list[str]:
    """The refusals for Compose file `name` with content `data`, each naming its line."""
    try:
        text = data.decode().removeprefix("\ufeff")
    except UnicodeDecodeError:
        return [f"{name}: not UTF-8 text"]
    if BAD.search(text):
        return [f"{name}: control characters or Unicode line breaks"]
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, block, empty, start = list[str](), -1, False, True  # block: indentation of an open `extends:` line
    for n, line in enumerate(lines, 1):
        body, at = line.lstrip(" "), f"{name}:{n}"
        indent = len(line) - len(body)
        if not body.strip() or body.startswith("#"):
            continue
        if block >= 0 and indent > block:
            if not BLOCK.fullmatch(line):
                out.append(f"{at}: {ONLY}")
            empty = False
            continue
        if block >= 0 and empty:  # nothing nested below `extends:`: its value follows in flow style
            out.append(f"{at}: {ONLY}")
        block, first, start = -1, start, MARKER.fullmatch(line) is not None
        if start:  # a document marker: the next document's root starts at column 0 too
            continue
        if body.startswith("\t"):
            out.append(f"{at}: a tab in the indentation")
        elif first and indent:  # an indented root would hide its top-level keys from the column-0 rule
            out.append(f"{at}: a document must start at column 0")
        elif indent == 0 and not TOP.fullmatch(line):
            out.append(f"{at}: only the top-level keys version, name, services, networks, volumes, secrets, configs"
                       " and x-* are allowed (include is refused)")  # fmt: skip
        elif UNREADABLE.search(line):
            out.append(f"{at}: explicit or alias keys, escaped quoted keys and !! tags are refused")
        else:
            for m in EXTENDS.finditer(line):  # every key on the line: a flow mapping may hold several
                if not (rest := line[m.end() :].strip()) or rest.startswith("#"):
                    block, empty = indent, True
                elif not INLINE.fullmatch(rest):
                    out.append(f"{at}: {ONLY}")
                    break
    return out

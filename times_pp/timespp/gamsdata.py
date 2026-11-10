# SPDX-License-Identifier: GPL-3.0-or-later
"""Reader for GAMS declaration / data statements (SET, PARAMETER, SCALAR, ALIAS).

Reads the subset of GAMS used by Veda-written DD files and by the TIMES
declaration files (initsys.mod, initmty.mod, *.def).  Executable statements
are skipped; they are ported by hand in the stage modules.

Labels are upper-cased (GAMS is case-insensitive); first-seen casing is kept
in `Reader.casing` for export.
"""
from __future__ import annotations
import re, os
from dataclasses import dataclass, field

DECL_KW = {"SET", "SETS", "PARAMETER", "PARAMETERS", "SCALAR", "SCALARS", "ALIAS", "TABLE"}
SPECIAL = {"EPS": 0.0, "INF": float("inf"), "+INF": float("inf"), "-INF": float("-inf"),
           "NA": float("nan"), "YES": 1.0, "NO": 0.0}
EPS = "EPS"   # marker returned for EPS values
# the records of a data block read from its text, one per line, without its tokens (Reader._tokens_blocks); 0: off
FAST_BLOCKS = os.environ.get("TIMESPP_DD_FAST", "1") != "0"


@dataclass
class Symbol:
    name: str
    kind: str                      # 'set' | 'par'
    domain: list | None = None     # declared domain names (None = unknown yet)
    text: str = ""
    # set: dict[tuple -> text] (ordered); par: dict[tuple -> float | 'EPS']
    data: dict = field(default_factory=dict)
    src: str = ""


def label_range(val):
    """The labels of a range a1*a5 (GAMS: the same text before a number that rises by one): ['a1', ..., 'a5'];
    numbers of the same width keep that width (S-H01*S-H24: S-H01, S-H02, ...). None when val is not such
    a range."""
    m = re.fullmatch(r"(.*?)(\d+)\*(.*?)(\d+)", val)
    if not m or m.group(1).upper() != m.group(3).upper() or not m.group(1):
        return None
    pre, a, b = m.group(1), m.group(2), m.group(4)
    lo, hi = int(a), int(b)
    if hi < lo:
        return None
    if len(a) == len(b):
        return [f"{pre}{k:0{len(a)}d}" for k in range(lo, hi + 1)]
    if a[0] == "0":                                 # a01*a100: widths that do not match
        return None
    return [f"{pre}{k}" for k in range(lo, hi + 1)]


def read_source(path: str) -> str:
    """Text of a GAMS source or DD file. Veda writes UTF-8; GAMS takes the bytes as they are, so names with accents
    (HALL-HÉROULT, SÖDERBERG) must decode to the same labels as the GDX of the GAMS run, which holds
    those UTF-8 bytes. Files that are not valid UTF-8 are read byte for byte as Latin-1 (older Veda versions, hand-written files)."""
    return decode_source(open(path, "rb").read())[0]


def decode_source(raw: bytes):
    """(text, encoding) of the bytes of a source or DD file: UTF-8, or Latin-1 byte for byte (see read_source).
    The encoding is kept: the report writes the texts of the DD files back as GAMS does, in the bytes they came in."""
    try:
        return raw.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


class Reader:
    def __init__(self, env: dict | None = None, include_dirs=()):
        self.env = {k.upper(): v for k, v in (env or {}).items()}
        self.sym: dict[str, Symbol] = {}
        self.alias: dict[str, str] = {}      # alias -> target
        self.casing: dict[str, str] = {}
        self.encodings: set[str] = set()     # of the files read that are not plain ASCII
        self.uel: dict[str, int] = {}        # label -> entry order (universe)
        self.include_dirs = list(include_dirs)
        self.follow_includes = False
        self.oneps = False
        self.dd_applied = []                 # assignments in DD files: (file, statement, records changed)
        self.dd_unsupported = []             # (file, statement, why it is not applied)
        self.run_src = None                  # the name of the run file (read_case): its lines are checked as a DD file's
        self.code_srcs = set()               # files of the model's own GAMS code the run file includes (read_case): read as DD files
        self.user_sets = []                  # (file, name, value) of every $SET in the run file and the DD files
        self._labs = {}                      # label as written -> label (upper case): the labels already met

    # ---------------------------------------------------------------- utils
    def lab(self, s: str) -> str:
        u = self._labs.get(s)
        if u is not None:                    # seen before: its casing and universe entry are there already
            return u
        raw = s
        s = s.strip()
        if len(s) >= 2 and s[0] in "'\"" and s[-1] == s[0]:
            s = s[1:-1]
        s = s.rstrip() if s.strip() else s
        u = s.upper()
        self.casing.setdefault(u, s)
        self.uel.setdefault(u, len(self.uel))
        self._labs[raw] = u
        return u

    def subst(self, line: str) -> str:
        if "%" not in line:
            return line
        def rep(m):
            k = m.group(1).upper()
            return str(self.env[k]) if k in self.env else m.group(0)
        return re.sub(r"%([A-Za-z_][A-Za-z_0-9.]*)%", rep, line)

    # ------------------------------------------------------------ front end
    def read_file(self, path: str):
        text, enc = decode_source(open(path, "rb").read())
        if not text.isascii():
            self.encodings.add(enc)
        self.read_text(text, src=os.path.basename(path))

    # directives with no effect on the data (listing, warnings, comment syntax...): accepted in DD files
    QUIET = {"ONEMPTY", "OFFEMPTY", "ONWARNING", "OFFWARNING", "ONLISTING", "OFFLISTING", "ONMULTI", "OFFMULTI",
             "ONSYMLIST", "OFFSYMLIST", "ONSYMXREF", "OFFSYMXREF", "ONUELLIST", "OFFUELLIST", "ONUELXREF",
             "OFFUELXREF", "TITLE", "STITLE", "ONDIGIT", "OFFDIGIT", "ONUNDF", "OFFUNDF", "EOLCOM", "ONEOLCOM",
             "OFFEOLCOM", "INLINECOM", "ONINLINE", "OFFINLINE", "HIDDEN", "LOG", "ONDOLLAR", "OFFDOLLAR",
             "ONGLOBAL", "OFFGLOBAL", "ONUPPER", "OFFUPPER", "PHANTOM", "LABEL"}

    VEDA_IF = re.compile(r"(?i)IF\s+(?:(?:NOT\s+)?DECLARED\s+REG\s+\$\s*SET\s+STARTRUN\b|NOT\s+DECLARED\s+REG_BNDCST\s+\$\s*ABORT\b)")

    def _directive(self, line: str, src: str):
        s = line.strip()[1:].strip()
        in_run = src == self.run_src
        in_dd = self._is_dd(src) or in_run
        # The $IF lines Veda writes in a run file.  No statement of TIMES reads STARTRUN, and REG_BNDCST is declared in
        # initmty.mod, so the $ABORT is not reached:
        #   $IF DECLARED REG      $SET STARTRUN 'RESTART'
        #   $IF NOT DECLARED REG  $SET STARTRUN 'SCRATCH'
        #   $IF NOT DECLARED REG_BNDCST $Abort ...
        # Any other $IF of a run file may change what GAMS compiles: not evaluated, and refused.
        if in_run and re.match(r"(?i)IF", s):
            if not self.VEDA_IF.match(s):
                self.dd_unsupported.append((src, "$" + s, "a $IF the reader does not evaluate"))
            return
        # chained $IF ... $SET ...
        m = re.match(r"(?i)IFI?\s+NOT\s+SET\s+(\w+)\s+\$?\s*(.*)$", s)
        if m:
            if m.group(1).upper() in self.env:
                return
            s = m.group(2).strip()
        elif re.match(r"(?i)IFI?E?\b", s):
            if in_dd:                                # other conditionals: not evaluated
                self.dd_unsupported.append((src, "$" + s, "a $IF the reader does not evaluate"))
            return
        word = (re.match(r"(\w+)", s) or [None, ""])[1].upper()
        if in_dd and word in self.QUIET:
            return
        if in_dd and not re.match(r"(?i)(ON|OFF)EPS\b|SET(GLOBAL|LOCAL)?\b", s):
            self.dd_unsupported.append((src, "$" + s, "a directive the reader does not execute"))
            return
        if re.match(r"(?i)ONEPS\b", s):
            self.oneps = True
            return
        if re.match(r"(?i)OFFEPS\b", s):
            self.oneps = False
            return
        m = re.match(r"(?i)SET(?:GLOBAL|LOCAL)?\s+(\w+)\s*(.*)$", s)
        if m:
            v = m.group(2).strip()
            rest = ""
            mq = re.match(r"""('[^']*'|"[^"]*")\s*(.*)$""", v)
            if mq:
                v, rest = mq.group(1)[1:-1], mq.group(2)
            self.env[m.group(1).upper()] = self.subst(v)
            if in_dd:
                self.user_sets.append((src, m.group(1).upper(), self.env[m.group(1).upper()]))
            if re.match(r"(?i)SET(GLOBAL|LOCAL)?\b", rest):
                self._directive("$" + rest, src)
            return
        m = re.match(r"(?i)(?:BAT)?INCLUDE\s+(\S+)", s)
        if m and self.follow_includes:
            name = m.group(1).strip("'\"")
            for d in self.include_dirs:
                for cand in (name, name.lower()):
                    p = os.path.join(d, cand)
                    if os.path.isfile(p):
                        self.read_file(p)
                        return

    def _is_dd(self, src):
        """A DD file, or a file of the model's own code included by the run file (read as a DD file is)."""
        return src.lower().endswith(".dd") or src in self.code_srcs

    def read_text(self, text: str, src: str = ""):
        # strip comment lines / $ontext blocks, apply directives, substitute %VAR%
        out, skip = [], False
        for raw in text.splitlines():
            if skip:
                if re.match(r"(?i)\s*\$\s*offtext", raw):
                    skip = False
                continue
            if raw.startswith("*"):
                continue
            st = raw.strip()
            if st.startswith("$"):
                if re.match(r"(?i)\$\s*ontext", st):
                    skip = True
                    continue
                if out:
                    self._statements("\n".join(out), src)
                    out = []
                self._directive(self.subst(raw), src)
                continue
            out.append(self.subst(raw))
        if out:
            self._statements("\n".join(out), src)

    # ------------------------------------------------------------ tokenizer
    TOK = re.compile(r"""[ \t\r]*(?:
          (?P<nl>\n)
        | (?P<q>'[^'\n]*'|"[^"\n]*")
        | (?P<p>[/;,()=])
        | (?P<w>[^\s/;,()='"]+)
        )""", re.X)

    @staticmethod
    def _tok(m, g):
        """The token of match m (group g). A number without its leading zero after a blank ('P1' .4) is a value,
        as GAMS reads it: written 0.4, so that _lex_data does not take it for the end of the key, as it does when it is
        glued to the label ('15'.1 is the key ('15','1'))."""
        v = m.group(g)
        if g == "w" and v[:1] == "." and v[1:2].isdigit() and m.start(g) > m.start():
            return "0" + v
        return v

    def _tokens(self, text):
        # (a character no token starts with is skipped: the search goes on from the next one)
        return [(g, self._tok(m, g)) for m in self.TOK.finditer(text) for g in (m.lastgroup,)]

    BODY_END = re.compile(r"\n[ \t\r]*/")

    def _tokens_blocks(self, text):
        """The tokens of `text`, but the lines after a '/' that ends its line, up to the next line that starts with
        '/', are one token ('B', their text), not tokenised: most likely the records of a data block, one per line,
        which `_parse_body` reads from the text (most of the time of a DD file is there).  Where it cannot, or where
        the token is not the inside of a data block, it is replaced by the tokens of its text (`_expand`): the tokens
        are those of `_tokens` either way.  TIMESPP_DD_FAST=0: no such tokens (every block from its tokens)."""
        if not FAST_BLOCKS:
            return self._tokens(text)
        out, pos, end = [], 0, self.BODY_END.search
        while True:
            for m in self.TOK.finditer(text, pos):
                g = m.lastgroup
                v = self._tok(m, g)
                out.append((g, v))
                if g == "p" and v == "/":
                    e = m.end()
                    k = text.find("\n", e)
                    if k >= 0 and not text[e:k].strip(" \t\r"):
                        c = end(text, k)
                        if c is not None and c.start() > k:
                            out.append(("B", text[e:c.start() + 1]))
                            pos = c.start() + 1
                            break
            else:
                return out

    def _expand(self, toks, i):
        """toks[i], a ('B', text) token, replaced in place by the tokens of its text."""
        toks[i:i + 1] = self._tokens(toks[i][1])

    # ------------------------------------------------------------ statements
    def _statements(self, text: str, src: str):
        toks = self._tokens_blocks(text)
        i, n = 0, len(toks)
        while i < n:
            kind, val = toks[i]
            if kind == "nl":
                i += 1
            elif kind == "w" and val.upper() in DECL_KW:
                i = self._declaration(toks, i, src)
                n = len(toks)
            else:                                   # executable statement, up to ';'
                j = i
                # LOOP(...), IF(...), WHILE(...), FOR(...): the statements inside end with ';' too; up to the ';' after
                # the closing parenthesis
                block = kind == "w" and val.upper() in self.BLOCK_KW
                depth = 0
                while i < n and (toks[i] != ("p", ";") or depth > 0):
                    if toks[i][0] == "B":
                        self._expand(toks, i)
                        n = len(toks)
                        continue
                    if block and toks[i][0] == "p":
                        depth += (toks[i][1] == "(") - (toks[i][1] == ")")
                    i += 1
                if self._is_dd(src):
                    self._dd_statement(toks[j:i], src)
                elif src == self.run_src:
                    self._run_statement(toks[j:i], src)
                i += 1

    BLOCK_KW = {"LOOP", "IF", "WHILE", "FOR", "REPEAT"}

    @staticmethod
    def _text(toks):
        """The text of a statement from its tokens."""
        text = ""
        for kind, val in toks:
            if kind == "nl":
                text += " "
            elif kind == "w" and text and text[-1:].isalnum() and val[:1].isalnum():
                text += " " + val
            else:
                text += val
        return text.strip()

    def _run_statement(self, toks, src):
        """An executable statement of the run file: an OPTION (it sets how GAMS solves and lists; no OPTION a run file has
        changes the LP) is taken, and any other is refused: GAMS would execute it, here it would be lost."""
        text = self._text(toks)
        if text and not re.match(r"(?i)OPTIONS?\b", text):
            self.dd_unsupported.append((src, text, "an executable statement in the run file"))

    def _dd_statement(self, toks, src):
        """An assignment in a DD file (ddexec.py): applied to the data read so far, as GAMS does; a statement of
        another form is kept in dd_unsupported, and the run reports it as unsupported input."""
        from . import ddexec
        text = self._text(toks)
        if not text or re.match(r"(?i)DISPLAY\b", text):          # empty, or a DISPLAY: no effect on the data
            return
        try:
            k = ddexec.apply(self, text)
            self.dd_applied.append((src, text, k))
        except ddexec.Unsupported as e:
            self.dd_unsupported.append((src, text, str(e)))

    def _declaration(self, toks, i, src):
        kw = toks[i][1].upper()
        i += 1
        n = len(toks)
        if kw == "ALIAS":
            names = []
            while i < n and toks[i] != ("p", ")"):
                if toks[i][0] == "B":
                    self._expand(toks, i)
                    n = len(toks)
                    continue
                if toks[i][0] == "w":
                    names.append(toks[i][1].upper())
                i += 1
            i += 1
            while i < n and toks[i][0] == "nl":
                i += 1
            if i < n and toks[i] == ("p", ";"):
                i += 1
            if names:
                self._alias(names)
            return i
        kind = "set" if kw.startswith("SET") else "par"
        scalar = kw.startswith("SCALAR")
        while i < n:
            if toks[i] == ("p", ";"):
                return i + 1
            if toks[i][0] == "w" and toks[i][1].upper() in DECL_KW:
                return i                      # next declaration without ';'
            if toks[i][0] == "B":
                self._expand(toks, i)
                n = len(toks)
                continue
            if toks[i][0] != "w":
                i += 1
                continue
            name = toks[i][1].upper()
            i += 1
            dom = None
            if i < n and toks[i] == ("p", "("):
                dom = []
                i += 1
                while i < n and toks[i] != ("p", ")"):
                    if toks[i][0] == "B":
                        self._expand(toks, i)
                        n = len(toks)
                        continue
                    if toks[i][0] in "wq":
                        dom.append(toks[i][1].upper())
                    i += 1
                i += 1
            text = ""
            if i < n and toks[i][0] == "w" and toks[i][1].upper() not in DECL_KW:
                # an explanatory text without quotes (SET UCX  Names of the constraints /...): the words up to '/', ',',
                # ';' or the end of the line
                words = []
                while i < n and (toks[i][0] in ("w", "q") or (toks[i][0] == "p" and toks[i][1] in "()=")):
                    words.append(toks[i][1])
                    i += 1
                text = " ".join(words)
            while i < n and toks[i][0] == "nl":
                i += 1
            if not text and i < n and toks[i][0] == "q":
                text = toks[i][1][1:-1]
                i += 1
            while i < n and toks[i][0] == "nl":
                i += 1
            if scalar and dom is None:
                dom = []
            # a parameter declared without a domain whose data is one number is a scalar (initmty.mlf: PARAMETER
            # TM_ARBM 'text' /1/); a DD file that names one declared before, without its domain, adds data to it
            bare = kind == "par" and dom is None and name not in self.sym and kw.startswith("PARAMETER")
            s = self._declare(name, kind, dom, text, src)
            if kw == "TABLE":
                return self._table(s, toks, i, src)
            if bare and i < n and toks[i] == ("p", "/"):
                j = i + 1
                body = toks[j][1].split() if j < n and toks[j][0] == "B" else []
                if not body:
                    while j < n and toks[j] != ("p", "/"):
                        if toks[j][0] != "nl":
                            body.append(toks[j][1])
                        j += 1
                if len(body) == 1 and self.NUM.match(body[0]):
                    s.domain, scalar = [], True
            if i < n and toks[i] == ("p", "/"):
                if i + 1 < n and toks[i + 1][0] == "B":
                    # the records, one per line: from the text (_tokens_blocks), else from its tokens
                    items = self._parse_body(s, toks[i + 1][1], scalar)
                    if items is not None:
                        self._data(s, None, scalar, items)
                        i += 3                       # the block, its closing '/'
                        continue
                    self._expand(toks, i + 1)
                    n = len(toks)
                j = i + 1
                while j < n and toks[j] != ("p", "/"):
                    j += 1
                self._data(s, toks[i + 1:j], scalar)
                i = j + 1
        return i

    def _table(self, s, toks, i, src):
        """The body of a TABLE, up to ';': a line of column labels, then one line per row, its label and a value
        under each column.  GAMS places a value under the column whose label it overlaps; read here is the table
        with a value in every column (the header and each row have as many entries), and a label of several
        indexes joined by dots.  A table of another form goes to dd_unsupported."""
        n = len(toks)
        lines, cur = [], []
        while i < n and toks[i] != ("p", ";"):
            if toks[i][0] == "B":
                self._expand(toks, i)
                n = len(toks)
                continue
            if toks[i][0] == "nl":
                if cur:
                    lines.append(cur)
                cur = []
            elif toks[i][0] in "wq":
                cur.append(toks[i][1])
            else:
                lines = []
            i += 1
        if cur:
            lines.append(cur)

        def labels(v):
            return tuple(self.lab(x.strip("'\"")) for x in (v.split(".") if v[:1] not in "'\"" else [v]))
        ok = len(lines) > 1 and all(len(ln) == len(lines[0]) + 1 for ln in lines[1:])
        items = []
        if ok:
            cols = [labels(c) for c in lines[0]]
            for ln in lines[1:]:
                row = labels(ln[0])
                for c, v in zip(cols, ln[1:]):
                    if not (self.NUM.match(v) or v.upper() in ("EPS", "INF", "+INF", "-INF", "NA")):
                        ok = False
                    else:
                        items.append(("k", [row + c], self._num(v), True))
        if ok:
            self._apply_data(s, ("par", items))
        else:
            self.dd_unsupported.append((src, f"TABLE {s.name}", "a table without a value under each column label"))
        return i + 1

    def _alias(self, names):
        tgt = self.alias.get(names[0], names[0])
        for a in names[1:]:
            self.alias[a] = tgt

    def _declare(self, name, kind, dom, text, src):
        s = self.sym.get(name)
        if s is None:
            s = self.sym[name] = Symbol(name, kind, dom, text, src=src)
        elif dom is not None and s.domain is None:
            s.domain = dom
        return s

    # ------------------------------------------------------------------ data
    NUM = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")

    def _lex_data(self, toks):
        """Split word tokens on '.', keeping numbers whole."""
        out = []
        for i, (kind, val) in enumerate(toks):
            if kind != "w":
                out.append((kind, val))
                continue
            # a number-like word is a value, unless it is glued to a quoted label: '15'.1 is the key ('15','1')
            # (the tokenizer has dropped the blanks, so a word that starts with '.' right after a quoted label is
            # read as a continuation of the key; Veda writes values below 1 with a leading zero), and 2030.'CO2-PPM'
            # is the key ('2030','CO2-PPM') (a word that ends with '.' right before a quoted label)
            glued = ((val.startswith(".") and out and out[-1][0] == "q")
                     or (val.endswith(".") and i + 1 < len(toks) and toks[i + 1][0] == "q"))
            if (self.NUM.match(val) and not glued) or val.upper().startswith("SET."):
                out.append(("w", val))
                continue
            segs = val.split(".")
            for k, sg in enumerate(segs):
                if k:
                    out.append(("d", "."))
                if sg:
                    out.append(("w", sg))
        return out

    def _labels(self, tok):
        kind, val = tok
        if kind == "w":
            m = re.fullmatch(r"(\d+)\*(\d+)", val)
            if m:
                return [(self.lab(str(k)),) for k in range(int(m.group(1)), int(m.group(2)) + 1)]
            if "*" in val:
                seq = label_range(val)
                if seq is not None:
                    return [(self.lab(x),) for x in seq]
            elif val[:1] == "#" and len(val) > 1:
                return self._set_members(val[1:])
        return [(self.lab(val),)]

    def _set_members(self, name):
        """#name in a data statement: the members of the set name, in their order (GAMS: all the elements of the
        set, as with the domain notation of a data statement)."""
        s = self.sym.get(self.alias.get(name.upper(), name.upper()))
        if s is None or s.kind != "set":
            raise ValueError(f"#{name}: not a set declared before")
        return list(s.data)

    def _key(self, it, i):
        # the common case first: labels joined by dots, no parentheses, ranges or line breaks inside the key
        n, j, labs = len(it), i, []
        while j < n:
            kind, val = it[j]
            if kind != "q" and (kind != "w" or "*" in val or val[:1] == "#"):
                break
            labs.append(val)
            j += 1
            if j < n and it[j][0] == "d":
                j += 1
                continue
            return [tuple(self.lab(v) for v in labs)], j
        comps, i = self._factor(it, i)
        while i < len(it) and it[i][0] == "d":
            nxt, i = self._factor(it, i + 1)
            comps = [a + b for a in comps for b in nxt]
        return comps, i

    def _factor(self, it, i):
        while i < len(it) and it[i][0] == "nl":
            i += 1
        if i < len(it) and it[i] == ("p", "("):
            alts = []
            i += 1
            while i < len(it) and it[i] != ("p", ")"):
                if it[i] == ("p", ",") or it[i][0] == "nl":
                    i += 1
                    continue
                k, i = self._key(it, i)
                alts.extend(k)
            return alts, i + 1
        if i < len(it) and it[i][0] in "wq":
            return self._labels(it[i]), i + 1
        return [()], i + 1

    def _data(self, s: Symbol, toks, scalar, parsed=None):
        self._apply_data(s, parsed or self._parse_data(s, toks, scalar))

    def _parse_data(self, s: Symbol, toks, scalar):
        """The records of a data block, in order, before they are applied (`_apply_data`): ('scalar', value | None),
        or (kind, items) with items ('ref', set name) for SET.name and ('k', keys, text) for a set /
        ('k', keys, value, a value was written) for a parameter.  The two halves are apart so that the DD files can
        be parsed in other processes and applied here in their order (ddpar.py)."""
        if s.kind == "par" and (scalar or s.domain == []):
            vals = [t for t in toks if t[0] == "w"]
            return ("scalar", self._num(vals[0][1]) if vals else None)
        items = []
        it = self._lex_data(toks)
        i, n = 0, len(it)
        while i < n:
            if it[i] == ("p", ",") or it[i][0] == "nl":
                i += 1
                continue
            if it[i][0] == "w" and it[i][1].upper().startswith("SET."):
                items.append(("ref", it[i][1][4:].upper()))
                i += 1
                continue
            # a number with a dot where a key of more than one label starts is labels: GAMS reads `1.1 0.25` in a
            # two-dimensional parameter as the key ('1','1') (SW_SUBS, SW_SPROB of stochastic TIMES)
            if it[i][0] == "w" and "." in it[i][1] and len(s.domain or ()) > 1 and self.NUM.match(it[i][1])                     and all(sg.isdigit() for sg in it[i][1].split(".")):
                segs = it[i][1].split(".")
                it[i:i + 1] = [t for k, sg in enumerate(segs) for t in ((("d", "."),) if k else ()) + (("w", sg),)]
                n = len(it)
            keys, i = self._key(it, i)
            if s.kind == "set":
                txt = ""
                if i < n and it[i][0] == "q":
                    txt = it[i][1][1:-1]
                    i += 1
                items.append(("k", keys, txt))
            else:
                v, has = 0.0, False
                if i < n and it[i][0] == "w":
                    v, has = self._num(it[i][1]), True
                    i += 1
                items.append(("k", keys, v, has))
        return (s.kind, items)

    # a record as Veda writes it, alone on its line: a key of labels (quoted, or words with no dot or '*') joined by
    # dots, then a value (a word), or for a set the element text (quoted).  A line of another form, or a word the
    # tokens would not give whole as the value, and the block is read from its tokens.  (Possessive: nothing in these
    # lines is matched by giving back what a repeat took, and it is twice as fast.)  BODY_LINE_PLAIN: no dot in a
    # quoted label, the key is split at its dots.
    BODY_LINE = re.compile(r"""[ \t\r]*+((?:'[^'\n]*+'|[^\s/;,()='".*]++)(?:\.(?:'[^'\n]*+'|[^\s/;,()='".*]++))*+)"""
                           r"""(?:[ \t\r]++(?:([^\s/;,()='".][^\s/;,()='"]*+)|('[^'\n]*+'|"[^"\n]*+")))?[ \t\r]*+""")
    BODY_LINE_PLAIN = re.compile(r"""[ \t\r]*+((?:'[^'\n.]*+'|[^\s/;,()='".*]++)(?:\.(?:'[^'\n.]*+'|[^\s/;,()='".*]++))*+)"""
                                 r"""(?:[ \t\r]++(?:([^\s/;,()='".][^\s/;,()='"]*+)|('[^'\n]*+'|"[^"\n]*+")))?[ \t\r]*+""")
    KEY_LABEL = re.compile(r"'[^'\n]*'|[^.']+")

    def _parse_body(self, s: Symbol, body, scalar):
        """`_parse_data` of a data block from its text (a 'B' token of `_tokens_blocks`), when every line is one
        record of the plain form (BODY_LINE) or blank: the same records, the labels met in the same order; else None.
        The records are (kind, (keys, values)): one key per record, and the value (None: none written) or the text;
        lighter than _parse_data's items, to send from a worker process and to apply.
        Their tokens: the labels (q) joined by '.' (w: a dot, or the words and dots between two quoted labels), then
        the value (w) or the text (q), then the line end.  _lex_data splits the words at their dots, except a word
        that starts the key and is a number (2020.5) or SET.name: those lines are left to the tokens; so is a value
        with a dot that is not a number.  A value is _num's: float, or for a word float does not take, _num."""
        if s.kind == "par" and (scalar or s.domain == []):
            return None
        plain, match, labels = self.BODY_LINE_PLAIN.fullmatch, self.BODY_LINE.fullmatch, self.KEY_LABEL.findall
        lab, known, num, isnum = self.lab, self._labs.get, self._num, self.NUM.match
        par = s.kind == "par"
        keys, vals = [], []
        addk, addv = keys.append, vals.append
        for line in body.split("\n"):
            m = plain(line)
            if m is not None:
                key, w, q = m.groups()
                parts = key.split(".")
            else:
                m = match(line)
                if m is None:
                    if line.strip(" \t\r"):
                        return None
                    continue
                key, w, q = m.groups()
                parts = labels(key)
            if key[0] != "'":
                lead = key.split("'", 1)[0]
                if "." in lead and (isnum(lead) or lead[:4].upper() == "SET."):
                    return None
            if "#" in key and any(x[:1] == "#" for x in parts):    # #set: left to the tokens (_labels)
                return None
            addk(tuple([known(x) or lab(x) for x in parts]))
            if par:
                if q is not None:
                    return None
                if w is None:
                    addv(None)
                    continue
                if "." in w and not isnum(w):          # split at its dots by _lex_data
                    return None
                try:
                    addv(float(w))
                except ValueError:
                    addv(num(w))
            else:
                if w is not None:
                    return None
                addv(q[1:-1] if q is not None else "")
        return (s.kind, (keys, vals))

    def _apply_data(self, s: Symbol, parsed):
        kind, items = parsed
        if kind == "scalar":
            if items is not None:
                s.data[()] = items
            return
        data = s.data
        if type(items) is tuple:                       # from _parse_body: one key per record
            if kind == "set":
                for k, txt in zip(*items):
                    if txt or k not in data:
                        data[k] = txt
            else:
                oneps = self.oneps
                for k, v in zip(*items):
                    if v is None:                      # no value written: 0
                        data.pop(k, None)
                    elif v != EPS and v == 0.0:
                        if oneps:
                            data[k] = EPS
                        else:
                            data.pop(k, None)
                    else:
                        data[k] = v
            return
        for it in items:
            if it[0] == "ref":
                ref = self.alias.get(it[1], it[1])
                if ref in self.sym:
                    for k, v in self.sym[ref].data.items():
                        data.setdefault(k, v)
            elif kind == "set":
                txt = it[2]
                for k in it[1]:
                    # A later quote replaces an earlier one. Listing the element again
                    # with no text leaves the text it already has.
                    if txt or k not in data:
                        data[k] = txt
            else:
                v = it[2]
                if it[3] and self.oneps and v == 0.0:
                    v = EPS
                for k in it[1]:
                    if v != EPS and v == 0.0:
                        data.pop(k, None)
                    else:
                        data[k] = v

    def _num(self, t: str):
        u = t.upper()
        if u == "EPS":
            return EPS
        if u in SPECIAL:
            return SPECIAL[u]
        return float(t)

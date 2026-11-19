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
# A label without quotes holds letters, digits, '_', '+' and '-' (and '.' between the labels of a key, '*' in a range,
# '#' before a set name): GAMS refuses `A!B`, `A#B`, `A{B`, ... ("Blank needed between element and text").  Such a
# word in the key of a record is most likely a comment the input meant (a comment switch GAMS was given and the reader
# was not), so it is an error here too, not a label.
BAD_LABEL = re.compile(r"""[!#{}@&$%?~^|<>\[\]`\\]""")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


class InputError(Exception):
    """A line of the input the reader cannot read: the file, the line number, the line's text and what was expected."""

    def __init__(self, src, line, text, what):
        self.src, self.line, self.text, self.what = src, line, text, what
        t = (text or "").strip()
        super().__init__(f"{src}, line {line}: {what}" + (f":  {t[:120]}" if t else ""))


class _Bad(Exception):
    """Inside the parse of a statement: what was expected, and the line breaks before it from a point the caller knows."""

    def __init__(self, what, off=0):
        super().__init__(what)
        self.what, self.off = what, off


class Comments:
    """What GAMS skips as comment text, as the dollar control options set it.  GAMS 54, with the default of each:
      $EOLCOM cc / $ONEOLCOM / $OFFEOLCOM      end-of-line comments: '!!', off
      $INLINECOM a b / $ONINLINE / $OFFINLINE  in-line comments, over several lines too: '/*' '*/', off
      $ONNESTCOM / $OFFNESTCOM                 in-line comments inside in-line comments: off
      $COMMENT c                               the character of a comment line in column 1: '*'
      $ONGLOBAL / $OFFGLOBAL                   whether what an included file sets holds after it returns: off
    ($EOLCOM and $INLINECOM switch their comments on; $OFF... keeps the characters for a later $ON....)"""
    __slots__ = ("eol", "eol_on", "inl", "inl_on", "nest", "char", "glob")

    def __init__(self, state=None):
        self.load(state or ("!!", False, ("/*", "*/"), False, False, "*", False))

    def state(self):
        return (self.eol, self.eol_on, self.inl, self.inl_on, self.nest, self.char, self.glob)

    def load(self, state):
        self.eol, self.eol_on, self.inl, self.inl_on, self.nest, self.char, self.glob = state
        self.inl = tuple(self.inl)

    @property
    def plain(self):
        """No end-of-line or in-line comments on: a line is read as it stands."""
        return not (self.eol_on or self.inl_on)


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


def dollar_lines(text):
    """The dollar control lines of a run file as GAMS reads them, in order: its comments taken out (`*` lines,
    $ONTEXT blocks, end-of-line and in-line comments as the file switches them on and off), each from its first
    option that is not a comment option ("$" + the rest; `$ONEOLCOM` alone gives nothing). Nothing is read and no
    include is followed: what a program needs that looks for the DD files and the switches of a run file."""
    got = []

    class _Lines(Reader):
        def _dollar(self, s, src):
            got.append("$" + s)

        def _statements(self, text, src, line0=1):
            pass

        def _refuse(self, src, text, why, line=None):
            pass

    _Lines().read_text(text, src="run")
    return got


class _Lead0(str):
    """A word written '.<digits>' after a blank, given its leading zero by the tokenizer ('P1' .4 is 0.4): a value,
    or, where a key has fewer labels than its domain, the next label (`AT .CO2_BND .0`: the label 0)."""
    __slots__ = ()


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
        # GAMS enters every data statement at compile time and runs the assignments afterwards, in order: a statement
        # sees the data of every file, also of those read after it.  read_case sets `deferred` to a list: the
        # statements of the DD files and the run file are kept there, and run_statements() runs them when all is read
        # (None: each is applied where it stands, on the data read so far)
        self.deferred = None
        self.driver_seen = False             # the run file has included TIMES's driver (a statement after it runs
                                             # after the solve: refused)
        self.run_src = None                  # the name of the run file (read_case): its lines are checked as a DD file's
        self.code_srcs = set()               # files of the model's own GAMS code the run file includes (read_case): read as DD files
        self.user_sets = []                  # (file, name, value) of every $SET in the run file and the DD files
        self._labs = {}                      # label as written -> label (upper case): the labels already met
        self.cm = Comments()                 # the comment switches in force (the run file's, while it is read)
        self.on_include = None               # load.read_case: called with an $INCLUDE line of the run file
        self._lines = []                     # the lines of the file being read (for the messages)
        self._strict = False                 # a DD file or the run file: labels and names are checked as GAMS does
        self._line = 0                       # the line of the directive being done
        self._line0 = 1                      # the line of the file where the text given to _statements starts
        self._stmt = None                    # (toks, index) of the executable statement being done
        self._nlc = None                     # (toks, index, line breaks before it): _nls

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

    # Options with no effect on the records read (GAMS 54: the same data read with and without each): the listing
    # ($ONLISTING, $TITLE, $STITLE, $DOUBLE, $SINGLE, $EJECT, $LINES, $STARS, $REMARK, $ONINCLUDE, $ONVERBATIM, $ONSYMLIST,
    # $ONSYMXREF, $ONUELLIST, $ONUELXREF, $ONDOLLAR, $ONUPPER, $ONMARGIN without $MINCOL/$MAXCOL), the log ($LOG), checks
    # ($ONWARNING, $ONORDER, $ONDIGIT, $ONUNDF: a value UNDF is then an error here, a word where a number is due),
    # $ONEMPTY (an empty block is read as one), $ONMULTI (a second data statement of a symbol is merged into the first,
    # as here), and $LABEL (only the target of a $GOTO, which is refused).  The value: the words after the option that
    # are its arguments (-1: the rest of the line).
    QUIET = {**dict.fromkeys(("ONEMPTY", "OFFEMPTY", "ONWARNING", "OFFWARNING", "ONLISTING", "OFFLISTING", "ONMULTI",
                              "OFFMULTI", "ONSYMLIST", "OFFSYMLIST", "ONSYMXREF", "OFFSYMXREF", "ONUELLIST",
                              "OFFUELLIST", "ONUELXREF", "OFFUELXREF", "ONDIGIT", "OFFDIGIT", "ONUNDF", "OFFUNDF",
                              "ONDOLLAR", "OFFDOLLAR", "ONUPPER", "OFFUPPER", "DOUBLE", "SINGLE", "EJECT", "ONINCLUDE",
                              "OFFINCLUDE", "ONVERBATIM", "OFFVERBATIM", "ONORDER", "OFFORDER", "ONMARGIN",
                              "OFFMARGIN"), 0),
             "LINES": 1, "STARS": 1, "LABEL": 1, "TITLE": -1, "STITLE": -1, "LOG": -1, "REMARK": -1}
    # options that change what is read and are not done here: refused, with why
    REFUSED = {"DOLLAR": "it changes the character of the dollar control options",
               "MINCOL": "text outside the margins is a comment in GAMS; margins are not read here",
               "MAXCOL": "text outside the margins is a comment in GAMS; margins are not read here",
               "ONDELIM": "data in delimited form is not read here",
               "PHANTOM": "a phantom label is left out of the data by GAMS; not done here"}
    WORD = re.compile(r"([A-Za-z]\w*)\s*")
    INCLUDE = re.compile(r"(?i)(?:BAT)?INCLUDE\s+\S")

    VEDA_IF = re.compile(r"(?i)IF\s+(?:(?:NOT\s+)?DECLARED\s+REG\s+\$\s*SET\s+STARTRUN\b|NOT\s+DECLARED\s+REG_BNDCST\s+\$\s*ABORT\b)")

    def _refuse(self, src, text, why, line=None):
        """An input that is not read here (the run ends UNSUPPORTED, naming it): its file and line, its text, why."""
        n = line if line is not None else self._line
        self.dd_unsupported.append((f"{src}, line {n}," if n else src, text, why))

    def _directive(self, line: str, src: str):
        """A dollar control line.  GAMS does each option on it in turn (`$ONEPS ONEOLCOM`, `$INLINECOM { } ONNESTCOM`
        are two options; an unknown word is an error): the options of comments, of EPS and of the scope of an include,
        and the options with no effect on the data, are done here; the first other word and the rest of the line go
        to _dollar ($SET, $IF, $INCLUDE, ... or refused)."""
        s = line.strip()[1:].strip()
        rest = s
        while rest:
            m = self.WORD.match(rest)
            if m is None:
                break
            w, args = m.group(1).upper(), rest[m.end():]
            k = self.QUIET.get(w)
            if k is not None:
                if k < 0:
                    return
                parts = args.split(None, k)
                rest = parts[k] if len(parts) > k else ""
                continue
            h = self._OPTS.get(w)
            if h is None:
                break
            rest = h(self, args, src)
            if rest is None:
                return
            rest = rest.strip()
        if rest:
            self._dollar(rest, src)

    def _line_level(self, line):
        """Is every option of this line one of the comment options, $HIDDEN or an option with no effect on the data?
        Those act on the lines that follow and on nothing read before: inside a data block (GAMS reads
        `$HIDDEN ...` or `$ONEOLCOM` between two records), the block goes on."""
        rest = line.strip()[1:].strip()
        while rest:
            m = self.WORD.match(rest)
            if m is None:
                return False
            w, args = m.group(1).upper(), rest[m.end():]
            k = self.QUIET.get(w)
            if k is None:
                if w not in self._OPTS or w in ("ONEPS", "OFFEPS"):
                    return False
                if w in ("HIDDEN",):
                    return True
                k = {"EOLCOM": 1, "INLINECOM": 2, "COMMENT": 1}.get(w, 0)
            if k < 0:
                return True
            parts = args.split(None, k)
            rest = parts[k].strip() if len(parts) > k else ""
        return True

    # The options of comments (class Comments), $ONEPS / $OFFEPS and $ONGLOBAL / $OFFGLOBAL: each takes the text after
    # its name and gives back what follows its arguments (None: the rest of the line is done).
    def _o_set(attr, val):
        def f(self, args, src):
            setattr(self.cm, attr, val)
            return args
        return f

    def _o_eps(val):
        def f(self, args, src):
            self.oneps = val
            return args
        return f

    def _o_eolcom(self, args, src):
        # GAMS: "$eolCom char[char]" ... "It is not allowed to reset the end-of-line comment symbol to the current
        # end-of-line comment symbol" (an error while they are on; after $OFFEOLCOM, $EOLCOM !! is taken)
        parts = args.split(None, 1)
        c = parts[0] if parts else ""
        if not 1 <= len(c) <= 2 or (self.cm.eol_on and c == self.cm.eol):
            self._refuse(src, ("$EOLCOM " + c).strip(), "end-of-line comment characters GAMS does not take "
                         "(one or two characters, not those in force)")
            return None
        self.cm.eol, self.cm.eol_on = c, True
        return parts[1] if len(parts) > 1 else ""

    def _o_inlinecom(self, args, src):
        # GAMS: "$inlineCom char[char] char[char]" ... "It is not allowed to reset the option $inlineCom to the
        # current symbol"
        parts = args.split(None, 2)
        pair = tuple(parts[:2])
        if len(pair) < 2 or not all(1 <= len(c) <= 2 for c in pair) or (self.cm.inl_on and pair == self.cm.inl):
            self._refuse(src, ("$INLINECOM " + " ".join(pair)).strip(), "in-line comment characters GAMS does not "
                         "take (two of one or two characters, not those in force)")
            return None
        self.cm.inl, self.cm.inl_on = pair, True
        return parts[2] if len(parts) > 2 else ""

    def _o_comment(self, args, src):
        # GAMS: "$comment char": the character of a comment line in column 1 (GAMS 54 compares it with its case)
        parts = args.split(None, 1)
        c = parts[0] if parts else ""
        if len(c) != 1:
            self._refuse(src, ("$COMMENT " + c).strip(), "a comment character GAMS does not take (one character)")
            return None
        self.cm.char = c
        return parts[1] if len(parts) > 1 else ""

    def _o_hidden(self, args, src):
        return None                          # GAMS: "A line starting with this option will be ignored"

    _OPTS = {"ONEOLCOM": _o_set("eol_on", True), "OFFEOLCOM": _o_set("eol_on", False), "EOLCOM": _o_eolcom,
             "ONINLINE": _o_set("inl_on", True), "OFFINLINE": _o_set("inl_on", False), "INLINECOM": _o_inlinecom,
             "ONNESTCOM": _o_set("nest", True), "OFFNESTCOM": _o_set("nest", False), "COMMENT": _o_comment,
             "ONGLOBAL": _o_set("glob", True), "OFFGLOBAL": _o_set("glob", False), "HIDDEN": _o_hidden,
             "ONEPS": _o_eps(True), "OFFEPS": _o_eps(False)}
    del _o_set, _o_eps

    def _dollar(self, s: str, src: str):
        """A dollar control option other than those of _directive (s: the text after the '$')."""
        in_run = src == self.run_src
        in_dd = self._is_dd(src) or in_run
        # the $INCLUDE and $BATINCLUDE lines of the run file: load.read_case reads the file they name
        if in_run and self.on_include is not None and self.INCLUDE.match(s):
            self.on_include("$" + s)
            return
        # The $IF lines Veda writes in a run file.  No statement of TIMES reads STARTRUN, and REG_BNDCST is declared in
        # initmty.mod, so the $ABORT is not reached:
        #   $IF DECLARED REG      $SET STARTRUN 'RESTART'
        #   $IF NOT DECLARED REG  $SET STARTRUN 'SCRATCH'
        #   $IF NOT DECLARED REG_BNDCST $Abort ...
        # Any other $IF of a run file may change what GAMS compiles: not evaluated, and refused.
        if in_run and re.match(r"(?i)IF", s):
            if not self.VEDA_IF.match(s):
                self._refuse(src, "$" + s, "a $IF the reader does not evaluate")
            return
        # chained $IF ... $SET ...
        m = re.match(r"(?i)IFI?\s+NOT\s+SET\s+(\w+)\s+\$?\s*(.*)$", s)
        if m:
            if m.group(1).upper() in self.env:
                return
            self._directive("$" + m.group(2).strip(), src)
            return
        elif re.match(r"(?i)IFI?E?\b", s):
            if in_dd:                                # other conditionals: not evaluated
                self._refuse(src, "$" + s, "a $IF the reader does not evaluate")
            return
        word = (re.match(r"(\w+)", s) or [None, ""])[1].upper()
        if in_dd and not re.match(r"(?i)SET(GLOBAL|LOCAL)?\b", s):
            self._refuse(src, "$" + s, self.REFUSED.get(word, "a directive the reader does not execute"))
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

    ONTEXT = re.compile(r"(?i)\$\s*ontext\b")
    OFFTEXT = re.compile(r"(?i)\$\s*offtext\b")

    def read_text(self, text: str, src: str = ""):
        """The statements and dollar control options of a file, its comments taken out as GAMS does (class Comments),
        %name% substituted after.  On each line, in this order (GAMS 54):
          - in a $ONTEXT block: nothing but a $OFFTEXT with its '$' in column 1 (a '$OFFTEXT' after blanks is text);
          - in an in-line comment open from a line before: comment text up to its close (a '*' in column 1, a '$' line,
            '$ONTEXT' there are comment text too); what follows the close is read;
          - the comment character in column 1 ('*', or that of $COMMENT): a comment line, whatever follows;
          - '$' in column 1: dollar control options, their comments taken out first (`$SET V FR !! c` sets FR);
          - else statements: end-of-line and in-line comments taken out (`_scan`).
        A line taken out leaves an empty line, so that the lines of a text handed to _statements are those of the
        file.  A '$' after blanks is not an option in GAMS (an error there): refused in a DD file and the run file.
        A Ctrl-Z (\\x1a, the DOS end-of-file mark some editors leave) ends the file, as in GAMS: what follows is not
        read."""
        z = text.find("\x1a")
        if z >= 0:
            text = text[:z]
        lines = text.splitlines()
        keep = self._lines, self._strict
        self._lines = lines
        strict = self._strict = self._is_dd(src) or src == self.run_src
        cm, subst, scan = self.cm, self.subst, self._scan
        plain = cm.plain
        out, start, skip, depth = [], 1, 0, 0
        try:
            for n, raw in enumerate(lines, 1):
                if skip:
                    if raw[:1] == "$" and self.OFFTEXT.match(raw):
                        skip = 0
                    out.append("")
                    continue
                if depth:
                    t, depth = scan(raw, depth)
                    out.append(subst(t))
                    continue
                c0 = raw[:1]
                if c0 == cm.char:
                    out.append("")
                    continue
                if c0 == "$" or ("$" in raw and raw.lstrip()[:1] == "$"):
                    t = raw
                    if not plain:
                        t, depth = scan(raw, 0)
                    if c0 != "$" and strict:
                        self._refuse(src, raw.strip(), "a '$' after blanks: GAMS reads dollar control options only "
                                     "with the '$' in column 1", n)
                        out.append("")
                        continue
                    if self.ONTEXT.match(t.lstrip()):
                        skip = n
                        out.append("")
                        continue
                    self._line = n
                    if self._line_level(t):          # a comment option, $HIDDEN, ...: the statement goes on
                        self._directive(subst(t), src)
                        out.append("")
                        cm = self.cm
                        plain = cm.plain
                        continue
                    if out:
                        self._statements("\n".join(out), src, start)
                        out = []
                    start = n + 1
                    self._directive(subst(t), src)
                    cm = self.cm
                    plain = cm.plain
                    continue
                if plain:
                    out.append(subst(raw))
                else:
                    t, depth = scan(raw, 0)
                    out.append(subst(t))
            # a comment open at the end of the file is named first (the statement it cuts short would be named next)
            if strict and skip:
                self._refuse(src, "$ONTEXT", "a $ONTEXT without its $OFFTEXT in the file (GAMS stops)", skip)
            if strict and depth:
                self._refuse(src, cm.inl[0], "an in-line comment still open at the end of the file (GAMS stops)",
                             len(lines))
            if out:
                self._statements("\n".join(out), src, start)
        finally:
            self._lines, self._strict = keep

    def _scan(self, line, depth):
        """(the line without its comments, the depth of the in-line comment open at its end).  Left to right: a quote
        (' or ") runs to the same quote or to the end of the line, and comment characters inside it are text; the
        end-of-line characters end the line; the in-line characters open a comment (inside one, with $ONNESTCOM, open
        another), which counts as blanks of its width (GAMS: `5/* c */0` is two numbers, `A/* c */B` the element A with
        the text B).  Comment characters are found inside a word too (`A!!B` is A)."""
        cm = self.cm
        eol = cm.eol if cm.eol_on else None
        op, cl = cm.inl
        inl = cm.inl_on
        if not depth and (eol is None or eol not in line) and (not inl or op not in line):
            return line, 0
        nest = cm.nest
        out, i, n, seg = [], 0, len(line), 0
        while i < n:
            if depth:
                if nest and line.startswith(op, i):
                    depth += 1
                    i += len(op)
                elif line.startswith(cl, i):
                    depth -= 1
                    i += len(cl)
                    if not depth:
                        out.append(" " * (i - seg))
                        seg = i
                else:
                    i += 1
                continue
            ch = line[i]
            if ch == "'" or ch == '"':
                j = line.find(ch, i + 1)
                i = n if j < 0 else j + 1
            elif eol is not None and line.startswith(eol, i):
                out.append(line[seg:i])
                return "".join(out), 0
            elif inl and line.startswith(op, i):
                out.append(line[seg:i])
                seg, depth = i, 1
                i += len(op)
            else:
                i += 1
        if not depth:
            out.append(line[seg:])
        return "".join(out), depth

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
            return _Lead0("0" + v)
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
    def _statements(self, text: str, src: str, line0: int = 1):
        """The statements of `text`, which starts at line `line0` of the file `src`.  A record or statement that cannot
        be read is an InputError naming the file and the line."""
        toks = self._tokens_blocks(text)
        self._line0, self._nlc = line0, None
        i, n, j = 0, len(toks), 0
        try:
            while i < n:
                kind, val = toks[i]
                j = i
                if kind == "nl":
                    i += 1
                elif kind == "w" and val.upper() in DECL_KW:
                    i = self._declaration(toks, i, src)
                    n = len(toks)
                else:                                   # executable statement, up to ';'
                    # LOOP(...), IF(...), WHILE(...), FOR(...): the statements inside end with ';' too; up to the ';'
                    # after the closing parenthesis
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
                    self._stmt = (toks, j)
                    if self._is_dd(src):
                        self._dd_statement(toks[j:i], src)
                    elif src == self.run_src:
                        self._run_statement(toks[j:i], src)
                    i += 1
        except _Bad as e:
            self._fail(src, line0 + e.off, e.what)
        except ValueError as e:                     # (raised where the line is not known: the statement's first)
            self._fail(src, line0 + self._nls(toks, j), str(e))

    def _fail(self, src, line, what):
        lines = self._lines
        if self.dd_unsupported:                     # (most likely the cause: a directive not read)
            f, text, why = self.dd_unsupported[-1]
            what += f" (before it, refused: {f.rstrip(',')}: {text[:60]}: {why})"
        raise InputError(src, line, lines[line - 1] if 0 < line <= len(lines) else "", what)

    def _nls(self, toks, j):
        """The line breaks before toks[j] (a 'B' token holds its own).  Counted on from the last count of the same
        tokens: the statements of a text are taken in order, and a token list only changes after the point reached."""
        c = self._nlc
        k, cnt = (c[1], c[2]) if c is not None and c[0] is toks and c[1] <= j else (0, 0)
        for kind, val in toks[k:j]:
            if kind == "nl":
                cnt += 1
            elif kind == "B":
                cnt += val.count("\n")
        self._nlc = (toks, j, cnt)
        return cnt

    def _nd(self, s):
        """The number of labels a key of `s` has, when its domain was declared (0 when it is not known here)."""
        return len(s.domain) if s.domain else 0

    def _stmt_line(self):
        """The line of the file where the executable statement being done starts."""
        toks, j = self._stmt
        return self._line0 + self._nls(toks, j)

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
        changes the LP) is taken; an assignment before TIMES's driver is run as a DD file's is (ddexec.py), in its
        place among them, when the statements are deferred (read_case); any other is refused: GAMS would execute it,
        here it would be lost."""
        text = self._text(toks)
        if not text or re.match(r"(?i)OPTIONS?\b", text):
            return
        if self.deferred is None or self.driver_seen:
            self._refuse(src, text, "an executable statement in the run file" +
                         (" after the driver of TIMES" if self.driver_seen else ""), self._stmt_line())
            return
        self._dd_statement(toks, src)

    def _dd_statement(self, toks, src, line=None):
        """An assignment in a DD file (ddexec.py), as GAMS does it: run after every file is read, in order, when the
        statements are deferred (read_case), else applied to the data read so far; a statement of another form is
        kept in dd_unsupported, and the run reports it as unsupported input (line: where it starts, when it was
        parsed in another process, ddpar.py)."""
        text = self._text(toks)
        if not text or re.match(r"(?i)DISPLAY\b", text):          # empty, or a DISPLAY: no effect on the data
            return
        line = line if line is not None else self._stmt_line()
        if self.deferred is not None:
            for kind, val in toks:                  # GAMS enters a quoted label where it stands (compile time)
                if kind == "q":
                    self.lab(val)
            self.deferred.append((src, text, line))
            return
        self._exec_statement(src, text, line)

    def _exec_statement(self, src, text, line):
        from . import ddexec
        try:
            k = ddexec.apply(self, text)
            self.dd_applied.append((src, text, k))
        except ddexec.Unsupported as e:
            self._refuse(src, text, str(e), line)

    def run_statements(self):
        """Run the deferred statements, in order, on the data of every file read (GAMS: execution after compilation)."""
        todo, self.deferred = self.deferred or [], None
        for src, text, line in todo:
            self._exec_statement(src, text, line)

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
            if self._strict and not NAME.match(toks[i][1]):
                raise _Bad(f"the name of a set or parameter where '{toks[i][1]}' stands", self._nls(toks, i))
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
                if j >= n:                           # GAMS reads on into what follows the file, and stops there
                    raise _Bad(f"the '/' that ends the data of {s.name} (the file ends inside it)", self._nls(toks, i))
                try:
                    self._data(s, toks[i + 1:j], scalar)
                except _Bad as e:                    # its line breaks counted from the '/' of the block
                    e.off += self._nls(toks, i + 1)
                    raise
                i = j + 1
        return i

    def _table(self, s, toks, i, src):
        line = self._line0 + self._nls(toks, i)
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
            self._refuse(src, f"TABLE {s.name}", "a table without a value under each column label", line)
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
            if kind == "w" and self._strict and BAD_LABEL.search(val):
                self._bad_label(val, it, j)
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
            v = it[i][1]
            if it[i][0] == "w" and self._strict and BAD_LABEL.search(v[1:] if v[:1] == "#" else v):
                self._bad_label(v, it, i)
            return self._labels(it[i]), i + 1
        return [()], i + 1

    def _bad_label(self, val, it, i):
        raise _Bad(f"a label where '{val}' stands (GAMS takes letters, digits, '_', '+' and '-' in a label without "
                   "quotes; a comment the files do not switch on?)", sum(1 for t in it[:i] if t[0] == "nl"))

    def _data(self, s: Symbol, toks, scalar, parsed=None):
        self._apply_data(s, parsed or self._parse_data(s, toks, scalar))

    def _parse_data(self, s: Symbol, toks, scalar):
        """The records of a data block, in order, before they are applied (`_apply_data`): ('scalar', value | None),
        or (kind, items) with items ('ref', set name) for SET.name and ('k', keys, text) for a set /
        ('k', keys, value, a value was written) for a parameter.  The two halves are apart so that the DD files can
        be parsed in other processes and applied here in their order (ddpar.py)."""
        if s.kind == "par" and (scalar or s.domain == []):
            for k, t in enumerate(toks):
                if t[0] == "w":
                    return ("scalar", self._value(t[1], toks, k))
            return ("scalar", None)
        items = []
        it = self._lex_data(toks)
        i, n = 0, len(it)
        st = self._strict                   # a DD file or the run file: GAMS's rules on what follows a key
        nd = self._nd(s) if st else 0       # GAMS: a key of another length is an error
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
            i0 = i
            try:
                keys, i = self._key(it, i)
                # GAMS: `AT .CO2_BND .0` - a '.' and digits after a blank go on with the key while it has fewer
                # labels than the domain (`.0` is the label 0), and are a value once it has them all (`'R1' .5`)
                while (i < n and it[i][0] == "w" and type(it[i][1]) is _Lead0 and it[i][1][2:].isdigit()
                       and s.domain and len(keys[0]) < len(s.domain)):
                    it[i:i + 1] = [("d", "."), ("w", it[i][1][2:])]
                    n = len(it)
                    keys, i = self._key(it, i0)
            except ValueError as e:
                raise _Bad(str(e), sum(1 for t in it[:i] if t[0] == "nl")) from None
            if nd and any(len(k) != nd for k in keys):
                raise _Bad(f"a key of {nd} label{'s' if nd > 1 else ''} ({s.name} is declared over "
                           f"{', '.join(s.domain)}), not '{'.'.join(keys[0])}'", sum(1 for t in it[:i] if t[0] == "nl"))
            if s.kind == "set":
                txt = ""
                if i < n and it[i][0] == "q" and (not st or i + 1 >= n or it[i + 1][0] == "nl" or it[i + 1] == ("p", ",")):
                    txt = it[i][1][1:-1]
                    i += 1
                elif st and i < n and it[i][0] in "wqd":
                    # GAMS: the words after an element, up to ',' or the end of the line, are its text (`A some text`;
                    # a quote inside is kept).  Read here from the tokens: blanks between the words are one blank.
                    parts = []
                    while i < n and it[i][0] in "wqd":
                        if parts and it[i][0] != "d" and parts[-1] != ".":
                            parts.append(" ")
                        parts.append(it[i][1])
                        i += 1
                    txt = "".join(parts)
                items.append(("k", keys, txt))
            else:
                v, has = 0.0, False
                j = i
                while st and j < n and it[j][0] == "nl":    # GAMS: the value may stand on the next line
                    j += 1
                if j < n and it[j][0] == "w":
                    v, has = self._value(it[j][1], it, j), True
                    i = j + 1
                elif st:
                    raise _Bad(f"a value for the record {'.'.join(keys[0])}", sum(1 for t in it[:i] if t[0] == "nl"))
                if st and i < n and it[i][0] != "nl" and it[i] != ("p", ","):
                    raise _Bad(f"the end of the record after its value, not '{it[i][1]}'",
                               sum(1 for t in it[:i] if t[0] == "nl"))
                items.append(("k", keys, v, has))
        return (s.kind, items)

    # a record as Veda writes it, alone on its line: a key of labels (quoted, or words with no dot or '*') joined by
    # dots, then a value (a word), or for a set the element text (quoted).  A line of another form, or a word the
    # tokens would not give whole as the value, and the block is read from its tokens.  (Possessive: nothing in these
    # lines is matched by giving back what a repeat took, and it is twice as fast.)  BODY_LINE_PLAIN: no dot in a
    # quoted label, the key is split at its dots.
    BODY_LINE = re.compile(r"""[ \t\r]*+((?:'[^'\n]*+'|[^\s/;,()='".*!#{}@&$%?~^|<>\[\]`\\]++)(?:\.(?:'[^'\n]*+'|[^\s/;,()='".*!#{}@&$%?~^|<>\[\]`\\]++))*+)"""
                           r"""(?:[ \t\r]++(?:([^\s/;,()='".][^\s/;,()='"]*+)|('[^'\n]*+'|"[^"\n]*+")))?[ \t\r]*+""")
    BODY_LINE_PLAIN = re.compile(r"""[ \t\r]*+((?:'[^'\n.]*+'|[^\s/;,()='".*!#{}@&$%?~^|<>\[\]`\\]++)(?:\.(?:'[^'\n.]*+'|[^\s/;,()='".*!#{}@&$%?~^|<>\[\]`\\]++))*+)"""
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
        strict = self._strict
        nd = self._nd(s) if strict else 0
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
            if nd and len(parts) != nd:                # not a record GAMS reads: from the tokens, which name it
                return None
            addk(tuple([known(x) or lab(x) for x in parts]))
            if par:
                if q is not None:
                    return None
                if w is None:
                    if strict:                         # GAMS: no value is an error (or it is on the next line)
                        return None
                    addv(None)
                    continue
                if "." in w and not isnum(w):          # split at its dots by _lex_data
                    return None
                try:
                    addv(float(w))
                except ValueError:
                    try:
                        addv(num(w))
                    except ValueError:               # read from the tokens, which name the line
                        return None
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

    def _value(self, w, toks, i):
        """_num of the word w, toks[i]: a record's value.  A word that is not a value is an error of the input, on the
        line of the record."""
        try:
            return self._num(w)
        except ValueError:
            raise _Bad(f"a value (a number, EPS, INF or NA) where '{w}' stands",
                       sum(1 for t in toks[:i] if t[0] == "nl")) from None

    def _num(self, t: str):
        u = t.upper()
        if u == "EPS":
            return EPS
        if u in SPECIAL:
            return SPECIAL[u]
        return float(t)

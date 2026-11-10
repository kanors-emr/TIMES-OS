# SPDX-License-Identifier: GPL-3.0-or-later
"""Assignment statements in DD files.

Veda models sometimes end a DD file with GAMS assignments that clean up the data read so far, e.g. (from a model's
zz_modelfix.dd):

    ACT_BND(R,DATAYEAR,P,S,BD)$((ACT_BND(R,DATAYEAR,P,S,BD)<3E-5)$ACT_BND(R,DATAYEAR,P,S,BD)) = EPS;
    UC_COMPRD(UC_N('TUC_UP_IOIHET-INDCO'),SIDE,R,DATAYEAR,C,S)$((ABS(UC_COMPRD(UC_N,SIDE,R,DATAYEAR,C,S))<1E-4)
        $UC_COMPRD(UC_N,SIDE,R,DATAYEAR,C,S)) = -1E-4;

GAMS executes them where they stand, on the data read before them. This module applies the form

    SYM(i1,..,in)$(condition) = value;

where each index is a set (or alias) name - running over the members of that set -, a set name restricting it to
one label (UC_N('X')), or a quoted label; the condition is built from references to SYM at the same indices,
numbers, EPS, ABS(), unary minus, + - * /, the comparisons < <= > >= = <> (also LT LE GT GE EQ NE), NOT, AND, OR
and $; the value is such an expression without a reference, or one that refers to SYM itself. The loop runs over
the records of SYM only, so the condition must hold no record that SYM does not have: that is required (a top-level
$SYM(...) factor, or a comparison that is false for a missing record) and checked. Anything else is left to the
caller to report as unsupported.

Values follow GAMS: EPS is 0 in arithmetic and non-zero in a $ condition and in AND/OR/NOT.
"""
from __future__ import annotations
import re

EPS = "EPS"


class Unsupported(Exception):
    pass


TOK = re.compile(r"""\s*(?:
      (?P<q>'[^']*'|"[^"]*")
    | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
    | (?P<op><=|>=|<>|[-+*/()<>=,$])
    | (?P<w>[A-Za-z_][A-Za-z0-9_]*)
    )""", re.X)


def tokens(text):
    out, pos = [], 0
    text = text.strip()
    while pos < len(text):
        m = TOK.match(text, pos)
        if not m or m.end() == pos:
            raise Unsupported(f"cannot read {text[pos:pos + 20]!r}")
        pos = m.end()
        for k in ("q", "num", "op", "w"):
            if m.group(k) is not None:
                out.append((k, m.group(k)))
                break
    return out


class _P:
    """Recursive-descent parser over the tokens; expressions become small tuples."""
    WORD_OPS = {"LT": "<", "LE": "<=", "GT": ">", "GE": ">=", "EQ": "=", "NE": "<>"}

    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)

    def take(self, val=None):
        tok = self.peek()
        if tok[0] is None or (val is not None and tok[1].upper() != val):
            raise Unsupported(f"expected {val or 'more'} at {tok[1]!r}")
        self.i += 1
        return tok

    def at(self, val):
        tok = self.peek()
        return tok[0] is not None and tok[1].upper() == val

    # index list of a symbol: names, NAME('lab'), 'lab'
    def indices(self):
        self.take("(")
        idx = []
        while True:
            k, v = self.take()
            if k == "q":
                idx.append(("lab", v[1:-1].strip().upper()))
            elif k == "w":
                if self.at("(") and self.peek(1)[0] == "q" and self.peek(2)[1] == ")":
                    self.take("(")
                    lab = self.take()[1][1:-1].strip().upper()
                    self.take(")")
                    idx.append(("one", v.upper(), lab))
                else:
                    idx.append(("set", v.upper()))
            else:
                raise Unsupported(f"index {v!r}")
            if self.at(")"):
                self.take(")")
                return idx
            self.take(",")

    # expression grammar, loosest first:  OR < AND < NOT < comparison < $ < + - < * / < unary < atom
    def expr(self):
        a = self.and_()
        while self.at("OR"):
            self.take()
            a = ("or", a, self.and_())
        return a

    def and_(self):
        a = self.not_()
        while self.at("AND"):
            self.take()
            a = ("and", a, self.not_())
        return a

    def not_(self):
        if self.at("NOT"):
            self.take()
            return ("not", self.not_())
        return self.cmp()

    def cmp(self):
        a = self.dollar()
        tok = self.peek()
        op = tok[1] if tok[0] == "op" and tok[1] in ("<", "<=", ">", ">=", "=", "<>") else \
            self.WORD_OPS.get((tok[1] or "").upper()) if tok[0] == "w" else None
        if op:
            self.take()
            return ("cmp", op, a, self.dollar())
        return a

    def dollar(self):
        a = self.add()
        while self.at("$"):
            self.take()
            a = ("$", a, self.add())
        return a

    def add(self):
        a = self.mul()
        while self.at("+") or self.at("-"):
            op = self.take()[1]
            a = (op, a, self.mul())
        return a

    def mul(self):
        a = self.unary()
        while self.at("*") or self.at("/"):
            op = self.take()[1]
            a = (op, a, self.unary())
        return a

    def unary(self):
        if self.at("-"):
            self.take()
            return ("neg", self.unary())
        if self.at("+"):
            self.take()
        return self.atom()

    def atom(self):
        k, v = self.peek()
        if k == "op" and v == "(":
            self.take()
            e = self.expr()
            self.take(")")
            return e
        if k == "num":
            self.take()
            return ("num", float(v))
        if k == "w":
            u = v.upper()
            self.take()
            if u == "EPS":
                return ("eps",)
            if u == "INF":
                return ("num", float("inf"))
            if u == "ABS" and self.at("("):
                self.take("(")
                e = self.expr()
                self.take(")")
                return ("abs", e)
            if self.at("("):
                return ("ref", u, self.indices())
            raise Unsupported(f"name {v!r} without indices")
        raise Unsupported(f"unexpected {v!r}")


def parse(text):
    """(name, lhs indices, condition or None, rhs) of 'SYM(..)$(..) = rhs', the trailing ';' left out."""
    p = _P(tokens(text))
    k, name = p.take()
    if k != "w":
        raise Unsupported("not an assignment")
    idx = p.indices()
    cond = None
    if p.at("$"):
        p.take()
        cond = p.unary()                 # $(...) or $SYM(...): one factor
    p.take("=")
    rhs = p.expr()
    if p.peek()[0] is not None:
        raise Unsupported(f"text after the value: {p.peek()[1]!r}")
    return name.upper(), idx, cond, rhs


# ----------------------------------------------------------------------------------- evaluation
def _num(v):
    return 0.0 if v == EPS or v is None else v


def _nz(v):
    return v == EPS or (v is not None and v != 0)


def evaluate(e, look):
    """Value of e (float, EPS or None for 'no record'); look(ref) gives the value of a reference."""
    op = e[0]
    if op == "num":
        return e[1]
    if op == "eps":
        return EPS
    if op in ("ref", "sameas", "agg"):
        return look(e)
    if op == "abs":
        v = evaluate(e[1], look)
        return v if v == EPS else abs(_num(v))
    if op == "neg":
        v = evaluate(e[1], look)
        return v if v == EPS else -_num(v)
    if op == "$":
        return evaluate(e[1], look) if _nz(evaluate(e[2], look)) else 0.0
    if op == "not":
        return 0.0 if _nz(evaluate(e[1], look)) else 1.0
    if op in ("and", "or"):
        a, b = _nz(evaluate(e[1], look)), _nz(evaluate(e[2], look))
        return 1.0 if (a and b if op == "and" else a or b) else 0.0
    if op == "cmp":
        a, b = _num(evaluate(e[2], look)), _num(evaluate(e[3], look))
        return 1.0 if {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "=": a == b, "<>": a != b}[e[1]] else 0.0
    a, b = evaluate(e[1], look), evaluate(e[2], look)
    x, y = _num(a), _num(b)
    r = {"+": lambda: x + y, "-": lambda: x - y, "*": lambda: x * y, "/": lambda: x / y}[op]()
    if r == 0 and (a == EPS or b == EPS):
        return EPS
    return r


def _refs(e):
    if e[0] == "ref":
        yield e
    for x in e[1:]:
        if isinstance(x, tuple):
            yield from _refs(x)


def _requires_record(e, name):
    """True if e is 0 whenever SYM has no record: a $SYM factor, an AND with one, a comparison false at 0..."""
    op = e[0]
    if op == "ref":
        return e[1] == name
    if op == "$":
        return _requires_record(e[2], name) or _requires_record(e[1], name)
    if op == "and":
        return _requires_record(e[1], name) or _requires_record(e[2], name)
    if op == "cmp":                                  # comparison of the own value with a constant
        try:
            return evaluate(e, lambda r: None) == 0.0
        except Exception:
            return False
    return False


def apply(reader, text):
    """Apply one statement to reader.sym; raises Unsupported when it is not of a handled form, with nothing changed.
    Returns the number of records changed.  The form of the module docstring first; else a LOOP or an assignment of
    the wider forms of `execute` (its refusal reported as that of the first form)."""
    try:
        return _apply_simple(reader, text)
    except Unsupported as e:
        try:
            return execute(reader, text)
        except Unsupported:
            raise e from None


def _apply_simple(reader, text):
    try:
        name, idx, cond, rhs = parse(text)
    except Unsupported as e:
        raise Unsupported(f"not an assignment of the form SYM(...)$(condition) = value; {e}") from None
    name = reader.alias.get(name, name)
    if name not in reader.sym or reader.sym[name].kind != "par":
        raise Unsupported(f"{name} is not a parameter read from the DD files")
    sym = reader.sym[name]
    # the loop: positions of the index, each a filter on the record's label
    pos_of = {}
    filters = []
    for k, it in enumerate(idx):
        if it[0] == "lab":
            filters.append(lambda lab, x=it[1]: lab == x)
            continue
        setname = it[1]
        members = _members(reader, setname)
        if it[0] == "one":
            filters.append(lambda lab, x=it[2], m=members: lab == x and lab in m)
        else:
            filters.append(lambda lab, m=members: lab in m)
        pos_of.setdefault(setname, k)
    # references: the same symbol, indexed by the loop's names (or labels)
    for r in list(_refs(rhs)) + (list(_refs(cond)) if cond else []):
        if reader.alias.get(r[1], r[1]) != name or len(r[2]) != len(idx):
            raise Unsupported(f"reference to {r[1]} in a statement on {name}")
        for it in r[2]:
            if it[0] == "one" or (it[0] == "set" and it[1] not in pos_of):
                raise Unsupported(f"index {it} in a reference")
    if cond is None or not _requires_record(cond, name):
        raise Unsupported("the condition does not limit the statement to existing records")

    def key_of(r, rec):
        return tuple(rec[pos_of[it[1]]] if it[0] == "set" else it[1] for it in r[2])

    changed = 0
    for rec in list(sym.data):
        if len(rec) != len(idx) or not all(f(lab) for f, lab in zip(filters, rec)):
            continue
        look = lambda r, rec=rec: sym.data.get(key_of(r, rec))
        if not _nz(evaluate(cond, look)):
            continue
        v = evaluate(rhs, look)
        if v is None or (v != EPS and v == 0):
            del sym.data[rec]                       # GAMS: an assignment of 0 removes the record
        else:
            sym.data[rec] = v
        changed += 1
    return changed


def _members(reader, setname):
    s = reader.alias.get(setname, setname)
    if s not in reader.sym or reader.sym[s].kind != "set":
        raise Unsupported(f"index {setname} is not a set known when the DD file is read")
    return {k[0] for k in reader.sym[s].data if len(k) == 1}


# ------------------------------------------------------------------------- the model's own code: LOOP, wider assignments
# A file of GAMS code the run file includes may carry statements of more forms than a DD file's clean-up:
#
#     loop(UCLIST, UC_RHSRT(ALL_REG,UC_N,ALLYEAR,LIM)$(sameas(UCLIST,UC_N) $sum(RG$sameas(ALL_REG,RG), 1)) = 0; ...);
#
# Read here: LOOP(set or (set,set,..) [$condition], statements), and assignments SYM(i1,..,in)[$condition] = value
# whose indices are sets, labels or names a LOOP controls; the expressions of _P with SAMEAS(a,b), SUM, PROD, SMAX
# and SMIN(set or (sets) [$condition], expression), references to any set (a member: 1, else 0) or parameter read
# so far, scalars by name, YES and NO.  An assignment runs over the records of SYM when it can only change those (its
# condition needs SYM's own record, or the value is 0); else over every combination of the members of its index
# sets, up to MAX_SPACE of them.  Sets are run through in the order of their labels' entry, as GAMS does.  Anything
# else is Unsupported, and a statement refused halfway is undone.

TOK2 = re.compile(TOK.pattern.replace("[-+*/()<>=,$]", "[-+*/()<>=,$;]"), re.X)
AGG = {"SUM", "PROD", "SMAX", "SMIN"}
WORDS = {"NOT", "AND", "OR", "XOR", "LT", "LE", "GT", "GE", "EQ", "NE"}
MAX_SPACE = 2_000_000


def tokens2(text):
    out, pos = [], 0
    text = text.strip()
    while pos < len(text):
        m = TOK2.match(text, pos)
        if not m or m.end() == pos:
            raise Unsupported(f"cannot read {text[pos:pos + 20]!r}")
        pos = m.end()
        for k in ("q", "num", "op", "w"):
            if m.group(k) is not None:
                out.append((k, m.group(k)))
                break
    return out


class _Q(_P):
    """_P with SAMEAS, the aggregations, scalars by name, and statements (LOOP, assignment)."""

    def atom(self):
        k, v = self.peek()
        if k == "w":
            u = v.upper()
            paren = self.peek(1) == ("op", "(")
            if u == "SAMEAS" and paren:
                self.take()
                self.take("(")
                a = self.arg()
                self.take(",")
                b = self.arg()
                self.take(")")
                return ("sameas", a, b)
            if u in AGG and paren:
                self.take()
                self.take("(")
                dom = self.domain()
                cond = None
                if self.at("$"):
                    self.take()
                    cond = self.unary()
                self.take(",")
                e = self.expr()
                self.take(")")
                return ("agg", u, dom, cond, e)
            if u in ("YES", "NO") and not paren:
                self.take()
                return ("num", 1.0 if u == "YES" else 0.0)
            if not paren and u not in ("EPS", "INF") and u not in WORDS:
                self.take()
                return ("ref", u, [])            # a scalar
        return super().atom()

    def arg(self):
        k, v = self.take()
        if k == "q":
            return ("lab", v[1:-1].strip().upper())
        if k == "w":
            return ("set", v.upper())
        raise Unsupported(f"argument {v!r}")

    def domain(self):
        names = []
        if self.at("("):
            self.take("(")
            while True:
                k, v = self.take()
                if k != "w":
                    raise Unsupported(f"domain {v!r}")
                names.append(v.upper())
                if self.at(")"):
                    self.take(")")
                    return names
                self.take(",")
        k, v = self.take()
        if k != "w" or self.at("("):
            raise Unsupported(f"domain {v!r}")
        return [v.upper()]

    def statement(self):
        k, v = self.peek()
        if k == "w" and v.upper() == "LOOP" and self.peek(1) == ("op", "("):
            self.take()
            self.take("(")
            dom = self.domain()
            cond = None
            if self.at("$"):
                self.take()
                cond = self.unary()
            self.take(",")
            body = self.statements()
            self.take(")")
            return ("loop", dom, cond, body)
        if k != "w":
            raise Unsupported("not an assignment")
        self.take()
        idx = self.indices() if self.at("(") else []
        cond = None
        if self.at("$"):
            self.take()
            cond = self.unary()
        self.take("=")
        return ("assign", v.upper(), idx, cond, self.expr())

    def statements(self):
        out = []
        while True:
            while self.at(";"):
                self.take()
            if self.peek()[0] is None or self.at(")"):
                return out
            out.append(self.statement())
            if not (self.at(";") or self.at(")") or self.peek()[0] is None):
                raise Unsupported(f"text after a statement: {self.peek()[1]!r}")


def execute(reader, text):
    """Run a LOOP or an assignment of the forms above on reader.sym; the number of records changed."""
    p = _Q(tokens2(text))
    st = p.statements()
    if p.peek()[0] is not None or len(st) != 1:
        raise Unsupported("not one statement")
    r = _Run(reader)
    try:
        r.run(st[0], {})
    except Unsupported:
        r.undo()
        raise
    return r.changed


class _NoneType:
    pass


_NONE = _NoneType()


def _walk(e):
    yield e
    for x in e[1:]:
        if isinstance(x, tuple):
            yield from _walk(x)


def _uses_data(e):
    """e refers to a set or parameter, or has a SAMEAS or an aggregation."""
    return any(x[0] in ("ref", "sameas", "agg") for x in _walk(e))


class _Run:
    def __init__(self, reader):
        self.rd = reader
        self.changed = 0
        self.log = []                                # (data, key, value before or _NONE): to undo
        self.index = {}                              # (symbol, position) -> {label: [keys]}

    def undo(self):
        for data, key, old in reversed(self.log):
            if old is _NONE:
                data.pop(key, None)
            else:
                data[key] = old

    def name(self, n):
        return self.rd.alias.get(n, n)

    def sym(self, n):
        return self.rd.sym.get(self.name(n))

    def members(self, n):
        """The labels of a one-dimensional set, in the order of their entry."""
        if self.name(n) == "*":
            raise Unsupported(f"{n}: the universe")
        s = self.sym(n)
        if s is None or s.kind != "set":
            raise Unsupported(f"{n} is not a set read so far")
        uel = self.rd.uel
        return sorted({k[0] for k in s.data if len(k) == 1}, key=lambda x: uel.get(x, 1 << 60))

    def space(self, dom, b):
        import itertools
        lists = []
        for n in dom:
            if n in b:
                raise Unsupported(f"{n} is controlled already")
            lists.append(self.members(n))
        for combo in itertools.product(*lists):
            nb = dict(b)
            nb.update(zip(dom, combo))
            yield nb

    def arglab(self, a, b):
        if a[0] == "lab":
            return a[1]
        if a[1] in b:
            return b[a[1]]
        raise Unsupported(f"{a[1]} is not controlled here")

    def label(self, it, b):
        if it[0] == "lab":
            return it[1]
        if it[0] == "one":
            return it[2]
        if it[1] in b:
            return b[it[1]]
        raise Unsupported(f"{it[1]} is not controlled here")

    def ev(self, e, b):
        return evaluate(e, lambda r: self.look(r, b))

    def look(self, r, b):
        if r[0] == "sameas":
            return 1.0 if self.arglab(r[1], b) == self.arglab(r[2], b) else 0.0
        if r[0] == "agg":
            _, f, dom, cond, x = r
            vals = []
            for nb in self.space(dom, b):
                if cond is not None and not _nz(self.ev(cond, nb)):
                    continue
                vals.append(self.ev(x, nb))
            if f == "SUM":
                tot, eps = 0.0, False
                for v in vals:
                    if v == EPS:
                        eps = True
                    else:
                        tot += _num(v)
                return EPS if eps and tot == 0 else tot
            nums = [_num(v) for v in vals]
            if f == "PROD":
                tot = 1.0
                for v in nums:
                    tot *= v
                return tot
            if f == "SMAX":
                return max(nums) if nums else float("-inf")
            return min(nums) if nums else float("inf")
        s = self.sym(r[1])
        if s is None:
            raise Unsupported(f"{r[1]} is not known here")
        key = tuple(self.label(it, b) for it in r[2])
        if s.kind == "set":
            if not key:
                raise Unsupported(f"the set {r[1]} as a value")
            return 1.0 if key in s.data else 0.0
        return s.data.get(key)

    def run(self, st, b):
        if st[0] == "loop":
            _, dom, cond, body = st
            for nb in list(self.space(dom, b)):
                if cond is not None and not _nz(self.ev(cond, nb)):
                    continue
                for x in body:
                    self.run(x, nb)
        else:
            self.assign(st, b)

    # ---- assignments
    def _own(self, e, name, idx):
        return e[0] == "ref" and self.name(e[1]) == name and e[2] == idx

    def requires(self, e, name, idx):
        """e is 0 whenever SYM has no record at the assignment's index."""
        op = e[0]
        if self._own(e, name, idx):
            return True
        if op in ("$", "and"):
            return self.requires(e[1], name, idx) or self.requires(e[2], name, idx)
        if op == "cmp" and all(self._own(x, name, idx) for x in _walk(e) if x[0] in ("ref", "sameas", "agg")):
            try:
                return evaluate(e, lambda r: None) == 0.0
            except Exception:
                return False
        return False

    @staticmethod
    def factors(e):
        """The factors that must all be non-zero for e to be non-zero: those of $ and AND."""
        if e is None:
            return []
        if e[0] in ("$", "and"):
            return _Run.factors(e[1]) + _Run.factors(e[2])
        return [e]

    def keys_at(self, s, pos, lab):
        k = (s.name, pos)
        ix = self.index.get(k)
        if ix is None:
            ix = self.index[k] = {}
            for rec in s.data:
                if len(rec) > pos:
                    ix.setdefault(rec[pos], []).append(rec)
        return ix.get(lab, ())

    def put(self, data, key, v):
        old = data.get(key, _NONE)
        if v is None or (v != EPS and v == 0):
            if old is _NONE:
                return False
            del data[key]                            # GAMS: an assignment of 0 removes the record
        else:
            if old is not _NONE and old == v and type(old) is type(v):
                return False
            data[key] = v
        self.log.append((data, key, old))
        return True

    def assign(self, st, b):
        _, name, idx, cond, rhs = st
        name = self.name(name)
        s = self.rd.sym.get(name)
        if s is None or s.kind != "par":
            raise Unsupported(f"{name} is not a parameter read so far")
        dom = s.domain or []
        fixed, free = {}, {}
        for k, it in enumerate(idx):
            if it[0] in ("lab", "one") or it[1] in b:
                fixed[k] = self.label(it, b)
            else:
                free.setdefault(it[1], []).append(k)
        for it in idx:
            if it[0] == "one" and it[2] not in set(self.members(it[1])):
                return
        # the members a free index runs over: not checked where it is the declared domain of its positions
        filt = {}
        for n, ks in free.items():
            if self.name(n) == "*" or all(k < len(dom) and self.name(dom[k].upper()) == self.name(n) for k in ks):
                continue
            filt[n] = set(self.members(n))
        zero = not _uses_data(rhs) and rhs[0] != "eps" and evaluate(rhs, lambda r: None) == 0.0
        if zero or (cond is not None and self.requires(cond, name, idx)):
            self._over_records(s, idx, cond, rhs, b, fixed, free, filt)
        else:
            self._over_space(s, idx, cond, rhs, b, fixed, free)

    def _over_records(self, s, idx, cond, rhs, b, fixed, free, filt):
        pins = dict(fixed)
        for f in self.factors(cond):                 # SAMEAS(controlled, index) in the condition: one label there
            if f[0] != "sameas":
                continue
            for x, y in ((f[1], f[2]), (f[2], f[1])):
                if x[0] == "set" and x[1] in free:
                    try:
                        lab = self.arglab(y, b)
                    except Unsupported:
                        continue
                    for k in free[x[1]]:
                        pins[k] = lab
        if pins:
            pos = min(pins)
            cand = list(self.keys_at(s, pos, pins[pos]))
        else:
            cand = list(s.data)
        n = len(idx)
        for rec in cand:
            if len(rec) != n or rec not in s.data or any(rec[k] != lab for k, lab in pins.items()):
                continue
            nb, ok = dict(b), True
            for v, ks in free.items():
                lab = rec[ks[0]]
                if any(rec[k] != lab for k in ks[1:]) or (v in filt and lab not in filt[v]):
                    ok = False
                    break
                nb[v] = lab
            if not ok:
                continue
            if cond is not None and not _nz(self.ev(cond, nb)):
                continue
            if self.put(s.data, rec, self.ev(rhs, nb)):
                self.changed += 1

    def _over_space(self, s, idx, cond, rhs, b, fixed, free):
        import itertools
        names = list(free)
        size, lists = 1, []
        for v in names:
            m = self.members(v)
            size *= len(m)
            lists.append(m)
        if size > MAX_SPACE:
            raise Unsupported(f"an assignment over {size} combinations of {', '.join(names)}")
        self.index = {k: v for k, v in self.index.items() if k[0] != s.name}
        for combo in itertools.product(*lists):
            nb = dict(b)
            nb.update(zip(names, combo))
            key = tuple(fixed[k] if k in fixed else nb[it[1]] for k, it in enumerate(idx))
            if cond is not None and not _nz(self.ev(cond, nb)):
                continue
            if self.put(s.data, key, self.ev(rhs, nb)):
                self.changed += 1

# SPDX-License-Identifier: GPL-3.0-or-later
"""The DD files of a case parsed in parallel processes, applied in their order: the same Reader state as reading them
one after the other.

Reading a DD file is two things: parsing its text into records (most of the time: tokens, labels, keys), and applying
the records to the data read so far (a later value replaces an earlier one, a zero removes a record, SET.name copies
a set, an assignment statement computes on what is there).  Only the first is done in the worker processes.  A worker
returns the records of its file as a list of operations, in the order the serial reader would have met them; the main
process applies them in the include order of the run file.

A worker parses with the state known when the files are handed out (the switches of the run file, the declarations of
the TIMES source files).  What it assumed is returned with the result and checked against the real state when the
file's turn comes: the value of every %name% it substituted, and the kind (set, parameter, scalar) as which it
parsed every data block.  If
anything differs (a file that uses a switch set by an earlier DD file, or a symbol declared in two DD files with
different domains), that file is read again by the serial reader at its turn.  So is a file whose parse failed
(the serial reader then raises the error, as it would have) and one with a $IF NOT SET, whose effect depends on the
state.  The result is the state of the serial reader by construction; tests/test_ddpar.py compares the two.
"""
from __future__ import annotations
import os, re
from .gamsdata import Reader, Symbol, decode_source

_DDNAMES = re.compile(r"(?im)^(PARAMETER|SET)[ \t]*\r?\n?[ \t]*\r?\n?([A-Za-z_]\w*)")
_IFNOTSET = re.compile(r"(?i)IFI?\s+NOT\s+SET\s+(\w+)")


def dd_names(text):
    """Names of the sets and parameters a DD file gives data for (for controls.inputs_known)."""
    return {n.upper() for _, n in _DDNAMES.findall(text)}


class _Fallback(Exception):
    pass


class _Recorder(Reader):
    """A Reader that records operations instead of applying data."""

    def __init__(self, env, view, include_dirs):
        super().__init__(include_dirs=include_dirs)
        self.env = dict(env)
        self.env0 = dict(env)
        self.view = {n: Symbol(n, k, list(d) if d is not None else None) for n, (k, d) in view.items()}
        self.sym = self.view                 # the parse looks at kinds and domains only
        self.ops = []
        self.pending = []                    # labels met since the last operation: (upper, as written)
        self.seen = {}
        self.env_assumed = {}                # name -> value at the start of the file (None: not set)
        self.env_set = set()                 # names this file sets ($SET): later reads are its own

    # labels: recorded in order of first appearance in the file; the universe and casing are the main process's
    def lab(self, s):
        u = self._labs.get(s)
        if u is not None:
            return u
        raw = s
        s = s.strip()
        if len(s) >= 2 and s[0] in "'\"" and s[-1] == s[0]:
            s = s[1:-1]
        s = s.rstrip() if s.strip() else s
        u = s.upper()
        w = self.seen.get(u)
        if w is None:
            self.seen[u] = w = u
            self.pending.append((u, s))
        self._labs[raw] = w                  # the same string object each time: the result pickles small
        return w

    def _op(self, *op):
        if self.pending:
            self.ops.append(("L", self.pending))
            self.pending = []
        self.ops.append(op)

    def _envread(self, k):
        if k not in self.env_set and k not in self.env_assumed:
            self.env_assumed[k] = self.env0.get(k)

    def subst(self, line):
        if "%" not in line:
            return line
        for m in re.finditer(r"%([A-Za-z_][A-Za-z_0-9.]*)%", line):
            self._envread(m.group(1).upper())
        return super().subst(line)

    def _directive(self, line, src):
        m = _IFNOTSET.match(line.strip()[1:].strip())
        if m:
            raise _Fallback("$IF NOT SET")
        env, nu = dict(self.env), len(self.dd_unsupported)
        self.oneps = None
        super()._directive(line, src)
        for k, v in self.env.items():
            if k not in env or env[k] != v:
                self.env_set.add(k)
                self._op("env", k, v)
        if self.oneps is not None:            # $ONEPS / $OFFEPS: applied in order (the parse does not depend on it)
            self._op("oneps", self.oneps)
        for u in self.dd_unsupported[nu:]:
            self._op("unsup", u)

    def _dd_statement(self, toks, src):
        self._op("stmt", toks, src)

    def _set_members(self, name):
        raise _Fallback("#set: the members of a set are known in the main process only")

    def _alias(self, names):
        self._op("alias", names)

    def _declare(self, name, kind, dom, text, src):
        s = self.view.get(name)
        if s is None:
            s = self.view[name] = Symbol(name, kind, dom, text, src=src)
        elif dom is not None and s.domain is None:
            s.domain = dom
        self._op("decl", name, kind, dom, text, src)
        return s

    def _data(self, s, toks, scalar, parsed=None):
        parsed = parsed or self._parse_data(s, toks, scalar)
        self._op("data", s.name, parsed, scalar)


def parse_file(path, env, view, include_dirs):
    """In a worker: the operations of one DD file, or None when it must be read by the serial reader."""
    raw = open(path, "rb").read()
    text, enc = decode_source(raw)
    r = _Recorder(env, view, include_dirs)
    try:
        r.read_text(text, src=os.path.basename(path))
    except Exception:
        return None
    r._op("end")
    return {"ops": r.ops, "env": r.env_assumed,
            "enc": None if text.isascii() else enc, "names": dd_names(text)}


def _valid(rd, res):
    """Do the worker's assumptions hold? The %names% it substituted have the values it used, and every data block was
    parsed as the kind the symbol has at that point (set, parameter or scalar: this follows from the declarations
    before it, replayed here on the kinds and domains alone)."""
    for k, v in res["env"].items():
        if rd.env.get(k) != v:
            return False
    st = {}
    for op in res["ops"]:
        if op[0] == "decl":
            name, kind, dom = op[1], op[2], op[3]
            if name not in st:
                s = rd.sym.get(name)
                st[name] = (s.kind, s.domain) if s is not None else None
            cur = st[name]
            if cur is None:
                st[name] = (kind, dom)
            elif dom is not None and cur[1] is None:
                st[name] = (cur[0], dom)
        elif op[0] == "data":
            kind, dom = st[op[1]]
            mode = "scalar" if kind == "par" and (op[3] or dom == []) else kind
            if mode != op[2][0]:
                return False
    return True


def apply(rd, res, src):
    """Apply the operations of a parsed file to the Reader, as reading it would."""
    sym, uel, casing = rd.sym, rd.uel, rd.casing
    for op in res["ops"]:
        t = op[0]
        if t == "L":
            for u, s in op[1]:
                casing.setdefault(u, s)
                if u not in uel:
                    uel[u] = len(uel)
        elif t == "data":
            rd._apply_data(sym[op[1]], op[2])
        elif t == "decl":
            rd._declare(*op[1:])
        elif t == "env":
            rd.env[op[1]] = op[2]
            rd.user_sets.append((src, op[1], op[2]))
        elif t == "oneps":
            rd.oneps = op[1]
        elif t == "stmt":
            rd._dd_statement(op[1], op[2])
        elif t == "alias":
            rd._alias(op[1])
        elif t == "unsup":
            rd.dd_unsupported.append(op[1])
    if res["enc"]:
        rd.encodings.add(res["enc"])


def workers_wanted(paths):
    """Processes for parsing: TIMESPP_DD_WORKERS, else up to 8 (one less than the processors); 1 (no processes) when
    the DD files are small, where starting processes costs more than it saves."""
    w = os.environ.get("TIMESPP_DD_WORKERS")
    if w:
        return max(1, int(w))
    if sum(os.path.getsize(p) for p in paths) < 20 * 2**20 or len(paths) < 2:
        return 1
    return max(1, min(8, (os.cpu_count() or 2) - 1, len(paths)))


class Pool:
    """Hands the DD files to worker processes, and gives back the results in include order.

    The files are handed out all at once, the largest first (TIMESPP_DD_ALL=0: in include order, a few ahead of the one
    being applied, so that finished results do not pile up in memory).  A worker parses with the state of the start
    either way.  Handed out in order a few ahead, a large file is started only when its turn comes near, and the
    main process waits for each large file in turn (on a large model: 21 s of waiting, for 25 s of
    parsing shared by 8 processes)."""

    def __init__(self, paths, rd, workers):
        from concurrent.futures import ProcessPoolExecutor
        self.paths, self.rd = list(paths), rd
        self.ex = ProcessPoolExecutor(max_workers=workers)
        self.ahead = None if os.environ.get("TIMESPP_DD_ALL", "1") != "0" else workers + 2
        self.env = dict(rd.env)
        # the kinds and domains the workers parse with: the TIMES declarations (the first DD file may come before
        # initsys.mod in the run file), then what has been read so far
        from .load import fallback_domains
        self.view = {n: (d["kind"], d["domain"]) for n, d in fallback_domains().items()}
        self.view.update({n: (s.kind, s.domain) for n, s in rd.sym.items()})
        self.inc = list(rd.include_dirs)
        self.fut, self.next = {}, 0
        self.serial = []                     # the files read here after all (their assumptions did not hold)

    def _fill(self, upto):
        if self.ahead is None:
            if self.next == 0:
                for k in sorted(range(len(self.paths)), key=lambda k: -os.path.getsize(self.paths[k])):
                    self.fut[k] = self.ex.submit(parse_file, self.paths[k], self.env, self.view, self.inc)
                self.next = len(self.paths)
            return
        while self.next < len(self.paths) and self.next <= upto:
            self.fut[self.next] = self.ex.submit(parse_file, self.paths[self.next], self.env, self.view, self.inc)
            self.next += 1

    def read(self, i):
        """Apply file i (the files are asked for in order): parsed in a worker when its assumptions hold, else read here."""
        self._fill(i + (self.ahead or 0))
        rd, p = self.rd, self.paths[i]
        try:
            res = self.fut.pop(i).result()
        except Exception:
            res = None
        if res is None or not _valid(rd, res):
            self.serial.append(os.path.basename(p))
            rd.read_file(p)
            return dd_names(decode_source(open(p, "rb").read())[0])
        apply(rd, res, os.path.basename(p))
        return res["names"]

    def close(self):
        for f in self.fut.values():
            f.cancel()
        self.ex.shutdown(wait=True, cancel_futures=True)

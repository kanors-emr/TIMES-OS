# SPDX-License-Identifier: GPL-3.0-or-later
"""Parts of the preprocessor run beside the main thread (TIMESPP_PAR_STAGES; by default level 2 except on Windows's
NT heap), each on a connection of its own.

Only parts that share no table and no Python state with what runs meanwhile are run so (from the tables each step
reads and writes, and the names in the code):
  coefmain.mod   coef_ptr beside coef_cpt, coef_nio, coef_obj, coef_alt, coef_shp (prep/coefficients.coefmain);
  ppmain.mod     (TIMESPP_PAR_STAGES=2) the levelling of UC_FLO beside everything after it: nothing in the
                 preprocessor reads UC_FLO after it, and nothing after it writes what that levelling reads
                 (prep/userconstraints.user_constraints,
                 joined at the end of preprocess()). Apart from level 1 because that levelling is partly Python-heavy
                 (fetches and loops over the UC rows), which competes with the main thread for Python's lock.
DuckDB statements release Python's lock, so the SQL of both runs side by side; DuckDB's thread pool (TIMESPP_THREADS)
belongs to the database and is shared by both connections.
"""
import os, copy, threading


def enabled(level=1):
    """TIMESPP_PAR_STAGES=1: coef_ptr beside coefmain; 2: also the levelling of UC_FLO (see below); 0: neither.
    Unset: 2 on the Segment Heap and off Windows (4-9% faster on large models), 0 on Windows's NT heap, where it does
    not pay. Every table is the same either way."""
    v = os.environ.get("TIMESPP_PAR_STAGES")
    if v is None:
        from . import winheap
        return (0 if winheap.heap() == "nt" else 2) >= level
    try:
        return int(v) >= level
    except ValueError:
        return False


def beside(db, f, name=None):
    """Start f(w) in a thread, w a copy of db on a second connection to the same database (con.cursor(): tables,
    views and macros are shared, temp tables are not). Returns the function that waits for it, adds its hand-off
    timers to db's and raises what it raised. The scalars, controls and QA log are the same objects as db's."""
    from .engine import _Con
    w = copy.copy(db)
    w.con = _Con(db.con._c.cursor())
    w.hand = {}
    err = []

    def go():
        try:
            f(w)
            from . import tjb
            tjb.side_done(w, name or getattr(f, "__name__", "side"))    # its tables can go to model.tjb now
        except BaseException as e:          # raised again in the main thread, at the join
            err.append(e)
    t = threading.Thread(target=go, name=name or getattr(f, "__name__", "side"))
    t.start()

    def join():
        t.join()
        for k, (s, n, r) in w.hand.items():
            h = db.hand.setdefault(k, [0.0, 0, 0])
            h[0] += s; h[1] += n; h[2] += r
        w.con.close()
        if err:
            raise err[0]
    return join


def later(db, join):
    """Keep `join` to be called at the end of preprocess() (pending())."""
    db.__dict__.setdefault("side_pending", []).append(join)


def pending(db):
    """Wait for every part started with later(), in the order started."""
    for join in db.__dict__.pop("side_pending", []):
        join()

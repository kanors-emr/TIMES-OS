# SPDX-License-Identifier: GPL-3.0-or-later
"""Preprocess a TIMES case without GAMS and write the tables for the Julia equation module.

  python -m timespp <case.run> <TIMES source folder | -> <out.db3> [--log qa.log] [--low-memory] [--memory 3GB]

"-" for the TIMES source folder: the declaration files of TIMES v4.9.8 carried with the port (timespp/times_src).

The DD files are parsed in parallel processes when they are large (ddpar.py): up to 8, one less than the processors;
TIMESPP_DD_WORKERS=<n> sets the number (1: no processes).  The result is the same either way.
"""
import os, sys, time
from .load import read_case, build_db
from . import controls, sysconst, export, domfilter, pipeline, side, tjb, stream

FIRST = "declarations and DD files"            # then the phases of pipeline.PHASES


def preprocess(run_file, src_dir, verbose=True, audit=None, work_db=None, memory=None, tjb_path=None, db3_path=None):
    """The preprocessed model.  audit: a dict that receives what happened (see `main`); with it, unsupported
    features are listed instead of stopping at the first one.
    work_db: a file for the DuckDB tables instead of memory (--low-memory); memory: DuckDB's memory limit, e.g. '3GB'
    (with a file, what does not fit is written to disk: the tables and the intermediate results of large statements).
    tjb_path: model.tjb, written in pieces as its tables become final, beside the steps (tjb.py; finished by _export).
    db3_path: model.db3; with TIMESPP_DB3_STREAM=1 the Parquet folder in its place (model_parquet), written the same
    way (stream.py); the steps of a myopic run (TIMESTEP, or FIXBOH) then go into model_steps.db3 (export.to_steps)."""
    t0 = time.time()
    if db3_path and os.path.exists(export.steps_of(db3_path)):
        os.remove(export.steps_of(db3_path))       # (the steps of an earlier run in this folder)
    rd, dd_order = read_case(run_file, src_dir)
    if work_db:
        os.makedirs(os.path.dirname(os.path.abspath(work_db)), exist_ok=True)
        _remove_work(work_db)
    db = build_db(rd, work_db or ":memory:")
    _OPEN.append(db)
    rd = None                       # the records read from the DD files are in DuckDB now: their Python copy goes
    if memory or work_db:
        db.set_memory(memory or "3GB")
    if work_db:
        db.con.execute(f"SET temp_directory='{(work_db + '.tmp').replace(chr(39), chr(39) * 2)}'")
    from . import winheap
    threads, heap = db.con.execute("select current_setting('threads')").fetchone()[0], winheap.heap()
    stages = 2 if side.enabled(2) else 1 if side.enabled(1) else 0
    if verbose:
        print(f"  DuckDB with {threads} threads; parallel stages level {stages}"
              + (f"; process heap: {'Segment Heap' if heap == 'segment' else 'NT heap'}" if heap else ""))
        for src, text, k in db.dd_applied:          # assignments in DD files, applied where they stand
            print(f"  {src}: {k} record(s) changed by  {text[:150]}")
    if audit is not None:
        audit["dd_statements"] = [{"file": f, "statement": t, "records": k} for f, t, k in db.dd_applied]
        db.audit = audit["unsupported"]
        audit["switches"] = {k: str(v) for k, v in sorted(db.env.items())}
        audit["dd_files"] = list(dd_order)
        audit["duckdb_threads"], audit["heap"], audit["parallel_stages"] = threads, heap, stages
    step = FIRST
    try:
        controls.derive(db)
        if audit is not None:                       # the results of earlier runs read (readbprice.mod, spoint.mod)
            audit["base_prices_from"] = getattr(db, "base_prices_from", None)
            if getattr(db, "base_prices_note", None):
                audit.setdefault("notes", []).append(db.base_prices_note)
        sysconst.load(db)
        domfilter.apply(db, verbose=verbose)
    except Exception as e:
        if audit is None:
            raise
        _note_failure(audit, step, e)
        return None
    if verbose:
        print(f"  {time.time() - t0:6.1f}s  {FIRST}")
    pieces = None
    if tjb_path and tjb.overlap() and not work_db:      # (--low-memory: no writer beside the steps, nor its memory)
        import random
        pieces = db.tjb_pieces = tjb.Pieces(db, tjb_path, random.getrandbits(62))
        if db3_path and stream.enabled():
            # (no drops in a myopic run: its steps read the tables again after the main pass, which no traced model does)
            myopic = bool(db.ctl.get("TIMESTEP")) or db.ctl.get("FIXBOH") is not None
            db.stream = stream.Stream(db, db3_path, pieces, drops_allowed=not myopic)
            if myopic and os.path.exists(db3_path):
                os.remove(db3_path)                 # (the model.db3 of an earlier run: Julia would read its steps)
        pieces.after(FIRST)
    try:
        return _steps(db, verbose, audit, pieces)
    except BaseException:
        if pieces is not None:
            pieces.abandon()
        if getattr(db, "stream", None) is not None:
            db.stream.abandon()
        raise


def _steps(db, verbose, audit, pieces):
    failed = False
    for phase, steps in pipeline.PHASES:
        t = time.time()
        db.timings = []
        many = verbose and len(steps) > 1          # a phase of several steps: its steps as they finish, then its total
        if many:
            print(f"  {'':9}{phase}:", flush=True)
        try:
            for s in steps:
                step = f"{phase}: {s.title}" if len(steps) > 1 else phase
                t1 = time.time()
                s.run(db)
                db.timings.append((s.title, time.time() - t1))
                if pieces is not None:
                    pieces.after(step)
                if many:
                    print(f"  {time.time() - t1:6.1f}s      {s.title}", flush=True)
        except Exception as e:
            # With audit, a failing step does not end the run: the later steps still run on what there is, so that
            # one pass lists every unsupported feature the model needs. A step that fails after unsupported input was
            # met is most likely a consequence of it (its remaining statements are skipped and said so); one that
            # fails before is a defect of the port, reported as such. Either way no tables are written.
            if audit is None:
                raise
            _note_failure(audit, step, e)
            failed = True
            if verbose:
                print(f"  {time.time() - t:6.1f}s  {step}  (failed: {type(e).__name__}; the run goes on to list the rest)")
            continue
        if verbose:
            print(f"  {time.time() - t:6.1f}s  {phase}", flush=True)
    t = time.time()
    try:
        side.pending(db)                  # the parts run beside the main thread (TIMESPP_PAR_STAGES=1, side.py)
    except Exception as e:
        if audit is None:
            raise
        _note_failure(audit, "parts run beside the main thread", e)
        failed = True
    if verbose and time.time() - t >= 0.05:
        print(f"  {time.time() - t:6.1f}s  waiting for the parts run beside the main thread")
    if failed:
        if pieces is not None:
            pieces.abandon()
        if getattr(db, "stream", None) is not None:
            db.stream.abandon()
        return None
    return db


def _tjb_path(path):
    """model.tjb beside model.db3 (written beside the steps unless TIMESPP_TJB=0, ..._PIECES=0 or ..._OVERLAP=0)."""
    return os.path.splitext(path)[0] + ".tjb" if tjb.overlap() else None


def _export(db, path, after_tjb=None):
    """model.tjb (unless TIMESPP_TJB=0), then model.db3, both with the same token: the binary copy is what the
    equations read; it is complete first, so that they can start while model.db3 is written.  With the Parquet folder
    (stream.py) in place of model.db3, a myopic run's steps go into model_steps.db3, of the same token, first."""
    import random
    token = random.getrandbits(62)
    tjbf = os.path.splitext(path)[0] + ".tjb"
    pieces = getattr(db, "tjb_pieces", None)
    if pieces is None and os.path.exists(tjbf):
        os.remove(tjbf)
    if getattr(db, "stream", None) is None and os.path.isdir(stream.folder_of(path)):
        import shutil                            # (a Parquet folder of an earlier run: model.db3 replaces it)
        shutil.rmtree(stream.folder_of(path), ignore_errors=True)
    if os.environ.get("TIMESPP_TJB", "1") != "0":
        t = time.time()
        if tjb.enabled():
            # version 2, in pieces: those written beside the steps (preprocess(tjb_path=...)), then the rest
            if pieces is None:
                pieces = tjb.Pieces(db, tjbf, token, thread=False)
            token = pieces.token
            db.tjb_info = pieces.finish()
        else:
            export.to_bin(db, tjbf, token)
        db.tjb_seconds = round(time.time() - t, 1)
        print(f"  {time.time() - t:6.1f}s  writing the binary copy for the equations ({os.path.basename(tjbf)})", flush=True)
        if getattr(db, "tjb_info", None):
            i = db.tjb_info
            print(f"  {'':9}(tables written beside the steps: {i['early']}; waited {i['waited']} s for them; after the "
                  f"last step: {i['at_end']}, of them written again {i['written_again']}"
                  + (f" ({', '.join(i['again'])})" if i["again"] else "") + f"; writers' time {i['writer_seconds']} s)", flush=True)
            for e in i["writer_errors"]:
                print(f"  {'':9}(the writer: {e})", flush=True)
        after_tjb and after_tjb()
        st = getattr(db, "stream", None)
        if st is not None and getattr(db, "steps", None):
            # the steps of a myopic run, which the equations read after model.tjb: in their own small file, written
            # before the Parquet folder (model.db3, which held them, is not written)
            t = time.time()
            export.to_steps(db, export.steps_of(path), token)
            print(f"  {time.time() - t:6.1f}s  writing the steps ({os.path.basename(export.steps_of(path))})", flush=True)
        if st is not None:                       # the Parquet folder in place of model.db3 (stream.py)
            th = os.environ.get("TIMESPP_DB3_THREADS")
            if th:                               # (what is left is written beside the equation build: fewer threads)
                db.con.execute(f"set threads = {max(1, int(th))}")
            n = st.finish(token)
            db.stream_info = i = st.info
            print(f"  {'':9}(Parquet files written beside the steps: {i['early']}; after the last step: written again "
                  f"{i['written_again']}" + (f" ({', '.join(i['again'])})" if i["again"] else "") + f"; waited {i['waited']} s; "
                  f"writers' time {i['writer_seconds']} s; tables dropped {i['dropped']} ({i['dropped_rows']:,} rows); "
                  f"large tables written after model.tjb {i['deferred']})", flush=True)
            for e in i["writer_errors"]:
                print(f"  {'':9}(the Parquet writer: {e})", flush=True)
            return n
        # model.db3 beside the equation build slows the build (they share the processors and memory bandwidth): the
        # runner can hold it back until Julia has handed the model to HiGHS (TIMESPP_DB3_AFTER: a file whose existence
        # says go), or give it fewer threads (TIMESPP_DB3_THREADS). Either way it appears under its name only complete.
        go = os.environ.get("TIMESPP_DB3_AFTER")
        if go:
            t = time.time()
            _wait_for(go)
            print(f"  {time.time() - t:6.1f}s  waiting to write {os.path.basename(path)} (until the model is in HiGHS)", flush=True)
        th = os.environ.get("TIMESPP_DB3_THREADS")
        if th:
            db.con.execute(f"set threads = {max(1, int(th))}")
    return export.to_sqlite(db, path, token)


def _output(db, path):
    """What was written: model.db3, or the Parquet folder in its place (stream.py)."""
    return stream.folder_of(path) if getattr(db, "stream", None) is not None else path


def _wait_for(go):
    """Until the file `go` exists, or the process that started this one has ended (then nobody will say go)."""
    parent = os.getppid()
    while not os.path.exists(go):
        if not _alive(parent):
            return
        time.sleep(0.2)


def _alive(pid):
    if os.name != "nt":
        return os.getppid() == pid
    import ctypes
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = ctypes.c_void_p
    h = k.OpenProcess(0x1000, False, pid)                  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
    finally:
        k.CloseHandle(ctypes.c_void_p(h))


def _note_failure(audit, step, e):
    """Record a step that raised: a NotPorted as one more unsupported feature, any other error as the defect of the
    port (the first one) or, after unsupported input was met, as a step that could not complete because of it."""
    import traceback
    if isinstance(e, controls.NotPorted):
        audit["unsupported"].append({"what": str(e), "symbols": {}})
        return
    text = "".join(traceback.format_exception(e))[-3000:]
    if audit["unsupported"]:
        audit.setdefault("incomplete_steps", []).append({"step": step, "error": text[-600:]})
    elif not audit.get("error"):
        audit["error"] = text
        audit["stopped_in"] = step


_OPEN = []                          # the databases opened by preprocess(), closed by main() before the work file goes


def _remove_work(work_db):
    """The work database of --low-memory and its spill folder (left by an earlier run, or done with)."""
    import shutil
    for f in (work_db, work_db + ".wal"):
        try:
            if os.path.exists(f):
                os.remove(f)
        except OSError as e:                     # still open elsewhere (Windows): left in place, said so
            print(f"  could not remove {f}: {e}")
    shutil.rmtree(work_db + ".tmp", ignore_errors=True)


def _kernel_report(audit=None):
    """What the Julia kernels cost (kernels.report), in the log and in the audit file."""
    from . import kernels
    if not kernels.active():
        return
    r = kernels.report()
    if audit is not None:
        audit["kernels"] = r
    if r.get("note"):
        print(f"  Julia kernels: {r['note']}")
    if not r["kernels"]:
        return
    print(f"  Julia kernels ({'default' if r['default'] else 'TIMESPP_KERNELS'}): start-up "
          + ", ".join(f"{k} {v:.2f}s" for k, v in r["start-up"].items()))
    for name, k in r["kernels"].items():
        print(f"    {name}: {k['calls']} calls ({k['declined']} declined), {k['rows to julia']:,} rows to Julia, "
              f"{k['rows from julia']:,} back; " + ", ".join(f"{p} {v:.2f}s" for p, v in k["seconds"].items()))
        if k.get("why declined"):
            print(f"      declined: {'; '.join(k['why declined'])}")


def main(argv):
    """python -m timespp <case.run> <TIMES source folder | -> <out.db3> [--log qa.log] [--audit result.json]
                         [--low-memory] [--memory 3GB]

    "-" for the TIMES source folder: the declaration files carried with the port (timespp/times_src).

    --audit: do not stop at the first unsupported feature; write to result.json the status (ok / unsupported /
    error), every unsupported feature met with the input that needs it, the step where the run stopped, the
    run-file switches and the time taken.  The tables are written only when the status is ok.  Exit status 0 / 3 / 1.
    --low-memory: the DuckDB tables in a work file next to out.db3 (<out>.work.duckdb, deleted at the end) instead of
    in memory, with DuckDB held to --memory (default 3GB) and the rest written to disk: slower, much less memory.
    --memory <size>: DuckDB's memory limit (DuckDB syntax: 3GB, 500MB), also without --low-memory."""
    if len(argv) < 3:
        print(__doc__)
        return 2
    t0 = time.time()
    work_db = argv[2] + ".work.duckdb" if "--low-memory" in argv else None
    memory = argv[argv.index("--memory") + 1] if "--memory" in argv else None
    try:
        return _main(argv, t0, work_db, memory)
    finally:
        for db in _OPEN:
            try:
                db.con.close()
            except Exception:
                pass
        _OPEN.clear()
        if work_db:
            _remove_work(work_db)


def _write_json(path, obj):
    """Write path whole or not at all: to path.part, then replace path with it. The runner reads path while this
    process runs; on Windows a replace is refused for a moment while another process (the runner's read, a virus
    scanner, the search indexer) has the file open, so it is tried again for up to 30 s."""
    import json
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    for i in range(300):
        try:
            os.replace(path + ".part", path)
            return
        except PermissionError:
            if i == 299:
                raise
            time.sleep(0.1)


def _main(argv, t0, work_db, memory):
    if "--audit" in argv:
        import json
        out = argv[argv.index("--audit") + 1]
        a = {"status": "error", "unsupported": [], "stopped_in": None, "error": None}
        try:
            db = preprocess(argv[0], argv[1], audit=a, work_db=work_db, memory=memory, tjb_path=_tjb_path(argv[2]), db3_path=argv[2])
        except Exception as e:                      # reading the case itself failed
            import traceback
            db, a["stopped_in"], a["error"] = None, "reading the run file and the DD files", "".join(traceback.format_exception(e))[-3000:]
        if a["unsupported"]:
            a["status"] = "unsupported"
        elif db is not None:
            a["status"] = "ok"
            a["earlier_results"] = getattr(db, "earlier_results", [])    # the results of earlier runs read (refpoint.py)
            if getattr(db, "mlf_calibration", None):
                a["mlf_calibration"] = db.mlf_calibration               # TIMES-MACRO MLF (prep/mlf.py _calibrate)
            t1 = time.time()
            def early():                            # the equations can start: preprocess.json says so before model.db3 is done
                a["handoffs"] = db.handoffs()
                a["tjb_seconds"] = db.tjb_seconds
                a["tjb"] = getattr(db, "tjb_info", None)
                a["db3_pending"] = True
                a["seconds"] = round(time.time() - t0, 1)
                _write_json(out, a)
                del a["db3_pending"]
            a["symbols_written"] = _export(db, argv[2], early)
            a["export_seconds"] = round(time.time() - t1, 1)
            a["output"] = _output(db, argv[2])
            if getattr(db, "stream_info", None):
                a["stream"] = db.stream_info
            print(f"  {a['export_seconds']:6.1f}s  writing the tables ({a['symbols_written']} symbols) to {os.path.basename(a['output'])}")
            a["handoffs"] = db.handoffs()
            print("  hand-offs (seconds, statements, rows):")
            for k, v in a["handoffs"].items():
                print(f"  {v['seconds']:9.1f}s  {v['statements']:9,}  {v['rows']:13,}  {k}")
            _kernel_report(a)
            a["qa"] = db.log[:200]
        a["seconds"] = round(time.time() - t0, 1)
        _write_json(out, a)
        print(f"  {a['seconds']:6.1f}s  total; status {a['status']}" + (f"; stopped in: {a['stopped_in']}" if a["stopped_in"] else ""))
        for u in a["unsupported"]:
            print("  UNSUPPORTED:", u["what"], u["symbols"] or "")
        return {"ok": 0, "unsupported": 3}.get(a["status"], 1)
    db = preprocess(argv[0], argv[1], work_db=work_db, memory=memory, tjb_path=_tjb_path(argv[2]), db3_path=argv[2])
    t1 = time.time()
    n = _export(db, argv[2])
    out = _output(db, argv[2])
    print(f"  {time.time() - t1:6.1f}s  writing the tables ({n} symbols) to {os.path.basename(out)}")
    print(f"  {time.time() - t0:6.1f}s  total; {n} symbols written to {out}")
    _kernel_report()
    if "--log" in argv:
        with open(argv[argv.index("--log") + 1], "w") as f:
            f.write("\n".join(db.log) + "\n")
    for line in db.log[:20]:
        print("  QA:", line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

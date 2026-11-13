# SPDX-License-Identifier: GPL-3.0-or-later
"""GDX2VEDA text file. Header comments, then one quoted record per result row.

Dimensions, from the header of a TIMES VD file:
Attribute, Commodity, Process, Period, Region, Vintage, TimeSlice, UserConstraint, PV

Label spelling is the first appearance in the DD. timespp.gamsdata.Reader.lab stores it
in Reader.casing, and timespp.load.build_db copies that onto db.casing. The report tables
hold the upper-case form; the writer looks each label up there.

Bytes, as GAMS and GDX2VEDA write them: the labels and texts of the DD files in the bytes they came in (UTF-8 as
Veda writes DD files, or Latin-1 for older files; model.db3 says which), and the retirement vintage, the label ¤ of
the TIMES source (Latin-1), as the byte 0xA4. A Polish or French name is then the same bytes as in the GAMS files.

A stored 0 is EPS. GAMS deletes a true zero on a plain assignment, so every zero row of
PAR_NCAPM, REG_WOBJ and CAP_NEW in GAMS is EPS. GDX2VEDA prints EPS
as 0. The not-0 option then drops those rows for the attributes named in times2veda.vdd.
"""
from __future__ import annotations
import csv, os, re
from decimal import Decimal, ROUND_HALF_UP

_DIGITS15 = Decimal("1.00000000000000")

DIMS = ("Attribute", "Commodity", "Process", "Period", "Region", "Vintage", "TimeSlice", "UserConstraint", "PV")
FIELDS = DIMS[1:-1]
_LETTER = {
    "w": "Sow", "r": "Region", "c": "Commodity", "p": "Process", "t": "Period",
    "v": "Vintage", "s": "TimeSlice", "uc_n": "UserConstraint",
}
# A stochastic run (STAGES, times2veda_stc.vdd) has the dimension Sow after Attribute.
FIELDS_STC = ("Sow",) + FIELDS
_HEADER = """\
*  GDX2VEDAversion- 2005-10-07
*         ImportID- Scenario:{scenario}
*       VEDAFlavor- TIMES
*       Dimensions- {dims}
* ParentDimensions- Commodity: Region; Process: Region; UserConstraint: Region
*      SetsAllowed- Commodity;Process;UserConstraint
*        FieldSize- {sizes}
*       NotIndexed- PV
*         ValueDim- PV
*  DefaultValueDim- PV
*   FieldSeparator- ,
*        TextDelim- "
"""

# GAMS names from times2veda.vdd that the report writer fills. Add a name here when
# its statements are ported. Until then the attribute is NOT PRODUCED, even on a model
# where it would have no rows. A name on this list that comes out empty is reported
# as empty.
PORTED = {
    "par_actl", "par_actm",
    "par_capl", "par_pasti", "par_capm", "par_ncapl", "par_ncapm",
    "f_in", "f_out", "agg_out", "par_eout", "p_out", "par_rtcs", "val_flo",
    "par_comprdl", "par_comprdm", "par_comnetl", "par_comnetm",
    "eqg_combal.l", "par_combalem", "eqe_combal.l", "par_combalgm",
    "eq_peak.l", "par_peakm",
    "par_cumflol", "par_cumflom", "par_cumcst",
    "par_capbd", "par_cumret", "par_top", "Cap_New",
    "ObjZ.l", "reg_wobj", "cst_pvp", "cst_pvc", "par_ncapr",
    "par_ucsl", "par_ucsm", "par_ucmrk", "par_ucrtp", "par_ucmax",
    "cst_invc", "cst_invx", "cst_decc", "cst_salv", "cst_fixc", "cst_fixx",
    "cst_actc", "cst_floc", "cst_flox", "cst_comc", "cst_comx", "cst_come", "cst_irec",
    "cst_time", "par_ipric", "reg_irec", "reg_acost", "reg_obj",
    "TM_RESULT",                    # TIMES-MACRO MLF (rpt_ext.mlf, mlf.py)
    "CM_RESULT", "CM_MAXC_M",
}


def _encode(text: str, encoding: str) -> bytes:
    """The bytes GAMS writes for a text: the encoding of the DD files, ¤ as the byte 0xA4."""
    def enc(s):
        try:
            return s.encode(encoding)
        except UnicodeEncodeError:              # a file of the other encoding among the DD files
            return s.encode("utf-8")
    return b"\xa4".join(enc(part) for part in text.split("\u00a4"))


def _decode(raw: bytes, encoding: str) -> str:
    """The inverse of _encode, for reading the files GAMS wrote."""
    return raw.decode(encoding, errors="surrogateescape").replace("\udca4", "\u00a4")


def _lines(path: str, encoding: str):
    text = _decode(open(path, "rb").read(), encoding)
    return [ln for ln in text.splitlines(keepends=True) if ln.strip() and not ln.startswith("*")]


def read_records(path: str, encoding: str = "utf-8"):
    """Yield (attribute, commodity, process, period, region, vintage, timeslice, uc, value)."""
    lines = _lines(path, encoding)
    for row in csv.reader(lines):
        if len(row) < 9:
            continue
        yield row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], float(row[8])


def by_attribute(path: str, attribute: str):
    """Records of one attribute, keyed by the seven index fields, value is PV."""
    out = {}
    for rec in read_records(path):
        if rec[0].lower() != attribute.lower():
            continue
        out[rec[1:8]] = rec[8]
    return out


def read_quads(path: str, encoding: str = "utf-8"):
    """Rows of a .vde or .vds file: four quoted fields."""
    lines = _lines(path, encoding)
    for row in csv.reader(lines):
        if len(row) >= 4:
            yield row[0], row[1], row[2], row[3]


def write_quads(path: str, rows, encoding: str = "utf-8"):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        for rec in rows:
            f.write(_encode(",".join('"' + str(x).replace('"', '""') + '"' for x in rec) + "\r\n", encoding))


def vdd_table(path: str, section: str):
    """Token rows of one times2veda.vdd section, comments skipped."""
    rows, on = [], False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                on = s == section
                continue
            if on and s and not s.startswith("*"):
                rows.append(s.split())
    return rows


def read_all(path: str):
    """Every attribute, keyed by its name, then by the seven index fields."""
    out = {}
    for rec in read_records(path):
        out.setdefault(rec[0], {})[rec[1:8]] = rec[8]
    return out


def vdd_entries(path: str):
    """DataEntries of times2veda.vdd, in file order, and the not-0 attribute names.

    Each entry is (veda attribute, gams symbol, index tokens). A token /LO/ is a
    fixed element: that column is filtered and the field stays '-'.
    """
    entries, not0 = [], set()
    section = ""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                section = s
                continue
            if section == "[Options]" and s.lower().startswith("not-0"):
                not0 = {t.lower() for t in s.split()[1:]}
            if section != "[DataEntries]" or not s or s.startswith("*"):
                continue
            parts = s.split()
            entries.append((parts[0], parts[1], parts[2:]))
    return entries, not0


def _symbol(gams: str):
    """GAMS name as stored: ObjZ.l is the scalar L_OBJZ, eqg_combal.l is L_EQG_COMBAL."""
    if gams.lower().endswith(".l"):
        return "L_" + gams[:-2].upper()
    return gams.upper()


def _num(value: float) -> str:
    """The number as GDX2VEDA writes it: 15 significant digits of the exact binary value, a tie rounded away from
    zero (27.78049797179025 is 27.7804979717903), trailing zeros dropped, and below 1E-4 or from 1E15 on with an
    exponent: 2.5E-16, 1.2E-5 (capital E, no leading zero)."""
    if value == 0.0:
        return "0"
    if value != value or value in (float("inf"), float("-inf")):
        return format(value, ".15g")
    d = Decimal(value).normalize()
    e = d.adjusted()
    q = d.scaleb(-e).quantize(_DIGITS15, rounding=ROUND_HALF_UP)
    if abs(q) >= 10:                                # 9.99..95 rounds up to 10: one place more
        e += 1
        q = (q / 10).quantize(_DIGITS15, rounding=ROUND_HALF_UP)
    mant = format(q, "f").rstrip("0").rstrip(".")
    if -4 <= e < 15:
        text = format(q.scaleb(e), "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    return f"{mant}E{e}"


def _spell(casing, label: str) -> str:
    shown = casing.get(label, label)
    # The database stores the retirement vintage as the four characters \xA4, the form
    # gams.transfer gives it. rptmisc.rpt writes the label '¤', and GDX2VEDA writes that
    # character, so the escaped form is turned back into it here (rptmisc.py, _RET).
    esc = re.fullmatch(r"\\[xX]([0-9A-Fa-f]{2})", shown)
    if esc:
        return chr(int(esc.group(1), 16))
    return shown


def produced_rows(db, entries, not0, fields=FIELDS):
    """Rows for the DataEntries it is given.

    A GAMS symbol that is not in the model contributes no rows. Whether that is
    'not produced' or an error is decided by the caller, from the list
    of parameters the report has ported.
    """
    by_attr = {}
    for attr, gams, indexes in entries:
        by_attr.setdefault(attr, []).append((gams, indexes))
    rows, feeds = {}, {}
    for attr, sources in by_attr.items():
        feeds[attr] = [gams for gams, _ in sources]
        got = {}
        for gams, indexes in sources:
            name = _symbol(gams)
            if name not in db.sym and name not in db.s:
                continue
            for key, value in _rows(db, attr, gams, indexes, not0, fields):
                if key in got:
                    raise SystemExit(
                        f"VD clash on {attr} {key}: {gams} and an earlier parameter both write it")
                got[key] = value
        rows[attr] = got
    return rows, feeds


def _rows(db, attr, gams, indexes, not0, fields=FIELDS):
    name = _symbol(gams)
    drop0 = attr.lower() in not0
    if not indexes:
        value = float(db.s.get(name, 0.0))
        if drop0 and value == 0.0:
            return
        yield (("-",) * len(fields)), value
        return
    cols = db.cols(name)
    if len(cols) != len(indexes):
        raise SystemExit(f"{gams} has columns {cols} but times2veda.vdd indexes it as {indexes}")
    where = []
    for col, token in zip(cols, indexes):
        if token.startswith("/") and token.endswith("/"):
            where.append(f'"{col}" = \'{token[1:-1].upper()}\'')
        elif token not in _LETTER:
            raise SystemExit(f"{gams} index {token} is not a Veda field")
    quoted = ", ".join(f'"{c}"' for c in cols)
    sql = f'select {quoted}, value from "{name}"'
    if where:
        sql += " where " + " and ".join(where)
    casing = getattr(db, "casing", {})
    for rec in db.q(sql):
        value = float(rec[-1])
        if drop0 and value == 0.0:
            continue
        key = ["-"] * len(fields)
        for token, label in zip(indexes, rec):
            if token.startswith("/"):
                continue
            key[fields.index(_LETTER[token])] = _spell(casing, label)
        yield tuple(key), value


def write_vd(path: str, scenario: str, rows: dict, encoding: str = "utf-8", fields=FIELDS):
    """Write one .vd file. Attribute order is the vdd order; row order is table order."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    dims = ("Attribute",) + tuple(fields) + ("PV",)
    head = _HEADER.format(scenario=scenario, dims=";".join(dims),
                          sizes=";".join(f"{d}:{20 if d == 'PV' else 63}" for d in dims))
    with open(path, "wb") as f:
        f.write(_encode(head.replace("\n", "\r\n"), encoding))
        for attr, got in rows.items():
            for key, value in got.items():
                body = ",".join('"' + str(x).replace('"', '""') + '"' for x in (attr,) + key)
                f.write(_encode(body + "," + _num(value) + "\r\n", encoding))

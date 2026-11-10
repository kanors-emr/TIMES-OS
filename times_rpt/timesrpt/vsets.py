# SPDX-License-Identifier: GPL-3.0-or-later
"""Element texts (.vde) and set membership (.vds) that GDX2VEDA writes.

solsetv.v3 builds the reporting sets and the attribute descriptions. FINISHUP
(lines 195-200) reassigns three of them after the report:

    RP_SGS(R,P) $= PRC_MAP(R,'NST',P);
    IRE_DIST(RP_IRE(R,P)) $= SUM(RPC_IREIO(R,P,C,IE,'IN'),1);
    RP_UX(RP_IRE(R,P)) $= SUM(RPC_IRE(R,P,C,IE),NRGELC(R,C));

The .vds file reads those, not the sets the preprocessor left behind.
Lines 160-161 fill a description the input did not give:

    COM_DESC(RC(R,C))$(NOT COM_DESC(R,C)) = COM_GRP(C);
    PRC_DESC(RP(R,P))$(NOT PRC_DESC(R,P)) = PRC(P);

Set-element texts are kept by the DD reader (timespp.load.build_db, elem_text).
The set's own text is sym_text, from the first declaration. solsetv's text is
used only when the model has none, so HPL stays 'Heat and Steam Plants'
(setglobs.gms) rather than the later 'Heating Plants'.
"""
from __future__ import annotations
import os, re

from .vd import _spell, vdd_table

_DIM = {
    "attr": "Attribute", "w": "Sow", "c": "Commodity", "p": "Process", "t": "Period",
    "r": "Region", "v": "Vintage", "s": "TimeSlice", "uc_n": "UserConstraint",
}
# solsetv.v3 lines 117-127. Each is PRC_MAP(R, group, P) inside RP.
_PRC_GROUP = {"DMD", "PRE", "PRW", "PRV", "REF", "ELE", "CHP", "HPL", "DISTR", "RENEW", "XTRACT"}
# solsetv.v3 lines 143-148. The sector code is not always the set name (COMM <- 'COM').
_DEM_SECTOR = {"RES": "RES", "COMM": "COM", "TRN": "TRN", "AGR": "AGR", "IND": "IND", "OTHD": "OTH"}
# solsetv.v3 lines 150-157, intersected with NRG.
_NRG_TYPE = {
    "NRGELC": ("ELC",),
    "NRGHET": ("LTHEAT", "HTHEAT"),
    "NRGFOS": ("FOSSIL",),
    "NRGREN": ("RENEN", "FRERENEW", "LIMRENEW"),
    "NRGSYN": ("SYNTH",),
}
_DIRECT = {"RP_STG", "RP_STS", "RP_IRE", "PRC_RCAP", "NRG", "DEM", "ENV", "MAT"}


def _decl_texts(path):
    """Set declaration texts in one GAMS file. The first one in the file wins."""
    if not os.path.isfile(path):
        return {}
    text = open(path, encoding="latin1").read()
    decl = {}
    for name, quoted in re.findall(
            r"(?m)^\s*(?:SET\s+)?([A-Za-z_][\w+]*)\s*(?:\([^)]*\))?\s*'([^']*)'", text):
        decl.setdefault(name.upper(), quoted)
    return decl


def _solset_texts(src):
    """ADESC from solsetv.v3, and declaration texts. setglobs is read before solsetv."""
    path = os.path.join(src, "solsetv.v3")
    text = open(path, encoding="latin1").read()
    files = [os.path.join(src, n) for n in ("setglobs.gms", "initmty.mod", "solsetv.v3")]
    decl = {}
    for f in files:
        for name, quoted in _decl_texts(f).items():
            decl.setdefault(name, quoted)
    adesc = []
    block = re.search(r"SET ADESC.*?/(.*?)/;", text, re.S)
    if block:
        for line in block.group(1).splitlines():
            m = re.match(r"\s*(\S+)\s+'(.*)'\s*$", line)
            if m:
                adesc.append((m.group(1), m.group(2)))
    return decl, adesc


def _set_text(db, decl, name):
    got = (getattr(db, "sym_text", {}) or {}).get(name.upper(), "")
    return got or decl.get(name.upper(), "")


# rptlite.rpt lines 12-13. solsysd adds these to SYSUC; the prefix on these runs is empty.
_SYSUC = """VAR VARX INV INVX INV+ INVX+ FIX FIXX IRE COM ACT FLO ELS DAM DAS DAM-EXT+
INSTCAP LUMPINV LUMPIX COST CGAP GGAP RNGLO RNGUP RATIO GRATIO LEVCOST""".split()


def _members(db, gams):
    """(region, element) rows of one ParentSubSets line. Empty when the set is not there."""
    g = gams.upper()
    if g in _PRC_GROUP and "RP" in db.sym and "PRC_MAP" in db.sym:
        return db.q(f"select r, p from RP where in_PRC_MAP(r, '{g}', p)")
    if g == "RP_SGS" and "PRC_MAP" in db.sym:
        return db.q("select r, p from PRC_MAP where prc_grp = 'NST'")
    if g == "IRE_DIST" and "RP_IRE" in db.sym and "RPC_IREIO" in db.sym:
        return db.q("""
            select i.r, i.p from RP_IRE i
            where exists (select 1 from RPC_IREIO k
                          where k.r = i.r and k.p = i.p and k.io = 'IN')
        """)
    if g == "RP_UX" and "RP_IRE" in db.sym and "RPC_IRE" in db.sym and "NRG" in db.sym:
        return db.q("""
            select distinct i.r, i.p from RP_IRE i
            join RPC_IRE k on k.r = i.r and k.p = i.p
            where exists (select 1 from NRG n
                          where n.r = k.r and n.c = k.c and in_NRG_TMAP(n.r, 'ELC', n.c))
        """)
    if g in _DEM_SECTOR and "DEM_SMAP" in db.sym:
        sector = _DEM_SECTOR[g]
        col = next(c for c in db.cols("DEM_SMAP") if c not in ("r", "c"))
        return db.q(f'select r, c from DEM_SMAP where "{col}" = \'{sector}\' and in_RC(r, c)')
    if g in _NRG_TYPE and "NRG" in db.sym:
        pred = " or ".join(f"in_NRG_TMAP(r, '{t}', c)" for t in _NRG_TYPE[g])
        return db.q(f"select r, c from NRG where {pred}")
    if g in _DIRECT and g in db.sym:
        return db.q(f'select r, "{db.cols(g)[1]}" from "{g}"')
    if g == "UC_R_EACH" and g in db.sym:
        return db.q(f'select {", ".join(db.cols(g))} from "{g}"')
    if g == "UC_CONST" and "UC_R_SUM" in db.sym:
        uc = db.cols("UC_R_SUM")[1]
        return db.q(f'select distinct \'NONE\', "{uc}" from UC_R_SUM')
    if g == "UC_DYNBD" and "PRC_DYNUC" in db.sym:
        return db.q('select distinct r, uc from PRC_DYNUC')
    return []


def membership(db, vdd):
    """(.vds) dimension, region, set, element. One ParentSubSets line, one GAMS set."""
    casing = getattr(db, "casing", {})
    rows = []
    for veda, gams, *indexes in vdd_table(vdd, "[ParentSubSets]"):
        dim = _DIM[indexes[-1]]
        for region, element in _members(db, gams):
            rows.append((dim, _spell(casing, region), veda, _spell(casing, element)))
    return rows


def _elem_text(db, name, key, fallback):
    return (getattr(db, "elem_text", {}) or {}).get(name, {}).get(key) or fallback


def _labelled(db, name):
    """Elements of a one-dimensional set, as (label, text). Text falls back to the label."""
    if name not in db.sym:
        return []
    col = db.cols(name)[0]
    casing = getattr(db, "casing", {})
    out = []
    for (label,) in db.q(f'select "{col}" from "{name}"'):
        shown = _spell(casing, label)
        out.append((shown, _elem_text(db, name, (label,), shown)))
    return out


def descriptions(db, vdd, src):
    """(.vde) dimension, parent, element, text."""
    decl, adesc = _solset_texts(src)
    casing = getattr(db, "casing", {})
    got = {}

    def put(dim, parent, element, text):
        got.setdefault((dim, parent, element), text)

    for name, text in adesc:
        put("Attribute", "-", name, text)
    for gams, letter in vdd_table(vdd, "[DimensionTextAll]"):
        if gams.lower() == "adesc":
            continue
        dim = _DIM[letter]
        for label, text in _labelled(db, gams.upper()):
            put(dim, "-", label, text)
    # solsetv.v3 lines 160-161 fill a missing description with the element name.
    for name, table, dim in (("PRC_DESC", "RP", "Process"), ("COM_DESC", "RC", "Commodity")):
        for key, text in (getattr(db, "elem_text", {}) or {}).get(name, {}).items():
            if len(key) == 2:
                put(dim, _spell(casing, key[0]), _spell(casing, key[1]), text)
        if table in db.sym:
            for a, b in db.q(f"select r, { 'p' if table == 'RP' else 'c' } from {table}"):
                put(dim, _spell(casing, a), _spell(casing, b), _spell(casing, b))
    # solsetv.v3 lines 178-179. PGPRIM defaults to ACT (rptlite).
    # times2veda.vdd lists reg_act after com_desc, so this text replaces the
    # commodity description of the primary group (d14s COM_DESC says 'Activity').
    env = getattr(db, "env", {}) or {}
    prim = str(env.get("PGPRIM", "ACT")).strip().strip("'\"").upper() or "ACT"
    if "ALL_REG" in db.sym:
        col = db.cols("ALL_REG")[0]
        shown = _spell(casing, prim)
        for (r,) in db.q(f'select "{col}" from ALL_REG'):
            got[("Commodity", _spell(casing, r), shown)] = shown
        got[("Commodity", "NONE", shown)] = shown
    # solsetv.v3 lines 180-181. OTHCOM is the peak commodities and the currencies.
    for table, skip in (("COM_PEAK", "r"), ("RDCUR", "r")):
        if table not in db.sym:
            continue
        col = next(c for c in db.cols(table) if c != skip)
        for (lab,) in db.q(f'select distinct "{col}" from "{table}"'):
            shown = _spell(casing, lab)
            put("Commodity", "-", shown, shown)
    # rptlite.rpt lines 12-13, and solsetv.v3 line 170 PLUSET / '+' / and line 169 NONSET / NONE /.
    for lab in _SYSUC + ["+"]:
        put("UserConstraint", "-", lab, lab)
    put("Period", "-", "NONE", "NONE")
    put("TimeSlice", "-", "NONE", "NONE")
    if "PAR_PASTI" in db.sym:
        for (lab,) in db.q('select distinct u from PAR_PASTI'):
            shown = _spell(casing, lab)
            put("Vintage", "-", shown, shown)
    # rptmisc.rpt writes the retirement vintage as the character ¤. It is a universe
    # element on every run, including a model that stores no retirement row (GasGrid).
    put("Vintage", "-", "\u00a4", "\u00a4")
    for gams, *indexes in vdd_table(vdd, "[ParentDimensionTextAll]"):
        if gams.lower() in ("prc_desc", "com_desc"):
            continue
        name = gams.upper()
        if name not in db.sym or len(db.cols(name)) != 2:
            continue
        dim = _DIM[indexes[-1]]
        a, b = db.cols(name)
        for x, y in db.q(f'select "{a}", "{b}" from "{name}"'):
            put(dim, _spell(casing, x), _spell(casing, y),
                _elem_text(db, name, (x, y), _spell(casing, y)))
    # A SET row is the Veda set's own declaration text. ELC+ and OTH are aliases of
    # NRGELC and OTHD, so the Veda name has no text and the file has no row for them.
    seen = set()
    for veda, _gams, *indexes in vdd_table(vdd, "[ParentSubSets]"):
        kind = {"p": "ProcessSET", "c": "CommoditySET", "uc_n": "UserConstraintSET"}.get(indexes[-1])
        if kind is None or veda in seen:
            continue
        text = _set_text(db, decl, veda)
        if not text:
            continue
        seen.add(veda)
        put(kind, "-", veda, text)
    return [key + (text,) for key, text in got.items()]

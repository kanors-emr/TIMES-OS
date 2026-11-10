# SPDX-License-Identifier: GPL-3.0-or-later
"""equcrtp.vda, the preprocessing parts: process-wise dynamic bounds (UC_DYNBND), TIMES v4.9.8.

A user constraint flagged in UC_DYNBND(uc_n, bd) is not generated as a user constraint: for each of its processes
and each period t, EQ(l)_UCRTP bounds X(t) against LHS^lead * X(t-1) + RHS * lead (X = CAP, NCAP or the annual
activity).  The coefficients come from UC_CAP / UC_NCAP / UC_ACT(ANNUAL) and are moved to PRC_DYNUC(uc, side, r,
y, p, grp, bd) here (INIT_EXT, init_ext.vda); they are given defaults and interpolated in PREP_EXT (prep_ext.vda);
the standard UC machinery is switched off for them in PPM_EXT (ppm_ext.vda).  The commodity form: UC_COMNET /
UC_COMPRD on such a constraint (ANNUAL only) become UC_COM(uc, NET/PRD, side, r, y, c, 'ANNUAL', 'UCN') with their
interpolation options here; preppm.mod interpolates them with the other UC_COM, ppmain.mod gives the commodity its
VAR_COMNET / VAR_COMPRD (UC_ON of the dynamic bound, RXX), and EQN_UCRTC states them (LO and UP only; the FX call of
EQU_EXT stops before EQ_UCRTC).
"""
from ..engine import DB


def init_ext(db: DB):
    """$LABEL INIT_EXT: move dynamic bounds to the dedicated attribute PRC_DYNUC."""
    if not db.card("UC_DYNBND"):
        return
    # --- OPTION CLEAR=UNCD1; LOOP(UC_DYNBND(UCN,BD),UNCD1(UCN)=YES);
    db.tmp("t_uncd1", "select distinct uc from UC_DYNBND")
    # --- PRC_DYNUC(UC_N,SIDE,R,LL,P,'CAP',BD)$UC_DYNBND(UC_N,BD) $= UC_CAP(UC_N,SIDE,R,LL,P);  'NCAP' $= UC_NCAP;  'ACT' $= UC_ACT(..,'ANNUAL')
    for grp, src, extra in (("CAP", "UC_CAP", ""), ("NCAP", "UC_NCAP", ""), ("ACT", "UC_ACT", " and a.s='ANNUAL'")):
        db.put("PRC_DYNUC", f"""select a.uc, a.side, a.r, a.y, a.p, '{grp}' as grp, d.l, a.value
                                from {src} a join UC_DYNBND d on d.uc=a.uc where in_REG(a.r){extra}""", zero="eps")
    # --- UC_COM(UC_N(UNCD1),'NET',SIDE,R,LL,C,ANNUAL(S),'UCN') $= UC_COMNET(UC_N,SIDE,R,LL,C,S);
    #     UC_COM(UC_N(UNCD1),'PRD',SIDE,R,LL,C,ANNUAL(S),'UCN') $= UC_COMPRD(UC_N,SIDE,R,LL,C,S);
    #     (all years, the option year '0' included; a timeslice other than ANNUAL is dropped with the rest below)
    for cv, src in (("NET", "UC_COMNET"), ("PRD", "UC_COMPRD")):
        db.put("UC_COM", f"""select a.uc, '{cv}' as cv, a.side, a.r, a.y, a.c, a.s, 'UCN' as grp, a.value
                             from {src} a join t_uncd1 u on u.uc=a.uc where a.s='ANNUAL' and in_REG(a.r)""", zero="eps")
    # --- UC_CAP(UC_N(UNCD1),SIDE,R,LL,P) = 0;  UC_NCAP = 0;  UC_ACT(..,S) = 0;  UC_COMPRD = 0;  UC_COMNET = 0;
    for n in ("UC_CAP", "UC_NCAP", "UC_ACT", "UC_COMPRD", "UC_COMNET"):
        db.remove(n, where=f'in_REG(r) and exists(select 1 from t_uncd1 u where u.uc="{n}".uc)')
    _ucn_com_defaults(db)


def _ucn_com_defaults(db: DB):
    """equcrtp.vda lines 28-36: the interpolation options of UC_COM(..,'UCN') and the side not given.
    LL--ORD(LL) and LASTLL are the label '0' (the last element of ALLYEAR, initsys.mod).  Each statement reads the
    values as they are before it (GAMS assigns in parallel)."""
    u = "grp='UCN' and in_REG(r) and exists(select 1 from t_uncd1 d where d.uc=a.uc)"
    k = "b.uc=a.uc and b.cv=a.cv and b.r=a.r and b.c=a.c and b.s=a.s and b.grp=a.grp"
    def has(side, y="'0'"):
        return f"exists(select 1 from UC_COM b where {k} and b.side='{side}' and b.y={y})"
    def val(side):
        return f"(select b.value from UC_COM b where {k} and b.side='{side}' and b.y='0')"
    # --- UC_COM(UCN(UNCD1),COM_VAR,'LHS',R,LL--ORD(LL),C,S,'UCN')$((NOT ..'LHS',R,'0'..)$UC_COM(..'LHS',R,LL..)) = 5;
    db.put("UC_COM", f"""select distinct a.uc, a.cv, 'LHS' as side, a.r, '0' as y, a.c, a.s, a.grp, 5 as value
                         from UC_COM a where a.side='LHS' and {u} and not {has('LHS')}""")
    # --- UC_COM(..'RHS',R,LL--ORD(LL)..)$((NOT ..'RHS',R,'0'..)$UC_COM(..'RHS',R,LL..)) = UC_COM(..'LHS',R,'0'..) + 10$(NOT ..'LHS','0'..);
    db.put("UC_COM", f"""select distinct a.uc, a.cv, 'RHS' as side, a.r, '0' as y, a.c, a.s, a.grp, coalesce({val('LHS')}, 10) as value
                         from UC_COM a where a.side='RHS' and {u} and not {has('RHS')}""")
    # --- UC_COM(UCN,COM_VAR,'RHS',R,LL,C,S,'UCN')$((NOT ..'RHS',R,'0'..)$UC_COM(..'LHS',R,LL..)) =
    #       EPS$(NOT MIYR_1(LL)) + UC_COM(..'LHS',R,LL..)$LASTLL(LL);
    #     (no RHS given: EPS in every LHS year but the first period, which gets nothing; the option '0' as on the LHS)
    db.put("UC_COM", f"""select a.uc, a.cv, 'RHS' as side, a.r, a.y, a.c, a.s, a.grp, case when a.y='0' then a.value else 0 end as value
                         from UC_COM a where a.side='LHS' and {u} and not in_MIYR_1(a.y) and not {has('RHS')}""", zero="eps")
    # --- UC_COM(UCN,COM_VAR,'LHS',R,LL,C,S,'UCN')$((NOT ..'LHS',R,'0'..)$UC_COM(..'RHS',R,LL..)) =
    #       (1+(UC_COM(..'RHS',R,LL..)-1)$LASTLL(LL));
    #     (no LHS given: 1 in every RHS year, the option '0' as on the RHS; unlike PRC_DYNUC also for EPS RHS years)
    db.put("UC_COM", f"""select a.uc, a.cv, 'LHS' as side, a.r, a.y, a.c, a.s, a.grp, case when a.y='0' then a.value else 1 end as value
                         from UC_COM a where a.side='RHS' and {u} and not {has('LHS')}""")


def prep_ext(db: DB, interp):
    """$LABEL PREP_EXT: defaults, inter-/extrapolation, the periods of the constraints."""
    if not db.card("PRC_DYNUC"):
        return
    key = "uc, r, p, grp, l"
    # --- PRC_DYNUC(UC_N,'LHS',R,LL--ORD(LL),P,UC_GRPTYPE,BD)$((NOT ..'LHS',R,'0',..)$PRC_DYNUC(..'LHS',R,LL,..)) = 5;
    #     (LL--ORD(LL) is the last year label, '0': the interpolation option of a series without one)
    db.put("PRC_DYNUC", f"""select distinct uc, 'LHS' as side, r, '0' as y, p, grp, l, 5 as value from PRC_DYNUC a where side='LHS'
                            and not exists(select 1 from PRC_DYNUC b where b.uc=a.uc and b.side='LHS' and b.r=a.r and b.y='0'
                                           and b.p=a.p and b.grp=a.grp and b.l=a.l)""")
    # --- PRC_DYNUC(..'RHS',R,LL--ORD(LL),..)$((NOT RHS '0')$RHS(LL)) = PRC_DYNUC('LHS',R,'0',..) + 10$(NOT LHS '0');
    db.put("PRC_DYNUC", f"""select distinct a.uc, 'RHS' as side, a.r, '0' as y, a.p, a.grp, a.l,
                                   coalesce((select b.value from PRC_DYNUC b where b.uc=a.uc and b.side='LHS' and b.r=a.r and b.y='0'
                                             and b.p=a.p and b.grp=a.grp and b.l=a.l), 10) as value
                            from PRC_DYNUC a where a.side='RHS'
                            and not exists(select 1 from PRC_DYNUC b where b.uc=a.uc and b.side='RHS' and b.r=a.r and b.y='0'
                                           and b.p=a.p and b.grp=a.grp and b.l=a.l)""")
    # --- LOOP(BD, UC_GMAP_P(R,UC_N,UC_GRPTYPE,P)$PRC_DYNUC(UC_N,'RHS',R,'0',P,UC_GRPTYPE,BD) = YES);
    db.add("UC_GMAP_P", "select distinct r, uc, grp, p from PRC_DYNUC where side='RHS' and y='0'")
    # --- If no RHS defined, set RHS to EPS for all LHS years except for the IE option according to LHS:
    #     PRC_DYNUC('RHS',R,LL,..)$((NOT RHS '0')$LHS(LL)) = EPS + LHS(LL)$LASTLL(LL);
    db.put("PRC_DYNUC", f"""select a.uc, 'RHS' as side, a.r, a.y, a.p, a.grp, a.l, case when a.y='0' then a.value else 0 end as value
                            from PRC_DYNUC a where a.side='LHS'
                            and not exists(select 1 from PRC_DYNUC b where b.uc=a.uc and b.side='RHS' and b.r=a.r and b.y='0'
                                           and b.p=a.p and b.grp=a.grp and b.l=a.l)""", zero="eps")
    # --- If no LHS defined, set LHS to 1 for all RHS years except for the IE option according to RHS:
    #     PRC_DYNUC('LHS',R,LL,..)$((NOT LHS '0')$RHS(LL)) = (1+(RHS(LL)-1)$LASTLL(LL))$(NOT SAMEAS('NCAP',UC_GRPTYPE));
    db.put("PRC_DYNUC", f"""select a.uc, 'LHS' as side, a.r, a.y, a.p, a.grp, a.l,
                                   case when a.grp='NCAP' then 0 when a.y='0' then a.value else 1 end as value
                            from PRC_DYNUC a where a.side='RHS'
                            and not exists(select 1 from PRC_DYNUC b where b.uc=a.uc and b.side='LHS' and b.r=a.r and b.y='0'
                                           and b.p=a.p and b.grp=a.grp and b.l=a.l)""")
    # --- $SET RESET 1;  $BATINCLUDE prepparm PRC_DYNUC 'UC_N,SIDE,R' 'P,UC_GRPTYPE,BD' "" T 1 1
    interp.prepparm(db, "PRC_DYNUC", "T", None, 1, def_iebd=1, reset=1)
    # --- Disable growth/decay equation in first period of availability if no constant specified:
    #     PRC_DYNUC(UCN,RHS,RTP(R,TT(T+1),P),UC_GRPTYPE,BD)$((RTP(R,T,P)->MIYR_1(TT))$(NOT UC_GMAP_P(R,UCN,UC_GRPTYPE,P))
    #                                                        $PRC_DYNUC(UCN,'LHS',R,'0',P,UC_GRPTYPE,BD)) = 0;
    from .common import _values
    years = [y for (y,) in db.q("select y from MILESTONYR order by yv(y)")]
    nxt = dict(zip(years[:-1], years[1:]))
    first = db.q1("select y from MIYR_1")
    db.tmp("t_next", _values([(t, tt) for t, tt in nxt.items()], ["t", "tt"]) if nxt else "select '' as t, '' as tt where false")
    db.remove("PRC_DYNUC", where="""side='RHS' and in_RTP(r, y, p)
        and exists(select 1 from t_next n where n.tt=PRC_DYNUC.y and (not in_RTP(PRC_DYNUC.r, n.t, PRC_DYNUC.p) or in_MIYR_1(n.tt)))
        and not in_UC_GMAP_P(r, uc, grp, p)
        and exists(select 1 from PRC_DYNUC b where b.uc=PRC_DYNUC.uc and b.side='LHS' and b.r=PRC_DYNUC.r and b.y='0'
                   and b.p=PRC_DYNUC.p and b.grp=PRC_DYNUC.grp and b.l=PRC_DYNUC.l)""")
    # --- Set final UC_GMAPs for REDUCE:  LOOP(BD, UC_JMAP('1',UCN,RHS,R,T(MIYR_1),P,UC_GRPTYPE)$PRC_DYNUC(UCN,RHS,R,'0',P,UC_GRPTYPE,BD) = YES);
    db.add("UC_JMAP", f"select distinct '1' as j, uc, 'RHS' as side, r, '{first}' as y, p, grp from PRC_DYNUC where side='RHS' and y='0'")


def t_succ(db: DB):
    """LOOP(UC_DYNBND(UCN,BD),UC_T_SUCC(R,UCN,'0') = YES);   (after the PREP_EXT block, whether or not PRC_DYNUC has records)"""
    if db.card("UC_DYNBND"):
        # (BD: LO, UP, FX; the flag UC_DYNBND('OBJ1','N') of stochastic TIMES, prep_ext.stc, is not in the loop)
        db.add("UC_T_SUCC", "select g.r, d.uc, '0' as y from REG g, (select distinct uc from UC_DYNBND where l in ('LO','UP','FX')) d")


def ppm_ext(db: DB):
    """$LABEL PPM_EXT: make sure that standard UCs are not generated for the dynamic bounds."""
    if not db.card("UC_DYNBND"):
        return
    # --- LOOP(UC_DYNBND(UCN,BD), UC_ON(R,UCN) = NO; UC_R_SUM(R,UCN) = NO; UC_R_EACH(R,UCN) = NO);
    for n in ("UC_ON", "UC_R_SUM", "UC_R_EACH"):
        db.remove(n, where=f"in_REG(r) and exists(select 1 from UC_DYNBND d where d.uc=\"{n}\".uc and d.l in ('LO','UP','FX'))")

# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_UTILP, EQ_CONSO, EQ_CONDA, EQ_LOGBD, EQ_MACSH, EQ_MACAG, EQ_MACES, EQ_KNCAP, EQ_MCAP, EQ_TMC,
    EQ_IVECBND, EQ_DD, EQ_DEMSH, EQ_DEMAG, EQ_DEMCES, EQ_ENSCST, EQ_TRDBAL                  equ_ext.mlf, mod_equa.tm

TIMES-MACRO in its linearised form (MLF, `\$SET MACRO MLF` with a reference run, `TIMESED`): the model TIMES_MACRO,
which maximises the utility VAR_UTIL. The macro-economic model of each region with MACRO (MR) is linked to the energy
system through the demands VAR_DEM (in the commodity balances instead of COM_PROJ, RD_NLP) and the annual costs
VAR_OBJCOST (EQ_OBJ by region and period, `eq_obj!`). Its non-linear functions are written in steps VAR_MELA(r,t,cg,j,bd)
of the variables they are taken of: the logarithm of consumption (cg = CON), the CES functions of production (cg the
inputs of AKL and YN: KN, LAB, AKL, ACT) and of the demands (cg the demand commodities). The coefficients come from
the calibration of MACRO and presolve.mlf (prep/mlf.py of the preprocessor): TM_SHAR, TM_PREF, TM_AGC, TM_QREF,
TM_VOC, TM_STEP, TM_CIE, TM_CESLEV, TM_MIDCON, TM_LOGVAL.

    EQ_UTILP:  SUM(MR(r), SUM(t, TM_NWT(r)*TM_PWT(t)*TM_DFACT(r,t) *
                   (LOG(TM_MIDCON(r,t)) - SUM(LOGJ(j,bd), BDSIG(bd)*VAR_MELA(r,t,'CON',j,bd)/TM_LSC)))) +
               SUM(r not MR, SUM(t, (3*TM_ANNC(r,t) - VAR_OBJCOST(r,t)*TM_SCALE_CST)*TM_UDF(r,t)))
                 =  VAR_UTIL * MAX(1,LOG(TM_SCALE_UTIL*1000))/1000
    EQ_CONSO(MR,t):    VAR_D(r,t,'YN') = VAR_C + VAR_INV + VAR_EC + VAR_NTX\$PP(t)
    EQ_CONDA(MR,t):    VAR_C(r,t) = TM_MIDCON(r,t) * (1 - SUM(LOGJ(j,bd), VAR_MELA(r,t,'CON',j,bd)*TM_LOGVAL(j,bd)/TM_LSC))
    EQ_LOGBD(MR,t):    SUM(LOGJ(j,bd), VAR_MELA(r,t,'CON',j,bd)/ORD(j)/TM_LOGJOT) <= TM_LSC
    EQ_MACSH(MR,t,TM_DMAS(cg,cg1)):  VAR_D(r,t,cg1) + SUM(TM_RCJ(r,cg1,j,bd)\$TM_PP(r,t), BDSIG(bd)*VAR_MELA(r,t,cg1,j,bd))
                                       =  TM_SHAR(r,t,cg,cg1) * VAR_D(r,t,cg) / TM_CIE(r,t,cg)
    EQ_MACAG(TM_PP(MR,t),TM_CES(cg)):  SUM(TM_RCJ(r,cg1,j,bd)\$TM_DMAS(cg,cg1),
                                           (TM_PREF(r,t,cg1)*(TM_AGC(r,t,cg,cg1,j,bd)-1) + TM_SHAR(r,t,cg1,cg)) * BDSIG(bd)*VAR_MELA(r,t,cg1,j,bd)) = 0
    EQ_MACES(TM_PP(MR,t),TM_DMAS(cg,cg1)):  SUM(TM_RCJ(r,cg1,j,bd), VAR_MELA(r,t,cg1,j,bd)*TM_STEP(r,cg1,bd)/ORD(j)/(TM_QREF(r,t,cg1)*TM_VOC(r,t,cg1,bd)))
                                              <=  VAR_D(r,t,cg) / TM_CIE(r,t,cg) / TM_CESLEV(r,t,cg)
    EQ_KNCAP(MR,t):    VAR_D(r,t,'KN') = VAR_K(r,t)
    EQ_MCAP(MR,PP(t+1)):  VAR_K(r,t+1) = VAR_K(r,t)*TM_TSRV(r,t) + (D(t+1)*VAR_INV(r,t+1) + TM_TSRV(r,t)*D(t)*VAR_INV(r,t))/2
    EQ_TMC(MR,TLAST(t)):  VAR_K(r,t) * (TM_GROWV(r,t) + TM_DEPR(r))/100 <= VAR_INV(r,t)
    EQ_IVECBND(MR,PP(t)):  VAR_INV(r,t) + VAR_EC(r,t) <= TM_Y0(r) * TM_L(r,t)**TM_IVETOL(r)
    EQ_DD(MR,PP(t),'ACT'):  VAR_DEM(r,t,'ACT') = (1/TM_SCALE_NRG) * (TM_AEEIFAC(r,t,'ACT')*VAR_D(r,t,'ACT') + VAR_SP(r,t,'ACT'))
    EQ_DEMSH(MR,PP(t),c)\$TM_DM(r,c):  VAR_DEM(r,t,c) + SUM(TM_RCJ(r,c,j,bd)\$TM_PP(r,t), BDSIG(bd)*VAR_MELA(r,t,c,j,bd))
                                        =  TM_SHAR(r,t,'ACT',c) * VAR_DEM(r,t,'ACT')
    EQ_DEMAG(TM_PP(MR,t)):  SUM(TM_RCJ(r,c,j,bd)\$TM_DM(r,c),
                                (TM_PREF(r,t,c)*(TM_AGC(r,t,'ACT',c,j,bd)-1) + TM_SHAR(r,t,c,'ACT')) * BDSIG(bd)*VAR_MELA(r,t,c,j,bd)) = 0
    EQ_DEMCES(TM_PP(MR,t),c)\$TM_DM(r,c):  SUM(TM_RCJ(r,c,j,bd), VAR_MELA(r,t,c,j,bd)*TM_STEP(r,c,bd)/ORD(j)/(TM_QREF(r,t,c)*TM_VOC(r,t,c,bd)))
                                            <=  VAR_DEM(r,t,'ACT') / TM_DEM(r,t,'ACT')
    EQ_ENSCST(MR,t):   TM_SCALE_CST*VAR_OBJCOST(r,t) + TM_AMP(r,t) + VAR_SP(r,t,'DEM')\$(NOT TM_PP(r,t)) - TM_SCALE_CST*TM_TAXREV(r,t)
                         =  VAR_EC(r,t) * TM_HDF(r,t)
    EQ_TRDBAL(PP(t)):  SUM(MR(r), VAR_NTX(r,t)) = 0

t runs over the milestone years, PP over all but the first; ORD(j) is the number j. The steps of TM_RCJ and LOGJ are those
of LO and UP only (BDNEQ).
"""
function eq_mlf!(m::Model)
    isempty(m.d.MLF) && return
    (; MR, PP, TLAST, TM_PP, TM_DM, TM_DMAS, TM_CES, TM_RCJ, LOGJ, REG, BDSIG, D, TM_NWT, TM_PWT, TM_DFACT, TM_MIDCON,
        TM_LSC, TM_LOGJOT, TM_LOGVAL, TM_ANNC, TM_UDF, TM_SCALE_UTIL, TM_SCALE_CST, TM_SCALE_NRG, TM_SHAR, TM_CIE,
        TM_PREF, TM_AGC, TM_STEP, TM_QREF, TM_VOC, TM_CESLEV, TM_TSRV, TM_GROWV, TM_DEPR, TM_Y0, TM_L, TM_IVETOL,
        TM_AEEIFAC, TM_DEM, TM_AMP, TM_TAXREV, TM_HDF) = m.d
    (; VAR_UTIL, VAR_C, VAR_INV, VAR_EC, VAR_NTX, VAR_D, VAR_K, VAR_DEM, VAR_SP, VAR_OBJCOST, VAR_MELA) = m.v
    (; ACT, CON, YN, KN, DEM) = m.K
    T = m.T
    ord(j) = Float64(year(m.L, j))                  # ORD(J): the labels of J are 1, 2, 3, ...
    lsc, jot = plain(TM_LSC()), plain(TM_LOGJOT())
    cst, nrg = plain(TM_SCALE_CST()), plain(TM_SCALE_NRG())
    # the steps by (r, cg): TM_RCJ(R,CG,J,BD) -> [(j, bd)]
    rcj = Dict{NTuple{2,Id},Vector{NTuple{2,Id}}}()
    for (r, cg, j, bd) in TM_RCJ
        push!(get!(Vector{NTuple{2,Id}}, rcj, (r, cg)), (j, bd))
    end
    steps(r, cg) = get(rcj, (r, cg), NTuple{2,Id}[])
    pp(t) = t in PP
    dmas = collect(TM_DMAS)
    dm_of(r) = [c for (r2, c) in TM_DM if r2 == r]

    # EQ_UTILP
    util = AE()
    for r in MR, t in T
        w = TM_NWT(r) * TM_PWT(t) * TM_DFACT(r, t)
        add!(util, w * log(TM_MIDCON(r, t)), 1.0)
        for (j, bd) in LOGJ
            add!(util, -w * BDSIG(bd) / lsc, VAR_MELA(r, t, CON, j, bd))
        end
    end
    for r in REG
        r in MR && continue
        for t in T
            add!(util, 3 * TM_ANNC(r, t) * TM_UDF(r, t), 1.0)
            add!(util, -cst * TM_UDF(r, t), VAR_OBJCOST(r, t))
        end
    end
    row!(m, :EQ_UTILP, (), util, ==, VAR_UTIL() * max(1, log(plain(TM_SCALE_UTIL()) * 1000)) / 1000)

    for r in MR, t in T
        # EQ_CONSO
        e = AE(); add!(e, 1.0, VAR_C(r, t)); add!(e, 1.0, VAR_INV(r, t)); add!(e, 1.0, VAR_EC(r, t))
        pp(t) && add!(e, 1.0, VAR_NTX(r, t))
        row!(m, :EQ_CONSO, (r, t), VAR_D(r, t, YN), ==, e)
        # EQ_CONDA
        e = AE(); add!(e, TM_MIDCON(r, t), 1.0)
        for (j, bd) in LOGJ
            add!(e, -TM_MIDCON(r, t) * TM_LOGVAL(j, bd) / lsc, VAR_MELA(r, t, CON, j, bd))
        end
        row!(m, :EQ_CONDA, (r, t), VAR_C(r, t), ==, e)
        # EQ_LOGBD
        e = AE()
        for (j, bd) in LOGJ
            add!(e, 1 / ord(j) / jot, VAR_MELA(r, t, CON, j, bd))
        end
        row!(m, :EQ_LOGBD, (r, t), e, <=, lsc)
    end
    for r in MR, t in T, (cg, cg1) in dmas
        # EQ_MACSH
        e = AE(); add!(e, 1.0, VAR_D(r, t, cg1))
        if (r, t) in TM_PP
            for (j, bd) in steps(r, cg1)
                add!(e, BDSIG(bd), VAR_MELA(r, t, cg1, j, bd))
            end
        end
        row!(m, :EQ_MACSH, (r, t, cg, cg1), e, ==, TM_SHAR(r, t, cg, cg1) / TM_CIE(r, t, cg) * VAR_D(r, t, cg))
    end
    for (r, t) in TM_PP
        r in MR || continue
        # EQ_MACAG
        for cg in TM_CES
            e = AE()
            for (c0, cg1) in dmas
                c0 == cg || continue
                for (j, bd) in steps(r, cg1)
                    k = (TM_PREF(r, t, cg1) * (TM_AGC(r, t, cg, cg1, j, bd) - 1) + TM_SHAR(r, t, cg1, cg)) * BDSIG(bd)
                    add!(e, k, VAR_MELA(r, t, cg1, j, bd))
                end
            end
            row!(m, :EQ_MACAG, (r, t, cg), e, ==, 0.0)
        end
        # EQ_MACES
        for (cg, cg1) in dmas
            e = AE()
            for (j, bd) in steps(r, cg1)
                add!(e, TM_STEP(r, cg1, bd) / ord(j) / (TM_QREF(r, t, cg1) * TM_VOC(r, t, cg1, bd)), VAR_MELA(r, t, cg1, j, bd))
            end
            row!(m, :EQ_MACES, (r, t, cg, cg1), e, <=, 1 / TM_CIE(r, t, cg) / TM_CESLEV(r, t, cg) * VAR_D(r, t, cg))
        end
    end
    for r in MR
        for t in T
            # EQ_KNCAP
            row!(m, :EQ_KNCAP, (r, t), VAR_D(r, t, KN), ==, VAR_K(r, t))
        end
        for k in 1:length(T)-1
            # EQ_MCAP(MR(R),PP(T+1))
            t, t1 = T[k], T[k+1]
            e = AE()
            add!(e, TM_TSRV(r, t), VAR_K(r, t))
            add!(e, D(t1) / 2, VAR_INV(r, t1))
            add!(e, TM_TSRV(r, t) * D(t) / 2, VAR_INV(r, t))
            row!(m, :EQ_MCAP, (r, t1), VAR_K(r, t1), ==, e)
        end
        for t in TLAST
            # EQ_TMC
            row!(m, :EQ_TMC, (r, t), (TM_GROWV(r, t) + TM_DEPR(r)) / 100 * VAR_K(r, t), <=, VAR_INV(r, t))
        end
        for t in T
            pp(t) || continue
            # EQ_IVECBND
            e = AE(); add!(e, 1.0, VAR_INV(r, t)); add!(e, 1.0, VAR_EC(r, t))
            row!(m, :EQ_IVECBND, (r, t), e, <=, TM_Y0(r) * TM_L(r, t)^TM_IVETOL(r))
            # EQ_DD
            e = AE(); add!(e, TM_AEEIFAC(r, t, ACT) / nrg, VAR_D(r, t, ACT)); add!(e, 1 / nrg, VAR_SP(r, t, ACT))
            row!(m, :EQ_DD, (r, t, ACT), VAR_DEM(r, t, ACT), ==, e)
            # EQ_DEMSH
            for c in dm_of(r)
                e = AE(); add!(e, 1.0, VAR_DEM(r, t, c))
                if (r, t) in TM_PP
                    for (j, bd) in steps(r, c)
                        add!(e, BDSIG(bd), VAR_MELA(r, t, c, j, bd))
                    end
                end
                row!(m, :EQ_DEMSH, (r, t, c), e, ==, TM_SHAR(r, t, ACT, c) * VAR_DEM(r, t, ACT))
            end
        end
    end
    for (r, t) in TM_PP
        r in MR || continue
        # EQ_DEMAG
        e = AE()
        for c in dm_of(r), (j, bd) in steps(r, c)
            add!(e, (TM_PREF(r, t, c) * (TM_AGC(r, t, ACT, c, j, bd) - 1) + TM_SHAR(r, t, c, ACT)) * BDSIG(bd), VAR_MELA(r, t, c, j, bd))
        end
        row!(m, :EQ_DEMAG, (r, t), e, ==, 0.0)
        # EQ_DEMCES
        for c in dm_of(r)
            e = AE()
            for (j, bd) in steps(r, c)
                add!(e, TM_STEP(r, c, bd) / ord(j) / (TM_QREF(r, t, c) * TM_VOC(r, t, c, bd)), VAR_MELA(r, t, c, j, bd))
            end
            row!(m, :EQ_DEMCES, (r, t, c), e, <=, 1 / TM_DEM(r, t, ACT) * VAR_DEM(r, t, ACT))
        end
    end
    for r in MR, t in T
        # EQ_ENSCST
        e = AE(); add!(e, cst, VAR_OBJCOST(r, t)); add!(e, TM_AMP(r, t), 1.0)
        (r, t) in TM_PP || add!(e, 1.0, VAR_SP(r, t, DEM))
        add!(e, -cst * TM_TAXREV(r, t), 1.0)
        row!(m, :EQ_ENSCST, (r, t), e, ==, TM_HDF(r, t) * VAR_EC(r, t))
    end
    for t in T
        pp(t) || continue
        # EQ_TRDBAL
        e = AE()
        for r in MR
            add!(e, 1.0, VAR_NTX(r, t))
        end
        row!(m, :EQ_TRDBAL, (t,), e, ==, 0.0)
    end
end

# SPDX-License-Identifier: GPL-3.0-or-later
"""
    EQ_OBJELS (r,bd,cur)                                                        eqobjels.mod, eqobj.mod

Elastic demands (TIMESED YES): the demand of c may move away from its projection in COM_STEP steps of size
COM_VOC * COM_PROJ / COM_STEP each (VAR_ELAST(r,t,c,s,j,bd), bounded by bnd_elas.mod); a decrease (bd = LO) or an
increase (UP) enters the commodity balance (`combal.jl`, eqcombal.mod 67) and its value at the base price of the
earlier run, along the demand curve of elasticity COM_ELAST, is the change of consumer surplus:

    EQ_OBJELS(r,bd,cur)  for bd in LO, UP:
        SUM((t,c,s,j), COEF_PVT(r,t) * COM_BPRICE(r,t,c,s,cur) *
                       (1 - BDSIG(bd)*(ORD(j)-0.5)*COM_VOC(r,t,c,bd)/COM_STEP(r,c,bd))**(1/COM_ELAST(r,t,c,s,bd)) * VAR_ELAST(r,t,c,s,j,bd))
            =  VAR_OBJELS(r,bd,cur)
    (bd = FX:  0 = VAR_OBJELS(r,'FX',cur))

for the regions with elastic demands (OBJELS_R: SUM_OBJ(R,'OBJELS'), eqobj.mod 28) and their currencies RDCUR. The
objective adds SUM(bd, BDSIG(bd) * VAR_OBJELS(r,bd,cur)) (eqobj.mod 89, `eq_obj!`). The preprocessor gives the
coefficients (ELS_COEF, prep/elastic.py).
"""
function eq_objels!(m::Model)
    (; OBJELS_R, RDCUR, ELS_COEF) = m.d
    isempty(OBJELS_R) && return
    isempty(m.d.MLF) || return                          # (not in TIMES_MACRO: mod_equa.tm lists the CORE equations only)
    (; VAR_ELAST, VAR_OBJELS) = m.v
    (; LO, UP, FX) = m.K
    terms = Dict{NTuple{3,Id},AE}()
    for ((r, t, c, s, j, bd, cur), k) in ELS_COEF
        add!(get!(AE, terms, (r, bd, cur)), k, VAR_ELAST(r, t, c, s, j, bd))
    end
    for (r, cur) in RDCUR
        r in OBJELS_R || continue
        for bd in (LO, FX, UP)
            row!(m, :EQ_OBJELS, (r, bd, cur), get(terms, (r, bd, cur), AE()), ==, VAR_OBJELS(r, bd, cur))
        end
    end
end

* SPDX-License-Identifier: GPL-3.0-or-later
* A linear program from a GDX, solved with the LP solver of this GAMS run (LP=...), and its solution to a GDX.
* Written by times_eq/gams/gamslp.py from the arrays of TimesEq.GamsLP.Optimizer; the same file for every model.
*   gams solve_lp.gms --IN=lp.gdx --OUT=solution.gdx lp=<solver> [optfile=1] [threads=<n>] [reslim=<seconds>]
* Input: i rows, j columns; rlo(i), rup(i) the row bounds (lo = up: an equality; one side infinite: an inequality;
* both finite and unequal: a ranged row, written as two inequalities whose marginals are added back); xlo(j), xup(j)
* the column bounds; A(i,j) the coefficients; c(j), c0 the objective; sense 1 to minimise, -1 to maximise.
* Output: x.l, x.m, the marginals of the rows (eqe, eqg, eql), modelstat, solvestat, obj, iterations, seconds, and
* the solver's version line.
$onEmpty
Set i 'rows', j 'columns';
Parameter rlo(i), rup(i), xlo(j), xup(j), A(i,j), c(j);
Scalar c0 'objective constant', sense '1 minimise, -1 maximise';
$gdxIn %IN%
$load i j rlo rup xlo xup A c c0 sense
$gdxIn

Set ie(i) 'equality', ig(i) 'at least rlo', il(i) 'at most rup';
ie(i) = rlo(i) = rup(i);
ig(i) = not ie(i) and rlo(i) > -inf;
il(i) = not ie(i) and rup(i) < inf;

Variable x(j), z;
x.lo(j) = xlo(j);
x.up(j) = xup(j);

Equation eqe(i), eqg(i), eql(i), obj;
eqe(ie).. sum(j$A(ie,j), A(ie,j)*x(j)) =e= rlo(ie);
eqg(ig).. sum(j$A(ig,j), A(ig,j)*x(j)) =g= rlo(ig);
eql(il).. sum(j$A(il,j), A(il,j)*x(j)) =l= rup(il);
obj..     z =e= sum(j$c(j), c(j)*x(j)) + c0;

Model lp / all /;
lp.solprint = 0; lp.limrow = 0; lp.limcol = 0; lp.holdfixed = 0;
if(sense = 1, solve lp using lp minimizing z; else solve lp using lp maximizing z;);

Scalar modelstat, solvestat, objval, iterations, seconds, gentime;
modelstat = lp.modelstat; solvestat = lp.solvestat; objval = z.l;
iterations = lp.iterusd; seconds = lp.resusd; gentime = lp.resgen;
execute_unload '%OUT%', x, eqe, eqg, eql, modelstat, solvestat, objval, iterations, seconds, gentime;

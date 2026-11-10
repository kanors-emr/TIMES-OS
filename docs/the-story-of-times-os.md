<img src="img/kanors-logo.png" alt="KanORS" width="180">

# How TIMES-OS came about

*One reference, and a different way of writing scientific software*

**Dr Amit Kanudia** · KanORS-EMR · November 2026

---

## Thirty years of one TIMES

I am one of the original authors of TIMES, and I built Veda for the people who use it. For three decades the
strength of TIMES has been the abstraction of a whole energy system that the code carries,
refined on hundreds of models, and the community of practitioners who trust it because there is one TIMES, defined
in one place, maintained by people who know it deeply.

That community is mostly made of tool users, not tool builders. Ministries, universities and research teams use TIMES
to answer questions about their energy systems; a small, specialised group keeps the tool itself. This division of
labour is what let TIMES spread across so many countries, and it is worth protecting.

## A new requirement

Over the last decade a new expectation arrived: research funded with public money should be reproducible with
open-source tools. The TIMES code has been open for years, published under an open-source licence; running it still
needed GAMS to build and solve the model, a commercial solver for anything sizeable, and proprietary tools to turn model
workbooks into model inputs.

Two needs followed from it. TIMES teams needed to bid for projects that asked for open tools. And newcomers, above
all in developing countries, needed to be able to try TIMES before committing to licences. Both are needs of the
users, and both are about how TIMES runs, not about what TIMES is.

## From migration to mirroring

ETSAP took the question seriously and began to study how TIMES might move to an open platform. The natural reflex was
the full open-source answer: migrate TIMES into a new language, and grow a community of builders around the new code.

I argued for something narrower. The requirement is about the runtime, not about how TIMES is developed. What TIMES
needs is an open way to run, while TIMES itself, in GAMS, stays the reference, maintained as it is. Around that
reference, open mirrors can be built and held to one strict test: from the same inputs, the same model, entry by
entry. That keeps the most valuable asset TIMES has, a formulation perfected over thirty years.

In July 2025 I set out my view in [*Reflections on the path forward for
ETSAP*](https://www.linkedin.com/pulse/reflections-path-forward-etsap-amit-kanudia-56g9c/). Its first question was
the one I still think matters most: will a new platform be usable in practice, by the existing TIMES community? A
complex port risked the worst of both worlds, too intimidating for newcomers and too incomplete for production use,
so I suggested starting small, with a minimum viable product, and keeping a gatekeeper to hold the flagship version
stable. And I argued that the real frontier lies elsewhere: "The true modeling revolution will come not when everyone
can build a model, but when anyone can reason with one." But none of this answered the urgent need for a
non-proprietary toolchain.

TIMES-OS is my own answer to that first question. It reads the files TIMES users already have, builds
the same model, and writes the same results: there is no new platform to learn. It is complete enough for
production because it follows the reference statement by statement, and it has a gatekeeper because the reference
itself is the gate. A working demonstration, I thought, would say more than any argument.

## From October to November

More than a year of working with AI on data pipelines gave me the courage to try it on model equations. I started on
5 October 2026, as KanORS-EMR began an offsite work week in Goa. I had no idea how far it would go; what happened in
the following weeks was beyond anything I imagined that day. Complete TIMES runs without GAMS came within days, and I
shared my excitement on LinkedIn on 13 October. A first version went to a small group of reviewers at the end of October.
The extensions followed: ancillary services, TIMES-MACRO in its linearised form, elastic demands, the climate module,
the model reduction, stochastic TIMES, and the move to TIMES v4.9.8, the current official release. In November came
1.0.0, the public release, verified on seventeen cases of nine openly licensed models, from 3 thousand to 8.2 million
rows: the same matrix as TIMES in GAMS, the same objective value.

## How it was built

Claude, Anthropic's AI, wrote every line of the code, and I directed: what to build, in what order, and when it was
done.

That took more rigour than writing the code myself, not less. What made it work is that TIMES is a precise,
executable reference. Every part of TIMES-OS follows the GAMS statement it implements, quoted above the code, and a
part counts as done only when TIMES-OS builds the same model as TIMES in GAMS, coefficient by coefficient. The
reference told the AI what the code had to do, and gave both of us a way to prove that it did. Thirty years inside
TIMES told me where to look when it did not.

If you know what you are doing, intimate interaction with the code may not be necessary: the reference and the
evidence carry the weight that reading every line used to carry.

With a precise reference and someone who knows the model, one person can now port a large scientific code
faithfully, work that used to take a team years. I believe this is how serious scientific software will be carried forward from now on. It
is checked the same way whoever writes it.

## What it means

TIMES-OS is a mirror, not a replacement. TIMES in GAMS, maintained under ETSAP, remains the reference, and ETSAP keeps
authority over the formulation and its releases. The main branch of TIMES-OS follows a declared official release and
adds nothing of its own. There is one TIMES; the engine becomes a choice.

For funders, a TIMES model can now run on open-source software from its input files to its results. For newcomers, the
first model costs nothing to run. For the community, thirty years of validation carry over.

What comes next:

- **More open reference models**, published with the results TIMES in GAMS gives for them, as the first seventeen
  cases are in [TIMES-OS-models](https://github.com/kanors-emr/TIMES-OS-models), so that anyone can check the
  agreement for themselves.
- **The open solver on large models.** HiGHS handles the sizes most people start with; making it solve production-size
  TIMES models is the next frontier, and the work has started.
- **ETSAP.** TIMES-OS was built independently, and I hope it will not stay that way. A toolchain that a community
  relies on should rest on the institution behind TIMES, not on one person's conviction. I hope ETSAP will take
  TIMES-OS under its umbrella.

I helped build TIMES thirty years ago. I want it to be usable by anyone, anywhere, who wants to model an energy
system seriously, for the next thirty.

**Dr Amit Kanudia**
Founder, KanORS-EMR · co-author of TIMES · creator of Veda

The code and how to run it: [the README](../README.md). What KanORS-EMR commits to:
[scope and commitments](scope-and-commitments.md).

# PROC CONTENTS / `dictionary.*` cheat sheet

Deep reference for the ground-truth-harvesting step of the sas-data-dictionary
skill. Load this when you need the actual query shapes, column names, or
gotchas -- the top-level SKILL.md just tells you *when* to harvest; this file
tells you *how*.

## Two ways to ask SAS "what's really in this data"

| | `dictionary.*` via PROC SQL | `PROC CONTENTS` |
|---|---|---|
| Shape | ordinary queryable tables | one report (or one OUT= dataset) per data set |
| Best for | scripting: one query covers every table in a library, filter/join/select like any other data | a human skimming one dataset's structure at a time, or details PROC CONTENTS' extended report surfaces (engine, compression, sort info, CRDATE/MODATE formatting) more conveniently than assembling several dictionary views |
| This project's default | **yes** -- `sas_metadata.py` uses this | fallback only |

`sashelp.vcolumn` / `sashelp.vtable` are read-only views over the same
underlying metadata as `dictionary.columns` / `dictionary.tables` -- same
columns, usable from a plain DATA step or PROC SQL without `dictionary.`'s
restriction to PROC SQL. Use `dictionary.*` when you're already in
`proc sql;` (the common case here); reach for `sashelp.*` only if you need
this metadata inside a DATA step.

## The query `sas_metadata.py` runs

```sas
proc sql noprint;
create table work._sdgcols as
  select memname, name, type, length, format, informat, label, varnum
  from dictionary.columns
  where libname='WORK'
  order by memname, varnum;
create table work._sdgtabs as
  select memname, nobs, nvar, label as table_label
  from dictionary.tables
  where libname='WORK' and memtype='DATA';
quit;
```

Column notes:

- **`type`** in `dictionary.columns` comes back as `1` (numeric) or `2`
  (character) in most SAS versions -- not the strings `"num"`/`"char"`.
  `sas_metadata.py` translates this for you; if you write your own query,
  remember to translate it too, or you'll silently mislabel every character
  variable as numeric.
- **`varnum`** is the variable's *creation order* position in the dataset
  (1-based) -- the same order `PROC CONTENTS`' "Variables in Creation Order"
  section lists. This is usually the more useful "position" for documentation
  purposes than the physical byte offset.
- **`libname`/`memname`** are matched as stored -- almost always **uppercase**
  regardless of how the SAS code itself cased the name. Always `.upper()`
  anything you're about to compare against a `dictionary.*` result.
- `dictionary.columns`/`dictionary.tables` only see **libraries currently
  assigned in this SAS session**. If a program's datasets landed in a
  permanent library, that libref must be assigned (via a `LIBNAME`
  statement, either in the program you just submitted or before you query)
  or the dictionary tables simply won't have rows for it -- no error, just
  silently empty.
- `memtype='DATA'` on `dictionary.tables` excludes views/catalogs/indexes
  that would otherwise show up alongside real datasets in the same library.
- Filtering out scratch/temp tables: resist the urge to default-exclude
  underscore-prefixed names. Legacy SAS code (see this project's
  `demo_programs/`) routinely underscore-prefixes its *real* outputs, not
  just genuine scratch tables -- there is no naming convention you can trust
  by default. Harvest everything in the library and let the source-code
  read (which dataset actually gets written to a permanent output, a report,
  or an external file at the end of the program) decide what's a "real"
  output versus an intermediate step, not the name.

## When to actually run the program first

Ground truth only exists once SAS has *materialized* the output datasets --
querying `dictionary.columns` before that just gets you last run's leftovers
or nothing. `sas_metadata.py --run` (the default) submits the program's
source in the current session first, same direction as
`config2-qlora-gpu/oda_harvest.py`'s harvest step. If the program
partially fails (a later PROC step errors out), earlier DATA steps often
still materialized successfully -- harvest whatever's there rather than
treating one error as "nothing to harvest"; `sas_metadata.py` reports SAS log
`ERROR` lines separately from the harvest result for exactly this reason.

Use `--no-run` instead when:

- The code hardcodes paths/librefs that don't exist in your sandbox (very
  common in "poor" legacy code lifted from a production job) and would
  error out before producing anything useful.
- The target datasets already exist in a permanent library from a prior,
  trusted run -- no need to re-execute, just point `--libname` at where
  they already live.
- You deliberately don't want to execute untrusted/unreviewed legacy code
  in your SAS session at all.

`--no-run` gets you real metadata for whatever's already there, at the cost
of not knowing whether the CURRENT version of the source code (the one
you're documenting) still produces that same structure. Note that in the
authored dictionary's `program_summary.notes` field when you use it.

## PROC CONTENTS, if you need it instead

```sas
proc contents data=work.d1 out=work._d1_contents noprint;
run;
```

The OUT= dataset's column names differ from `dictionary.columns`'
(`NAME`, `TYPE`, `LENGTH`, `VARNUM`, `LABEL`, `FORMAT`, `FORMATL`, `FORMATD`,
`INFORMAT`, `INFORML`, `INFORMD`, plus engine/host detail columns) -- don't
assume the two are drop-in interchangeable if you mix approaches. Prefer
`dictionary.columns` for anything scripted; reach for `PROC CONTENTS`
(no OUT=, plain report) only when a human wants to eyeball one dataset
interactively, or when you specifically need the printed report's
engine/compression/index/sort-order detail that isn't in `dictionary.columns`
(check `dictionary.tables` first -- much of that is there too, just under
different column names, e.g. `SORTEDBY`, `COMPRESS`).

## Putting it together with the rest of the pipeline

1. `sas_metadata.py program.sas` -> ground-truth `columns`/`tables` JSON
   (real name/type/length/format/informat/label per column, real nobs/nvar
   per table).
2. `extract.py program.sas` -> static regex allow-list from the source text
   itself (works even with zero SAS connection; also catches macro
   parameters, which dictionary tables have no concept of).
3. `header_extract.py program.sas` -> whatever human-authored context
   exists (often nothing -- see SKILL.md).
4. Claude reads the source + all three of the above, writes the dictionary
   JSON, preferring a ground-truth `label`/`format` over its own inference
   whenever one exists for that variable.
5. `validate_dictionary.py` / `write_dictionary.py` cross-check every
   claimed identifier against the union of (1) and (2) before anything gets
   persisted.

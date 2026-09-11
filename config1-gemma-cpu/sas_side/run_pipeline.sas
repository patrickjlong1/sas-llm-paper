/******************************************************************************
 run_pipeline.sas -- drive sas-doc-gen FROM a SAS session, via X statements.

 DOES NOT WORK ON SAS ONDEMAND FOR ACADEMICS (ODA). ODA runs in a locked-down
 container with the X statement / XCMD disabled by design -- there is no
 shell to escape to. Submitting this on ODA will just log an error like
 "Shell escape is not valid in this SAS session" and stop.

 This is for a full, licensed SAS install (SAS 9 desktop/server, or a Viya
 compute context) where XCMD is enabled -- check with:

     %put %sysfunc(getoption(xcmd));

 If that comes back blank/NOXCMD, ask whoever administers that install to
 enable it (`-xcmd` at server startup, or `options xcmd;` if the install
 policy allows toggling it per-session), or use the ODA path instead: run
 run_demo.sh from a plain terminal on the machine hosting sas-doc-gen, which
 drives SAS the other way around, over saspy -- see DEMO.md.

 What this does: given a SAS program already sitting in WORK-visible source,
 shells out to run it through document_sas.py (the local zero-shot pipeline),
 then reads the resulting markdown doc back into a SAS dataset so you never
 have to leave your SAS session to see the result.

 Edit the three macro variables below for your setup, then submit the whole
 file.
 ******************************************************************************/

%let sasdocgen_dir  = /internal/sas-doc-gen;     /* where this project lives */
%let target_program = &sasdocgen_dir/demo_programs/test1.sas; /* .sas file to document, or omit and pass --dir below */
%let out_dir         = &sasdocgen_dir/out;        /* where document_sas.py writes results */

/* Confirm XCMD is actually on before wasting a run finding out the hard way */
%macro check_xcmd;
  %if %sysfunc(getoption(xcmd)) ne XCMD %then %do;
    %put ERROR: XCMD is not enabled in this SAS session (getoption(xcmd)=%sysfunc(getoption(xcmd))).;
    %put ERROR: This will not work on ODA. See the header comment in this file.;
    %abort cancel;
  %end;
%mend check_xcmd;
%check_xcmd;

/* Shell out to the pipeline. Runs the local zero-shot doc generator (Ollama,
   already running on the box hosting sas-doc-gen) against one program. */
x "cd &sasdocgen_dir && python3 document_sas.py &target_program --out &out_dir";

/* Pull the generated markdown doc back into SAS as one dataset for viewing
   inline, e.g. in SAS Enterprise Guide's results, or `proc print`. */
%macro program_base(path);
  %local slash dot;
  %let slash = %sysfunc(findc(&path, /, b));
  %let dot   = %sysfunc(findc(&path, ., b));
  %sysfunc(substr(&path, %eval(&slash+1), %eval(&dot-&slash-1)))
%mend program_base;

%let base = %program_base(&target_program);

data doc_&base;
  length line $ 2000;
  infile "&out_dir/&base..doc.md" truncover;
  input;
  line = _infile_;
run;

proc print data=doc_&base noobs; run;

/* Optional: also push the accumulated local catalog (program_summary,
   macro_params, data_dictionary) to SAS as real datasets in this same
   session, reusing the connection you're already in -- skip the second
   saspy hop entirely if you're already inside SAS with XCMD on.
   Needs ~/.authinfo to exist for whichever account push_to_oda.py's venv
   Python runs as; see DEMO.md. Uncomment to use: */

/*
x "cd &sasdocgen_dir && /internal/venvs/main/bin/python3 push_to_oda.py --catalog catalog/";
*/

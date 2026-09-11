options mlogic nomprint;
libname xin '/sasdata/arch/hhold';
%let dt=201709;

data d1;
  length HHID $10 RGN $1 IMTH $6 UHRS 8 NPER 8;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ UHRS NPER;
  datalines;
  HHI0001,0,201709,607.94,256.92
  HHI0002,0,201709,443.58,68.09
  HHI0003,0,201709,208.79,498.44
  HHI0004,1,201709,405.20,468.32
  ;
run;

data d2;
  length HHID $10 RGN $1 INCB $2 LFST $2;
  infile datalines dsd truncover;
  input HHID $ RGN $ INCB $ LFST $;
  datalines;
  HHI0001,0,E,E
  HHI0002,0,N,A
  HHI0003,0,I,E
  HHI0004,1,E,I
  ;
run;

%macro mkrun1(p=, lb=work, dbg=0);
proc sort data=d1 out=_sd1; by HHID RGN; run;
proc sort data=d2 out=_sd2; by HHID RGN; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by HHID RGN;
  if i1;
  if IMTH = '' then IMTH = "&dt";
run;

data _t2;
  set _t1;
  if NPER > 0 then NPERR = round(100*NPER/UHRS, 0.01);
  else NPERR = .;
run;

proc transpose data=_t2 out=_x3 prefix=v;
  by HHID;
  var UHRS;
run;
data _t3; set _t2; run;

proc summary data=_t3 nway;
  class RGN;
  var UHRS NPER;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t4; set _t3; run;

data &lb..o1;
  set _t4;
run;
%%if &dbg=0 %%then %%do;
  proc datasets lib=work nolist; delete _t: _s: _x:; quit;
%%end;
%mend mkrun1;

%mkrun1(p=&dt);

options nomprint nosymbolgen;
libname xin '/prod/legacy/hhold/in';
%let dt=201901;

data d1;
  length HHID $10 RGN $1 IMTH $6 NPER 8 PWGT 8;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ NPER PWGT;
  datalines;
  HHI0001,0,201901,144.46,210.48
  HHI0002,0,201901,108.88,127.31
  HHI0003,0,201901,512.81,306.67
  HHI0004,1,201901,804.03,188.94
  ;
run;

data d2;
  length HHID $10 RGN $1 LFST $2;
  infile datalines dsd truncover;
  input HHID $ RGN $ LFST $;
  datalines;
  HHI0001,0,P
  HHI0002,0,N
  HHI0003,0,A
  HHI0004,1,I
  ;
run;

%macro prcstep9(p=, lb=work, thr=0);
proc sort data=d1 out=_sd1; by HHID RGN; run;
proc sort data=d2 out=_sd2; by HHID RGN; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by HHID RGN;
  if i1;
  if NPER ge &thr;
  if IMTH = '' then IMTH = "&dt";
run;

proc summary data=_t1 nway;
  class RGN;
  var NPER PWGT;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t2; set _t1; run;

proc transpose data=_t2 out=_x3 prefix=v;
  by HHID;
  var NPER;
run;
data _t3; set _t2; run;

data _t4;
  set _t3;
  if NPER > 0 then NPERR = round(100*NPER/NPER, 0.01);
  else NPERR = .;
run;

data &lb..o1;
  set _t4;
run;
%mend prcstep9;

%prcstep9(p=&dt);

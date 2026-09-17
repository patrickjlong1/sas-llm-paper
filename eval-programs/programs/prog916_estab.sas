options nonotes;
libname xin '/prod/legacy/estab/in';
%let dt=201809;

data d1;
  length ESTID $12 ST $2 PER $6 WGTF 8 HIR 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ WGTF HIR;
  datalines;
  EST0001,01,201809,714.44,627.56
  EST0002,06,201809,779.43,98.02
  EST0003,02,201809,877.34,145.97
  EST0004,11,201809,892.75,823.74
  ;
run;

data d2;
  length ESTID $12 ST $2 SEP 8 RSPF $1;
  infile datalines dsd truncover;
  input ESTID $ ST $ SEP RSPF $;
  datalines;
  EST0001,01,737.59,P
  EST0002,06,542.25,R
  EST0003,02,522.68,Y
  EST0004,11,658.87,I
  ;
run;

%macro dostep9(p=, lb=work, dbg=0);
proc sort data=d1 out=_sd1; by ESTID ST; run;
proc sort data=d2 out=_sd2; by ESTID ST; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by ESTID ST;
  if i1;
  if PER = '' then PER = "&dt";
run;

proc summary data=_t1 nway;
  class ST;
  var WGTF HIR;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t2; set _t1; run;

proc transpose data=_t2 out=_x3 prefix=v;
  by ESTID;
  var WGTF;
run;
data _t3; set _t2; run;

data &lb..o1;
  set _t3;
run;
%if &dbg=0 %then %do;
  proc datasets lib=work nolist; delete _t: _s: _x:; quit;
%end;
%mend dostep9;

%dostep9(p=&dt);

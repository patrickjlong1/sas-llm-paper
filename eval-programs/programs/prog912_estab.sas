options validvarname=v7;
libname xin '/prod/legacy/estab/in';
%let dt=202004;

data d1;
  length ESTID $12 ST $2 PER $6 SEP 8 WGTF 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ SEP WGTF;
  datalines;
  EST0001,01,202004,80.00,690.94
  EST0002,06,202004,91.60,255.52
  EST0003,02,202004,540.20,36.09
  EST0004,11,202004,438.79,87.64
  ;
run;

data d2;
  length ESTID $12 ST $2 EMPL 8 JO 8 HIR 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ EMPL JO HIR;
  datalines;
  EST0001,01,548.07,546.85,140.56
  EST0002,06,644.08,212.83,411.07
  EST0003,02,408.48,51.46,42.57
  EST0004,11,289.33,337.38,392.57
  ;
run;

data d3;
  length ESTID $12 ST $2 PER $6 SEP 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ SEP;
  datalines;
  EST0001,01,202004,796.94
  EST0002,06,202004,861.38
  EST0003,02,202004,136.98
  EST0004,11,202004,253.63
  ;
run;

%macro mkrun3(p=, lb=work, thr=10, dbg=0);
proc sort data=d1 out=_sd1; by ESTID ST; run;
proc sort data=d2 out=_sd2; by ESTID ST; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by ESTID ST;
  if i1;
  if SEP ge &thr;
  if PER = '' then PER = "&dt";
run;

proc summary data=_t1 nway;
  class ST;
  var SEP WGTF;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t2; set _t1; run;

data _t3;
  set _t2;
  if SEP > 0 then SEPR = round(100*SEP/SEP, 0.01);
  else SEPR = .;
run;

proc transpose data=_t3 out=_x4 prefix=v;
  by ESTID;
  var SEP;
run;
data _t4; set _t3; run;

data &lb..o1;
  set _t4;
run;
%%if &dbg=0 %%then %%do;
  proc datasets lib=work nolist; delete _t: _s: _x:; quit;
%%end;
%mend mkrun3;

%mkrun3(p=&dt);

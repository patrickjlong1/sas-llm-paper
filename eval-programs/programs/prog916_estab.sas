options mlogic nomprint;
libname xin '/prod/legacy/estab/in';
%let dt=201905;

data d1;
  length ESTID $12 ST $2 PER $6 SEP 8 WGTF 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ SEP WGTF;
  datalines;
  EST0001,01,201905,789.92,307.48
  EST0002,06,201905,61.29,656.13
  EST0003,02,201905,480.40,108.72
  EST0004,11,201905,372.84,104.21
  ;
run;

data d2;
  length ESTID $12 ST $2 EMPL 8 JO 8 HIR 8 RSPF $1;
  infile datalines dsd truncover;
  input ESTID $ ST $ EMPL JO HIR RSPF $;
  datalines;
  EST0001,01,826.35,283.50,494.02,P
  EST0002,06,185.80,414.16,359.94,N
  EST0003,02,618.67,604.31,78.07,R
  EST0004,11,289.55,52.88,681.86,N
  ;
run;

%macro estab_run(p=, lb=work, thr=10);
proc sort data=d1 out=s_d1; by ESTID ST; run;
proc sort data=d2 out=s_d2; by ESTID ST; run;

data sel;
  merge s_d1(in=i1) s_d2(in=i2);
  by ESTID ST;
  if i1;
  if SEP ge &thr;
  if PER = '' then PER = "&p";
  if EMPL > 0 then HIRR = round(100*HIR/EMPL, 0.01);
  else HIRR = .;
run;

proc summary data=sel nway;
  class ST;
  var WGTF HIR;
  output out=agg1(drop=_type_ _freq_) mean=;
run;

data &lb..o1;
  set sel;
run;
%mend estab_run;

%estab_run(p=&dt);
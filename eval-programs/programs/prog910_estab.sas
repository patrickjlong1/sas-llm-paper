options validvarname=v7;
libname xin '/prod/legacy/estab/in';
%let dt=201912;

data d1;
  length ESTID $12 ST $2 PER $6 JO 8 WGTF 8 RSPF $1;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ JO WGTF RSPF $;
  datalines;
  EST0001,01,201912,605.18,77.36,R
  EST0002,06,201912,228.64,345.03,N
  EST0003,02,201912,74.41,512.47,R
  EST0004,11,201912,830.22,958.10,P
  ;
run;

data d2;
  length ESTID $12 ST $2 EMPL 8 HIR 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ EMPL HIR;
  datalines;
  EST0001,01,394.60,840.25
  EST0002,06,588.23,166.32
  EST0003,02,251.85,611.08
  EST0004,11,742.72,377.60
  ;
run;

%macro est_prep(p=, lb=work, thr=5);
proc sort data=d1 out=s_d1; by ESTID ST; run;
proc sort data=d2 out=s_d2; by ESTID ST; run;

data sel;
  merge s_d1(in=i1) s_d2(in=i2);
  by ESTID ST;
  if i1;
  if EMPL ge &thr;
  if PER = '' then PER = "&p";
  if EMPL > 0 then WGTFR = round(100*WGTF/EMPL, 0.01);
  else WGTFR = .;
run;

data &lb..o1;
  set sel;
run;
%mend est_prep;

%est_prep(p=&dt);
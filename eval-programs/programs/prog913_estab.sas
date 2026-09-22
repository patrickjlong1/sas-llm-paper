options nonotes;
libname xin '/prod/legacy/estab/in';
%let dt=202009;

data d1;
  length ESTID $12 ST $2 PER $6 JO 8 SEP 8 RSPF $1;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ JO SEP RSPF $;
  datalines;
  EST0001,01,202009,229.51,461.80,N
  EST0002,06,202009,818.20,50.07,P
  EST0003,02,202009,344.15,219.31,R
  EST0004,11,202009,697.83,863.99,N
  ;
run;

data d2;
  length ESTID $12 ST $2 EMPL 8 WGTF 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ EMPL WGTF;
  datalines;
  EST0001,01,405.23,904.66
  EST0002,06,580.85,36.40
  EST0003,02,720.65,552.83
  EST0004,11,217.96,618.02
  ;
run;

%macro mkest(p=, lb=work, thr=5);
proc sort data=d1 out=s_d1; by ESTID ST; run;
proc sort data=d2 out=s_d2; by ESTID ST; run;

data sel;
  merge s_d1(in=i1) s_d2(in=i2);
  by ESTID ST;
  if i1;
  if WGTF ge &thr;
  if PER = '' then PER = "&p";
  if EMPL > 0 then JOR = round(100*JO/EMPL, 0.01);
  else JOR = .;
run;

proc summary data=sel nway;
  class ST;
  var JO SEP;
  output out=agg1(drop=_type_ _freq_) sum=;
run;

data &lb..o1;
  set sel;
run;
%mend mkest;

%mkest(p=&dt);
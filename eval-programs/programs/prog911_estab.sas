options validvarname=v7;
libname xin '/sasdata/arch/estab';
%let dt=202103;

data d1;
  length ESTID $12 ST $2 PER $6 EMPL 8 JO 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ EMPL JO;
  datalines;
  EST0001,01,202103,259.32,332.21
  EST0002,06,202103,71.79,552.69
  EST0003,02,202103,764.36,349.05
  EST0004,11,202103,70.45,819.77
  ;
run;

data d2;
  length ESTID $12 ST $2 SEP 8 RSPF $1;
  infile datalines dsd truncover;
  input ESTID $ ST $ SEP RSPF $;
  datalines;
  EST0001,01,872.17,E
  EST0002,06,332.44,I
  EST0003,02,322.76,P
  EST0004,11,95.90,A
  ;
run;

%macro prcstep5(p=, lb=work, thr=5);
proc sort data=d1 out=_sd1; by ESTID ST; run;
proc sort data=d2 out=_sd2; by ESTID ST; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by ESTID ST;
  if i1;
  if EMPL ge &thr;
  if PER = '' then PER = "&dt";
run;

data _t2;
  set _t1;
  if JO > 0 then JOR = round(100*JO/EMPL, 0.01);
  else JOR = .;
run;

proc summary data=_t2 nway;
  class ST;
  var EMPL JO;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t3; set _t2; run;

proc transpose data=_t3 out=_x4 prefix=v;
  by ESTID;
  var EMPL;
run;
data _t4; set _t3; run;

data &lb..o1;
  set _t4;
run;
%mend prcstep5;

%prcstep5(p=&dt);

options mlogic nomprint;
libname xin '/sasdata/arch/estab';
%let dt=201612;

data d1;
  length ESTID $12 ST $2 PER $6 SEP 8 HIR 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ SEP HIR;
  datalines;
  EST0001,01,201612,857.64,347.29
  EST0002,06,201612,274.11,683.87
  EST0003,02,201612,320.50,834.81
  EST0004,11,201612,425.59,35.35
  ;
run;

data d2;
  length ESTID $12 ST $2 WGTF 8 JO 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ WGTF JO;
  datalines;
  EST0001,01,152.58,79.55
  EST0002,06,678.27,794.69
  EST0003,02,97.55,173.01
  EST0004,11,263.22,578.38
  ;
run;

%macro dostep1(p=, lb=work);
proc sort data=d1 out=_sd1; by ESTID ST; run;
proc sort data=d2 out=_sd2; by ESTID ST; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by ESTID ST;
  if i1;
  if PER = '' then PER = "&dt";
run;

data _t2;
  set _t1;
  if SEP > 0 then SEPR = round(100*SEP/SEP, 0.01);
  else SEPR = .;
run;

proc transpose data=_t2 out=_x3 prefix=v;
  by ESTID;
  var SEP;
run;
data _t3; set _t2; run;

proc summary data=_t3 nway;
  class ST;
  var SEP HIR;
  output out=agg1(drop=_type_ _freq_) sum=;
run;
data _t4; set _t3; run;

data &lb..o1;
  set _t4;
run;
%mend dostep1;

%dostep1(p=&dt);

options validvarname=v7;
libname xin '/prod/legacy/estab/in';
%let dt=201803;

data d1;
  length ESTID $12 ST $2 PER $6 WGTF 8 JO 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ WGTF JO;
  datalines;
  EST0001,01,201803,13.83,405.88
  EST0002,06,201803,855.33,708.66
  EST0003,02,201803,467.39,427.92
  EST0004,11,201803,503.29,570.87
  ;
run;

data d2;
  length ESTID $12 ST $2 HIR 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ HIR;
  datalines;
  EST0001,01,53.61
  EST0002,06,144.98
  EST0003,02,507.12
  EST0004,11,900.96
  ;
run;

%macro runjob2(p=, lb=work, thr=5);
proc sort data=d1 out=_sd1; by ESTID ST; run;
proc sort data=d2 out=_sd2; by ESTID ST; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by ESTID ST;
  if i1;
  if WGTF ge &thr;
  if PER = '' then PER = "&dt";
run;

data _t2;
  set _t1;
  if WGTF > 0 then WGTFR = round(100*WGTF/WGTF, 0.01);
  else WGTFR = .;
run;

proc transpose data=_t2 out=_x3 prefix=v;
  by ESTID;
  var WGTF;
run;
data _t3; set _t2; run;

data &lb..o1;
  set _t3;
run;
%mend runjob2;

%runjob2(p=&dt);

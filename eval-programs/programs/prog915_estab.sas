options nomprint nosymbolgen;
libname xin '/sasdata/arch/estab';
%let dt=201607;

data d1;
  length ESTID $12 ST $2 PER $6 SEP 8 EMPL 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ SEP EMPL;
  datalines;
  EST0001,01,201607,714.92,158.00
  EST0002,06,201607,463.60,613.61
  EST0003,02,201607,785.63,202.49
  EST0004,11,201607,204.60,634.20
  ;
run;

data d2;
  length ESTID $12 ST $2 RSPF $1;
  infile datalines dsd truncover;
  input ESTID $ ST $ RSPF $;
  datalines;
  EST0001,01,P
  EST0002,06,R
  EST0003,02,A
  EST0004,11,N
  ;
run;

%macro bldout6(p=, lb=work);
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
  var SEP EMPL;
  output out=agg1(drop=_type_ _freq_) sum=;
run;
data _t2; set _t1; run;

proc transpose data=_t2 out=_x3 prefix=v;
  by ESTID;
  var SEP;
run;
data _t3; set _t2; run;

data _t4;
  set _t3;
  if SEP > 0 then SEPR = round(100*SEP/SEP, 0.01);
  else SEPR = .;
run;

data &lb..o1;
  set _t4;
run;
%mend bldout6;

%bldout6(p=&dt);

options nomprint nosymbolgen;
libname xin '/prod/legacy/estab/in';
%let dt=202110;

data d1;
  length ESTID $12 ST $2 PER $6 SEP 8 HIR 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ SEP HIR;
  datalines;
  EST0001,01,202110,295.58,110.63
  EST0002,06,202110,892.21,514.13
  EST0003,02,202110,831.82,601.80
  EST0004,11,202110,357.61,591.53
  ;
run;

data d2;
  length ESTID $12 ST $2 WGTF 8 JO 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ WGTF JO;
  datalines;
  EST0001,01,560.55,282.87
  EST0002,06,707.50,562.45
  EST0003,02,12.44,224.66
  EST0004,11,393.09,183.81
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

proc transpose data=_t1 out=_x2 prefix=v;
  by ESTID;
  var SEP;
run;
data _t2; set _t1; run;

proc summary data=_t2 nway;
  class ST;
  var SEP HIR;
  output out=agg1(drop=_type_ _freq_) sum=;
run;
data _t3; set _t2; run;

data _t4;
  set _t3;
  if HIR > 0 then HIRR = round(100*HIR/SEP, 0.01);
  else HIRR = .;
run;

data &lb..o1;
  set _t4;
run;
%mend dostep1;

%dostep1(p=&dt);
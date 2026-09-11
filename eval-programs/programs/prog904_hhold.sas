options mlogic nomprint;
libname xin '/prod/legacy/hhold/in';
%let dt=201703;

data d1;
  length HHID $10 RGN $1 IMTH $6 PWGT 8 NPER 8;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ PWGT NPER;
  datalines;
  HHI0001,0,201703,458.37,897.77
  HHI0002,0,201703,623.82,122.99
  HHI0003,0,201703,505.98,620.89
  HHI0004,1,201703,495.14,724.76
  ;
run;

data d2;
  length HHID $10 RGN $1 UHRS 8 PRXF $1 INCB $2;
  infile datalines dsd truncover;
  input HHID $ RGN $ UHRS PRXF $ INCB $;
  datalines;
  HHI0001,0,800.45,Y,E
  HHI0002,0,367.37,A,Y
  HHI0003,0,11.69,N,E
  HHI0004,1,764.49,N,N
  ;
run;

data d3;
  length HHID $10 RGN $1 IMTH $6 PWGT 8;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ PWGT;
  datalines;
  HHI0001,0,201703,71.72
  HHI0002,0,201703,589.31
  HHI0003,0,201703,570.66
  HHI0004,1,201703,791.63
  ;
run;

%macro prcstep5(p=, lb=work);
proc sort data=d1 out=_sd1; by HHID RGN; run;
proc sort data=d2 out=_sd2; by HHID RGN; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by HHID RGN;
  if i1;
  if IMTH = '' then IMTH = "&dt";
run;

proc summary data=_t1 nway;
  class RGN;
  var PWGT NPER;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t2; set _t1; run;

data _t3;
  set _t2;
  if NPER > 0 then NPERR = round(100*NPER/PWGT, 0.01);
  else NPERR = .;
run;

proc transpose data=_t3 out=_x4 prefix=v;
  by HHID;
  var PWGT;
run;
data _t4; set _t3; run;

data &lb..o1;
  set _t4;
run;
%mend prcstep5;

%prcstep5(p=&dt);

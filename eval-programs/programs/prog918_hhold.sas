options mlogic nomprint;
libname xin '/sasdata/arch/hhold';
%let dt=202009;

data d1;
  length HHID $10 RGN $1 IMTH $6 UHRS 8 NPER 8;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ UHRS NPER;
  datalines;
  HHI0001,0,202009,507.95,459.24
  HHI0002,0,202009,586.79,854.66
  HHI0003,0,202009,320.90,516.90
  HHI0004,1,202009,418.35,591.63
  ;
run;

data d2;
  length HHID $10 RGN $1 PRXF $1 LFST $2;
  infile datalines dsd truncover;
  input HHID $ RGN $ PRXF $ LFST $;
  datalines;
  HHI0001,0,A,I
  HHI0002,0,P,N
  HHI0003,0,I,Y
  HHI0004,1,P,R
  ;
run;

%macro runjob2(p=, lb=work, thr=5);
proc sort data=d1 out=_sd1; by HHID RGN; run;
proc sort data=d2 out=_sd2; by HHID RGN; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by HHID RGN;
  if i1;
  if UHRS ge &thr;
  if IMTH = '' then IMTH = "&dt";
run;

proc summary data=_t1 nway;
  class RGN;
  var UHRS NPER;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t2; set _t1; run;

proc transpose data=_t2 out=_x3 prefix=v;
  by HHID;
  var UHRS;
run;
data _t3; set _t2; run;

data _t4;
  set _t3;
  if UHRS > 0 then UHRSR = round(100*UHRS/UHRS, 0.01);
  else UHRSR = .;
run;

data &lb..o1;
  set _t4;
run;
%mend runjob2;

%runjob2(p=&dt);

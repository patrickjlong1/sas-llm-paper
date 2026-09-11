options nomprint nosymbolgen;
libname xin '/sasdata/arch/hhold';
%let dt=201712;

data d1;
  length HHID $10 RGN $1 IMTH $6 NPER 8 PWGT 8;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ NPER PWGT;
  datalines;
  HHI0001,0,201712,823.90,510.39
  HHI0002,0,201712,670.66,837.41
  HHI0003,0,201712,409.44,604.68
  HHI0004,1,201712,644.55,693.54
  ;
run;

data d2;
  length HHID $10 RGN $1 INCB $2 PRXF $1;
  infile datalines dsd truncover;
  input HHID $ RGN $ INCB $ PRXF $;
  datalines;
  HHI0001,0,A,R
  HHI0002,0,A,I
  HHI0003,0,R,I
  HHI0004,1,P,P
  ;
run;

data d3;
  length HHID $10 RGN $1 IMTH $6 NPER 8;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ NPER;
  datalines;
  HHI0001,0,201712,596.83
  HHI0002,0,201712,523.70
  HHI0003,0,201712,155.68
  HHI0004,1,201712,721.66
  ;
run;

%macro prcstep4(p=, lb=work);
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
  var NPER PWGT;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t2; set _t1; run;

data _t3;
  set _t2;
  if PWGT > 0 then PWGTR = round(100*PWGT/NPER, 0.01);
  else PWGTR = .;
run;

proc transpose data=_t3 out=_x4 prefix=v;
  by HHID;
  var NPER;
run;
data _t4; set _t3; run;

data &lb..o1;
  set _t4;
run;
%mend prcstep4;

%prcstep4(p=&dt);

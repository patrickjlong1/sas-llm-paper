options validvarname=v7;
libname xin '/prod/legacy/hhold/in';
%let dt=201604;

data d1;
  length HHID $10 RGN $1 IMTH $6 UHRS 8 LFST $2;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ UHRS LFST $;
  datalines;
  HHI0001,0,201604,603.38,E
  HHI0002,0,201604,74.55,I
  HHI0003,0,201604,918.21,U
  HHI0004,1,201604,187.36,N
  ;
run;

data d2;
  length HHID $10 RGN $1 PWGT 8 NPER 8 INCB $2 PRXF $1;
  infile datalines dsd truncover;
  input HHID $ RGN $ PWGT NPER INCB $ PRXF $;
  datalines;
  HHI0001,0,846.12,421.97,B,N
  HHI0002,0,510.38,150.60,E,Y
  HHI0003,0,739.06,586.21,C,N
  HHI0004,1,92.43,97.23,A,Y
  ;
run;

%macro hh_prep(p=, lb=work, thr=0);
proc sort data=d1 out=s_d1; by HHID RGN; run;
proc sort data=d2 out=s_d2; by HHID RGN; run;

data sel;
  merge s_d1(in=i1) s_d2(in=i2);
  by HHID RGN;
  if i1;
  if PWGT ge &thr;
  if IMTH = '' then IMTH = "&p";
  if NPER > 0 then PWGTR = round(100*PWGT/NPER, 0.01);
  else PWGTR = .;
run;

proc summary data=sel nway;
  class RGN;
  var PWGT NPER;
  output out=agg1(drop=_type_ _freq_) mean=;
run;

data &lb..o1;
  set sel;
run;
%mend hh_prep;

%hh_prep(p=&dt);
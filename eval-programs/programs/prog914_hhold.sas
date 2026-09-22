options nonotes;
libname xin '/prod/legacy/hhold/in';
%let dt=202112;

data d1;
  length HHID $10 RGN $1 IMTH $6 PWGT 8 PRXF $1;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ PWGT PRXF $;
  datalines;
  HHI0001,0,202112,99.28,Y
  HHI0002,0,202112,712.92,N
  HHI0003,0,202112,364.75,N
  HHI0004,1,202112,588.13,Y
  ;
run;

data d2;
  length HHID $10 RGN $1 UHRS 8 NPER 8 INCB $2;
  infile datalines dsd truncover;
  input HHID $ RGN $ UHRS NPER INCB $;
  datalines;
  HHI0001,0,448.76,77.29,B
  HHI0002,0,614.39,420.90,E
  HHI0003,0,91.05,688.34,C
  HHI0004,1,352.52,804.60,A
  ;
run;

%macro hh_flat(p=, lb=work, thr=10);
proc sort data=d1 out=s_d1; by HHID RGN; run;
proc sort data=d2 out=s_d2; by HHID RGN; run;

data sel;
  merge s_d1(in=i1) s_d2(in=i2);
  by HHID RGN;
  if i1;
  if UHRS ge &thr;
  if IMTH = '' then IMTH = "&p";
  if NPER > 0 then PWGTR = round(100*PWGT/NPER, 0.01);
  else PWGTR = .;
run;

proc summary data=sel nway;
  class RGN;
  var PWGT NPER;
  output out=agg1(drop=_type_ _freq_) sum=;
run;

data &lb..o1;
  set sel;
run;
%mend hh_flat;

%hh_flat(p=&dt);
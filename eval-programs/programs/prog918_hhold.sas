options validvarname=v7;
libname xin '/prod/legacy/hhold/in';
%let dt=201807;

data d1;
  length HHID $10 RGN $1 IMTH $6 LFST $2 INCB $2;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ LFST $ INCB $;
  datalines;
  HHI0001,0,201807,U,C
  HHI0002,0,201807,I,B
  HHI0003,0,201807,E,A
  HHI0004,1,201807,N,D
  ;
run;

data d2;
  length HHID $10 RGN $1 NPER 8 PWGT 8 PRXF $1;
  infile datalines dsd truncover;
  input HHID $ RGN $ NPER PWGT PRXF $;
  datalines;
  HHI0001,0,571.87,449.73,N
  HHI0002,0,90.11,892.36,Y
  HHI0003,0,315.09,604.51,N
  HHI0004,1,480.44,57.86,Y
  ;
run;

%macro hh_run(p=, lb=work, thr=5);
proc sort data=d1 out=s_d1; by HHID RGN; run;
proc sort data=d2 out=s_d2; by HHID RGN; run;

data sel;
  merge s_d1(in=i1) s_d2(in=i2);
  by HHID RGN;
  if i1;
  if NPER ge &thr;
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
%mend hh_run;

%hh_run(p=&dt);
options nomprint nosymbolgen;
libname xin '/sasdata/arch/estcost';
%let dt=201601;

data d1;
  length RUID $14 IND $6 QTR $6 OWGT 8 WCOST 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ OWGT WCOST;
  datalines;
  RUI0001,IND000,201601,429.73,384.40
  RUI0002,IND000,201601,539.13,23.13
  RUI0003,IND000,201601,67.78,194.27
  RUI0004,IND000,201601,452.52,674.85
  ;
run;

data d2;
  length RUID $14 IND $6 EDTF $1;
  infile datalines dsd truncover;
  input RUID $ IND $ EDTF $;
  datalines;
  RUI0001,IND000,I
  RUI0002,IND000,E
  RUI0003,IND000,P
  RUI0004,IND000,N
  ;
run;

data d3;
  length RUID $14 IND $6 QTR $6 OWGT 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ OWGT;
  datalines;
  RUI0001,IND000,201601,54.67
  RUI0002,IND000,201601,366.72
  RUI0003,IND000,201601,733.31
  RUI0004,IND000,201601,600.64
  ;
run;

%macro prcstep2(p=, lb=work, thr=1);
proc sort data=d1 out=_sd1; by RUID IND; run;
proc sort data=d2 out=_sd2; by RUID IND; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by RUID IND;
  if i1;
  if OWGT ge &thr;
  if QTR = '' then QTR = "&dt";
run;

proc summary data=_t1 nway;
  class IND;
  var OWGT WCOST;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t2; set _t1; run;

data _t3;
  set _t2;
  if OWGT > 0 then OWGTR = round(100*OWGT/OWGT, 0.01);
  else OWGTR = .;
run;

proc transpose data=_t3 out=_x4 prefix=v;
  by RUID;
  var OWGT;
run;
data _t4; set _t3; run;

data &lb..o1;
  set _t4;
run;
%mend prcstep2;

%prcstep2(p=&dt);

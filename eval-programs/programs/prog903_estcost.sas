options nomprint nosymbolgen;
libname xin '/prod/legacy/estcost/in';
%let dt=201807;

data d1;
  length RUID $14 IND $6 QTR $6 OWGT 8 HRSP 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ OWGT HRSP;
  datalines;
  RUI0001,IND000,201807,487.39,439.22
  RUI0002,IND000,201807,23.01,656.53
  RUI0003,IND000,201807,166.48,514.39
  RUI0004,IND000,201807,455.48,9.75
  ;
run;

data d2;
  length RUID $14 IND $6 EDTF $1;
  infile datalines dsd truncover;
  input RUID $ IND $ EDTF $;
  datalines;
  RUI0001,IND000,N
  RUI0002,IND000,A
  RUI0003,IND000,Y
  RUI0004,IND000,Y
  ;
run;

%macro prcstep4(p=, lb=work, thr=0);
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
  var OWGT HRSP;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t2; set _t1; run;

proc transpose data=_t2 out=_x3 prefix=v;
  by RUID;
  var OWGT;
run;
data _t3; set _t2; run;

data _t4;
  set _t3;
  if OWGT > 0 then OWGTR = round(100*OWGT/OWGT, 0.01);
  else OWGTR = .;
run;

data &lb..o1;
  set _t4;
run;
%mend prcstep4;

%prcstep4(p=&dt);

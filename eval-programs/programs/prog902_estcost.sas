options validvarname=v7;
libname xin '/sasdata/arch/estcost';
%let dt=201606;

data d1;
  length RUID $14 IND $6 QTR $6 TCOMP 8 BCOST 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ TCOMP BCOST;
  datalines;
  RUI0001,IND000,201606,396.93,617.75
  RUI0002,IND000,201606,629.13,889.11
  RUI0003,IND000,201606,304.46,578.43
  RUI0004,IND000,201606,697.74,385.04
  ;
run;

data d2;
  length RUID $14 IND $6 HRSP 8 WCOST 8;
  infile datalines dsd truncover;
  input RUID $ IND $ HRSP WCOST;
  datalines;
  RUI0001,IND000,205.91,145.88
  RUI0002,IND000,439.50,370.78
  RUI0003,IND000,693.80,845.98
  RUI0004,IND000,426.47,66.33
  ;
run;

data d3;
  length RUID $14 IND $6 QTR $6 TCOMP 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ TCOMP;
  datalines;
  RUI0001,IND000,201606,656.28
  RUI0002,IND000,201606,893.52
  RUI0003,IND000,201606,131.61
  RUI0004,IND000,201606,72.79
  ;
run;

%macro dostep8(p=, lb=work, thr=5, dbg=0);
proc sort data=d1 out=_sd1; by RUID IND; run;
proc sort data=d2 out=_sd2; by RUID IND; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by RUID IND;
  if i1;
  if TCOMP ge &thr;
  if QTR = '' then QTR = "&dt";
run;

proc transpose data=_t1 out=_x2 prefix=v;
  by RUID;
  var TCOMP;
run;
data _t2; set _t1; run;

proc summary data=_t2 nway;
  class IND;
  var TCOMP BCOST;
  output out=agg1(drop=_type_ _freq_) sum=;
run;
data _t3; set _t2; run;

data _t4;
  set _t3;
  if TCOMP > 0 then TCOMPR = round(100*TCOMP/TCOMP, 0.01);
  else TCOMPR = .;
run;

data &lb..o1;
  set _t4;
run;
%if &dbg=0 %then %do;
  proc datasets lib=work nolist; delete _t: _s: _x:; quit;
%end;
%mend dostep8;

%dostep8(p=&dt);

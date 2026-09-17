options nonotes;
libname xin '/prod/legacy/estcost/in';
%let dt=202112;

data d1;
  length RUID $14 IND $6 QTR $6 WCOST 8 HRSP 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ WCOST HRSP;
  datalines;
  RUI0001,IND000,202112,369.45,107.01
  RUI0002,IND000,202112,715.73,195.36
  RUI0003,IND000,202112,250.43,205.99
  RUI0004,IND000,202112,867.79,381.71
  ;
run;

data d2;
  length RUID $14 IND $6 BCOST 8 EDTF $1;
  infile datalines dsd truncover;
  input RUID $ IND $ BCOST EDTF $;
  datalines;
  RUI0001,IND000,609.91,P
  RUI0002,IND000,679.73,R
  RUI0003,IND000,475.22,N
  RUI0004,IND000,344.12,Y
  ;
run;

%macro runjob4(p=, lb=work, dbg=0);
proc sort data=d1 out=_sd1; by RUID IND; run;
proc sort data=d2 out=_sd2; by RUID IND; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by RUID IND;
  if i1;
  if QTR = '' then QTR = "&dt";
run;

data _t2;
  set _t1;
  if WCOST > 0 then WCOSTR = round(100*WCOST/WCOST, 0.01);
  else WCOSTR = .;
run;

proc summary data=_t2 nway;
  class IND;
  var WCOST HRSP;
  output out=agg1(drop=_type_ _freq_) sum=;
run;
data _t3; set _t2; run;

proc transpose data=_t3 out=_x4 prefix=v;
  by RUID;
  var WCOST;
run;
data _t4; set _t3; run;

data &lb..o1;
  set _t4;
run;
%if &dbg=0 %then %do;
  proc datasets lib=work nolist; delete _t: _s: _x:; quit;
%end;
%mend runjob4;

%runjob4(p=&dt);

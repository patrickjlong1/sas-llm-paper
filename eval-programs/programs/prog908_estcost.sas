options nonotes;
libname xin '/prod/legacy/estcost/in';
%let dt=201910;

data d1;
  length RUID $14 IND $6 QTR $6 BCOST 8 HRSP 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ BCOST HRSP;
  datalines;
  RUI0001,IND000,201910,23.97,293.91
  RUI0002,IND000,201910,829.77,609.53
  RUI0003,IND000,201910,239.70,298.01
  RUI0004,IND000,201910,30.83,886.63
  ;
run;

data d2;
  length RUID $14 IND $6 OWGT 8 WCOST 8 EDTF $1;
  infile datalines dsd truncover;
  input RUID $ IND $ OWGT WCOST EDTF $;
  datalines;
  RUI0001,IND000,34.37,664.58,Y
  RUI0002,IND000,190.87,506.03,A
  RUI0003,IND000,590.28,842.41,R
  RUI0004,IND000,346.87,77.12,I
  ;
run;

data d3;
  length RUID $14 IND $6 QTR $6 BCOST 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ BCOST;
  datalines;
  RUI0001,IND000,201910,402.80
  RUI0002,IND000,201910,555.22
  RUI0003,IND000,201910,679.99
  RUI0004,IND000,201910,502.17
  ;
run;

%macro bldout8(p=, lb=work, dbg=0);
proc sort data=d1 out=_sd1; by RUID IND; run;
proc sort data=d2 out=_sd2; by RUID IND; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by RUID IND;
  if i1;
  if QTR = '' then QTR = "&dt";
run;

proc transpose data=_t1 out=_x2 prefix=v;
  by RUID;
  var BCOST;
run;
data _t2; set _t1; run;

proc summary data=_t2 nway;
  class IND;
  var BCOST HRSP;
  output out=agg1(drop=_type_ _freq_) sum=;
run;
data _t3; set _t2; run;

data _t4;
  set _t3;
  if BCOST > 0 then BCOSTR = round(100*BCOST/BCOST, 0.01);
  else BCOSTR = .;
run;

data &lb..o1;
  set _t4;
run;
%if &dbg=0 %then %do;
  proc datasets lib=work nolist; delete _t: _s: _x:; quit;
%end;
%mend bldout8;

%bldout8(p=&dt);

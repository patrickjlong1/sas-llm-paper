options nomprint nosymbolgen;
libname xin '/sasdata/arch/estcost';
%let dt=202111;

data d1;
  length RUID $14 IND $6 QTR $6 TCOMP 8 BCOST 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ TCOMP BCOST;
  datalines;
  RUI0001,IND000,202111,312.48,183.30
  RUI0002,IND000,202111,38.40,615.66
  RUI0003,IND000,202111,146.71,629.77
  RUI0004,IND000,202111,149.71,5.56
  ;
run;

data d2;
  length RUID $14 IND $6 OWGT 8 WCOST 8 EDTF $1;
  infile datalines dsd truncover;
  input RUID $ IND $ OWGT WCOST EDTF $;
  datalines;
  RUI0001,IND000,435.85,879.53,E
  RUI0002,IND000,92.59,683.17,Y
  RUI0003,IND000,471.63,347.83,E
  RUI0004,IND000,18.91,877.54,P
  ;
run;

%macro bldout2(p=, lb=work, thr=0, dbg=0);
proc sort data=d1 out=_sd1; by RUID IND; run;
proc sort data=d2 out=_sd2; by RUID IND; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by RUID IND;
  if i1;
  if TCOMP ge &thr;
  if QTR = '' then QTR = "&dt";
run;

data _t2;
  set _t1;
  if BCOST > 0 then BCOSTR = round(100*BCOST/TCOMP, 0.01);
  else BCOSTR = .;
run;

proc summary data=_t2 nway;
  class IND;
  var TCOMP BCOST;
  output out=agg1(drop=_type_ _freq_) sum=;
run;
data _t3; set _t2; run;

proc transpose data=_t3 out=_x4 prefix=v;
  by RUID;
  var TCOMP;
run;
data _t4; set _t3; run;

data &lb..o1;
  set _t4;
run;
%if &dbg=0 %then %do;
  proc datasets lib=work nolist; delete _t: _s: _x:; quit;
%end;
%mend bldout2;

%bldout2(p=&dt);

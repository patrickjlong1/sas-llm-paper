options nomprint nosymbolgen;
libname xin '/sasdata/arch/estcost';
%let dt=201909;

data d1;
  length RUID $14 IND $6 QTR $6 OWGT 8 HRSP 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ OWGT HRSP;
  datalines;
  RUI0001,IND000,201909,431.56,788.23
  RUI0002,IND000,201909,165.02,240.74
  RUI0003,IND000,201909,732.88,516.39
  RUI0004,IND000,201909,98.75,372.51
  ;
run;

data d2;
  length RUID $14 IND $6 TCOMP 8 BCOST 8 EDTF $1;
  infile datalines dsd truncover;
  input RUID $ IND $ TCOMP BCOST EDTF $;
  datalines;
  RUI0001,IND000,628.30,119.84,E
  RUI0002,IND000,371.97,680.20,I
  RUI0003,IND000,895.16,243.37,A
  RUI0004,IND000,54.08,585.91,E
  ;
run;

%macro occ_val(p=, lb=work, thr=0);
proc sort data=d1 out=s_d1; by RUID IND; run;
proc sort data=d2 out=s_d2; by RUID IND; run;

data base;
  merge s_d1(in=i1) s_d2(in=i2);
  by RUID IND;
  if i1;
  if OWGT ge &thr;
  if QTR = '' then QTR = "&p";
  if HRSP > 0 then OWGTR = round(100*OWGT/HRSP, 0.01);
  else OWGTR = .;
run;

proc transpose data=base out=wide_ind prefix=v;
  by RUID;
  var OWGT;
run;

proc summary data=base nway;
  class IND;
  var OWGT HRSP;
  output out=agg1(drop=_type_ _freq_) mean=;
run;

data &lb..o1;
  set base;
run;
%mend occ_val;

%occ_val(p=&dt);
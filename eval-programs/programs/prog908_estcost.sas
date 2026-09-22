options nonotes;
libname xin '/prod/legacy/estcost/in';
%let dt=201802;

data d1;
  length RUID $14 IND $6 QTR $6 TCOMP 8 HRSP 8 EDTF $1;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ TCOMP HRSP EDTF $;
  datalines;
  RUI0001,IND000,201802,692.17,333.90,A
  RUI0002,IND000,201802,477.53,866.61,E
  RUI0003,IND000,201802,112.36,590.18,I
  RUI0004,IND000,201802,864.29,477.05,A
  ;
run;

data d2;
  length RUID $14 IND $6 WCOST 8 BCOST 8 OWGT 8;
  infile datalines dsd truncover;
  input RUID $ IND $ WCOST BCOST OWGT;
  datalines;
  RUI0001,IND000,255.18,436.99,209.33
  RUI0002,IND000,729.40,748.13,537.81
  RUI0003,IND000,589.26,23.09,681.19
  RUI0004,IND000,64.75,799.51,44.26
  ;
run;

%macro cost_final(p=, lb=work, dbg=0);
proc sort data=d1 out=s_d1; by RUID IND; run;
proc sort data=d2 out=s_d2; by RUID IND; run;

data base;
  merge s_d1(in=i1) s_d2(in=i2);
  by RUID IND;
  if i1;
  if QTR = '' then QTR = "&p";
  if HRSP > 0 then TCOMPR = round(100*TCOMP/HRSP, 0.01);
  else TCOMPR = .;
run;

proc transpose data=base out=wide_rt prefix=v;
  by RUID;
  var TCOMP;
run;

proc summary data=base nway;
  class IND;
  var TCOMP HRSP;
  output out=agg1(drop=_type_ _freq_) sum=;
run;

data &lb..o1;
  set base;
run;
%if &dbg=0 %then %do;
  proc datasets lib=work nolist; delete s_d1 s_d2 base wide_rt; quit;
%end;
%mend cost_final;

%cost_final(p=&dt);
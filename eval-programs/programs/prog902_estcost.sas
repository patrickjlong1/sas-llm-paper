options validvarname=v7;
libname xin '/prod/legacy/estcost/in';
%let dt=201706;

data d1;
  length RUID $14 IND $6 QTR $6 TCOMP 8 WCOST 8 HRSP 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ TCOMP WCOST HRSP;
  datalines;
  RUI0001,IND000,201706,721.14,408.53,655.37
  RUI0002,IND000,201706,98.76,86.21,334.80
  RUI0003,IND000,201706,540.29,491.72,780.43
  RUI0004,IND000,201706,363.58,270.44,117.29
  ;
run;

data d2;
  length RUID $14 IND $6 BCOST 8 OWGT 8 EDTF $1;
  infile datalines dsd truncover;
  input RUID $ IND $ BCOST OWGT EDTF $;
  datalines;
  RUI0001,IND000,312.61,48.26,A
  RUI0002,IND000,12.55,339.71,E
  RUI0003,IND000,48.57,50.92,I
  RUI0004,IND000,93.14,666.49,A
  ;
run;

%macro cost_lib(p=, lb=work, thr=10, dbg=0);
proc sql;
  create table j1 as
    select a.*,
           b.BCOST,
           b.OWGT,
           b.EDTF
    from d1 a
    inner join d2 b
      on a.RUID = b.RUID and a.IND = b.IND;
quit;

data hold;
  set j1;
  if TCOMP ge &thr;
  if QTR = '' then QTR = "&p";
  if TCOMP > 0 then BCOSTR = round(100*BCOST/TCOMP, 0.01);
  else BCOSTR = .;
run;

proc summary data=hold nway;
  class IND;
  var TCOMP BCOST;
  output out=agg1(drop=_type_ _freq_) sum=;
run;

data &lb..o1;
  set hold;
run;
%if &dbg=0 %then %do;
  proc datasets lib=work nolist; delete j1 hold; quit;
%end;
%mend cost_lib;

%cost_lib(p=&dt);
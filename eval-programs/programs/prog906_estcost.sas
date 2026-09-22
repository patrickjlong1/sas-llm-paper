options mlogic nomprint;
libname xin '/prod/legacy/estcost/in';
%let dt=202107;

data d1;
  length RUID $14 IND $6 QTR $6 BCOST 8 HRSP 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ BCOST HRSP;
  datalines;
  RUI0001,IND000,202107,338.53,423.87
  RUI0002,IND000,202107,871.94,51.60
  RUI0003,IND000,202107,444.62,358.25
  RUI0004,IND000,202107,25.67,177.93
  ;
run;

data d2;
  length RUID $14 IND $6 TCOMP 8 WCOST 8 EDTF $1;
  infile datalines dsd truncover;
  input RUID $ IND $ TCOMP WCOST EDTF $;
  datalines;
  RUI0001,IND000,766.99,300.17,A
  RUI0002,IND000,592.41,520.29,E
  RUI0003,IND000,881.08,47.66,I
  RUI0004,IND000,35.20,398.31,A
  ;
run;

data d3;
  length RUID $14 IND $6 QTR $6 TCOMP 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ TCOMP;
  datalines;
  RUI0001,IND000,202107,689.11
  RUI0002,IND000,202107,501.07
  RUI0003,IND000,202107,925.68
  RUI0004,IND000,202107,19.94
  ;
run;

%macro qtr_cost(p=, lb=work, thr=5, dbg=0);
proc sql;
  create table j1 as
    select a.*,
           b.TCOMP,
           b.WCOST,
           b.EDTF,
           c.TCOMP as P_TCOMP
    from d1 a
    inner join d2 b
      on a.RUID = b.RUID and a.IND = b.IND
    left join d3 c
      on a.RUID = c.RUID and a.IND = c.IND;
quit;

data hold;
  set j1;
  if TCOMP ge &thr;
  if QTR = '' then QTR = "&p";
  TCDIF = TCOMP - P_TCOMP;
  if TCOMP > 0 then TCOMPR = round(100*TCOMP/HRSP, 0.01);
  else TCOMPR = .;
run;

proc summary data=hold nway;
  class IND;
  var TCOMP BCOST;
  output out=agg1(drop=_type_ _freq_) mean=;
run;

data &lb..o1;
  set hold;
run;
%if &dbg=0 %then %do;
  proc datasets lib=work nolist; delete j1 hold; quit;
%end;
%mend qtr_cost;

%qtr_cost(p=&dt);
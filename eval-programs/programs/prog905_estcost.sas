options nonotes;
libname xin '/sasdata/arch/estcost';
%let dt=202002;

data d1;
  length RUID $14 IND $6 QTR $6 WCOST 8 BCOST 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ WCOST BCOST;
  datalines;
  RUI0001,IND000,202002,554.06,218.57
  RUI0002,IND000,202002,706.19,56.33
  RUI0003,IND000,202002,119.94,448.71
  RUI0004,IND000,202002,836.27,101.04
  ;
run;

data d2;
  length RUID $14 IND $6 TCOMP 8 HRSP 8 EDTF $1;
  infile datalines dsd truncover;
  input RUID $ IND $ TCOMP HRSP EDTF $;
  datalines;
  RUI0001,IND000,772.63,563.90,I
  RUI0002,IND000,762.52,98.31,A
  RUI0003,IND000,568.65,671.04,E
  RUI0004,IND000,937.30,420.75,I
  ;
run;

%macro run_cost(p=, lb=work, thr=0);
proc sql;
  create table j1 as
    select a.*,
           b.TCOMP,
           b.HRSP,
           b.EDTF
    from d1 a
    inner join d2 b
      on a.RUID = b.RUID and a.IND = b.IND;
quit;

data hold;
  set j1;
  if WCOST ge &thr;
  if QTR = '' then QTR = "&p";
  if TCOMP > 0 then WCOSTR = round(100*WCOST/TCOMP, 0.01);
  else WCOSTR = .;
run;

proc summary data=hold nway;
  class IND;
  var WCOST BCOST;
  output out=agg1(drop=_type_ _freq_) sum=;
run;

data &lb..o1;
  set hold;
run;
%mend run_cost;

%run_cost(p=&dt);
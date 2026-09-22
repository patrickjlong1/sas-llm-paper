options nomprint nosymbolgen;
libname xin '/sasdata/arch/estcost';
%let dt=201803;

data d1;
  length RUID $14 IND $6 QTR $6 BCOST 8 OWGT 8;
  infile datalines dsd truncover;
  input RUID $ IND $ QTR $ BCOST OWGT;
  datalines;
  RUI0001,IND000,201803,188.60,676.15
  RUI0002,IND000,201803,802.34,349.71
  RUI0003,IND000,201803,65.83,90.07
  RUI0004,IND000,201803,451.68,558.36
  ;
run;

data d2;
  length RUID $14 IND $6 WCOST 8 TCOMP 8 HRSP 8 EDTF $1;
  infile datalines dsd truncover;
  input RUID $ IND $ WCOST TCOMP HRSP EDTF $;
  datalines;
  RUI0001,IND000,74.82,263.42,404.51,E
  RUI0002,IND000,197.34,999.68,271.39,I
  RUI0003,IND000,685.70,721.56,611.82,A
  RUI0004,IND000,431.86,483.24,88.07,E
  ;
run;

%macro ccost_rpt(p=, lb=work, thr=10);
proc sql;
  create table j1 as
    select a.*,
           b.WCOST,
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
  var BCOST OWGT;
  output out=agg1(drop=_type_ _freq_) sum=;
run;

data &lb..o1;
  set hold;
run;
%mend ccost_rpt;

%ccost_rpt(p=&dt);
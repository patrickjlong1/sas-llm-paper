options nonotes;
libname xin '/prod/legacy/estab/in';
%let dt=201701;

data d1;
  length ESTID $12 ST $2 PER $6 EMPL 8 SEP 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ EMPL SEP;
  datalines;
  EST0001,01,201701,833.64,307.81
  EST0002,06,201701,415.18,906.94
  EST0003,02,201701,687.53,140.75
  EST0004,11,201701,270.30,466.32
  ;
run;

data d2;
  length ESTID $12 ST $2 JO 8 HIR 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ JO HIR;
  datalines;
  EST0001,01,75.92,559.60
  EST0002,06,381.44,702.03
  EST0003,02,930.11,313.41
  EST0004,11,524.09,804.38
  ;
run;

data d3;
  length ESTID $12 ST $2 PER $6 EMPL 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ EMPL;
  datalines;
  EST0001,01,201701,762.44
  EST0002,06,201701,449.25
  EST0003,02,201701,590.17
  EST0004,11,201701,238.86
  ;
run;

%macro est_snap(p=, lb=work, thr=5, dbg=0);
proc sql;
  create table j1 as
    select a.*,
           b.JO,
           b.HIR,
           c.EMPL as P_EMPL
    from d1 a
    inner join d2 b
      on a.ESTID = b.ESTID and a.ST = b.ST
    left join d3 c
      on a.ESTID = c.ESTID and a.ST = c.ST;
quit;

data hold;
  set j1;
  if EMPL ge &thr;
  if PER = '' then PER = "&p";
  EMPLDIF = EMPL - P_EMPL;
  if EMPL > 0 then SEPR = round(100*SEP/EMPL, 0.01);
  else SEPR = .;
run;

proc summary data=hold nway;
  class ST;
  var SEP JO;
  output out=agg1(drop=_type_ _freq_) mean=;
run;

data &lb..o1;
  set hold;
run;
%if &dbg=0 %then %do;
  proc datasets lib=work nolist; delete j1 hold; quit;
%end;
%mend est_snap;

%est_snap(p=&dt);
options nonotes;
libname xin '/sasdata/arch/estab';
%let dt=201611;

data d1;
  length ESTID $12 ST $2 PER $6 EMPL 8 SEP 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ EMPL SEP;
  datalines;
  EST0001,01,201611,412.38,117.52
  EST0002,06,201611,689.55,83.10
  EST0003,02,201611,271.90,196.44
  EST0004,11,201611,855.16,64.87
  ;
run;

data d2;
  length ESTID $12 ST $2 JO 8 HIR 8 WGTF 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ JO HIR WGTF;
  datalines;
  EST0001,01,338.20,954.11,199.50
  EST0002,06,501.77,233.63,841.20
  EST0003,02,71.94,70.28,577.31
  EST0004,11,908.45,182.06,11.75
  ;
run;

%macro est_report(p=, lb=work, thr=0);
proc sql;
  create table j1 as
    select a.*,
           b.JO,
           b.HIR,
           b.WGTF
    from d1 a
    left join d2 b
      on a.ESTID = b.ESTID and a.ST = b.ST;
quit;

data hold;
  set j1;
  if EMPL ge &thr;
  if PER = '' then PER = "&p";
  if EMPL > 0 then SEPR = round(100*SEP/EMPL, 0.01);
  else SEPR = .;
run;

proc summary data=hold nway;
  class ST;
  var SEP HIR;
  output out=agg1(drop=_type_ _freq_) sum=;
run;

data &lb..o1;
  set hold;
run;
%mend est_report;

%est_report(p=&dt);
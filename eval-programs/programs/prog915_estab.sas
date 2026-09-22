options nomprint nosymbolgen;
libname xin '/sasdata/arch/estab';
%let dt=201604;

data d1;
  length ESTID $12 ST $2 PER $6 EMPL 8 WGTF 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ EMPL WGTF;
  datalines;
  EST0001,01,201604,340.86,720.05
  EST0002,06,201604,848.13,108.44
  EST0003,02,201604,671.28,536.92
  EST0004,11,201604,127.40,280.37
  ;
run;

data d2;
  length ESTID $12 ST $2 HIR 8 SEP 8 JO 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ HIR SEP JO;
  datalines;
  EST0001,01,410.23,91.77,254.18
  EST0002,06,622.38,770.08,377.61
  EST0003,02,85.63,344.56,955.23
  EST0004,11,931.15,214.20,68.86
  ;
run;

%macro est_aug(p=, lb=work, dbg=0);
proc sql;
  create table j1 as
    select a.*,
           b.HIR,
           b.SEP,
           b.JO
    from d1 a
    inner join d2 b
      on a.ESTID = b.ESTID and a.ST = b.ST;
quit;

data hold;
  set j1;
  if PER = '' then PER = "&p";
  if EMPL > 0 then WGTFR = round(100*WGTF/EMPL, 0.01);
  else WGTFR = .;
run;

proc summary data=hold nway;
  class ST;
  var EMPL HIR;
  output out=agg1(drop=_type_ _freq_) sum=;
run;

data &lb..o1;
  set hold;
run;
%if &dbg=0 %then %do;
  proc datasets lib=work nolist; delete j1 hold; quit;
%end;
%mend est_aug;

%est_aug(p=&dt);
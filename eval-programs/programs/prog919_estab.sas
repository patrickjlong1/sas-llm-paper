options nomprint nosymbolgen;
libname xin '/sasdata/arch/estab';
%let dt=202104;

data d1;
  length ESTID $12 ST $2 PER $6 EMPL 8 HIR 8 JO 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ EMPL HIR JO;
  datalines;
  EST0001,01,202104,99.61,487.27,379.62
  EST0002,06,202104,759.23,55.70,585.44
  EST0003,02,202104,320.48,730.06,21.14
  EST0004,11,202104,503.70,170.85,771.08
  ;
run;

data d2;
  length ESTID $12 ST $2 SEP 8 RSPF $1 WGTF 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ SEP RSPF $ WGTF;
  datalines;
  EST0001,01,82.30,P,631.27
  EST0002,06,769.48,R,413.08
  EST0003,02,337.95,N,741.65
  EST0004,11,161.24,N,52.94
  ;
run;

%macro build_est(p=, lb=work, dbg=0);
proc sort data=d1 out=s_d1; by ESTID ST; run;
proc sort data=d2 out=s_d2; by ESTID ST; run;

data base;
  merge s_d1(in=i1) s_d2(in=i2);
  by ESTID ST;
  if i1;
  if PER = '' then PER = "&p";
  if EMPL > 0 then SEPR = round(100*SEP/EMPL, 0.01);
  else SEPR = .;
run;

proc summary data=base nway;
  class ST;
  var HIR EMPL;
  output out=agg1(drop=_type_ _freq_) sum=;
run;

data &lb..o1;
  set base;
run;
%if &dbg=0 %then %do;
  proc datasets lib=work nolist; delete s_d1 s_d2 base; quit;
%end;
%mend build_est;

%build_est(p=&dt);
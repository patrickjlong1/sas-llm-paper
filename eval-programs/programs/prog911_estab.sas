options mlogic nomprint;
libname xin '/sasdata/arch/estab';
%let dt=201608;

data d1;
  length ESTID $12 ST $2 PER $6 RSPF $1 WGTF 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ RSPF $ WGTF;
  datalines;
  EST0001,01,201608,R,179.85
  EST0002,06,201608,N,260.10
  EST0003,02,201608,R,641.38
  EST0004,11,201608,P,57.73
  ;
run;

data d2;
  length ESTID $12 ST $2 EMPL 8 JO 8 SEP 8 HIR 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ EMPL JO SEP HIR;
  datalines;
  EST0001,01,312.74,470.22,112.69,884.07
  EST0002,06,866.44,62.80,906.25,116.60
  EST0003,02,554.54,428.66,253.18,718.95
  EST0004,11,131.04,744.33,519.27,96.41
  ;
run;

%macro gen_est(p=, lb=work);
proc sql;
  create table j1 as
    select a.*,
           b.EMPL,
           b.JO,
           b.SEP,
           b.HIR
    from d1 a
    inner join d2 b
      on a.ESTID = b.ESTID and a.ST = b.ST;
quit;

data hold;
  set j1;
  if PER = '' then PER = "&p";
  if RSPF in ('R','N');
  if EMPL > 0 then HIRR = round(100*HIR/EMPL, 0.01);
  else HIRR = .;
run;

proc transpose data=hold out=wide_est prefix=v;
  by ESTID;
  var EMPL;
run;

proc summary data=hold nway;
  class ST;
  var EMPL HIR;
  output out=agg1(drop=_type_ _freq_) sum=;
run;

data &lb..o1;
  set hold;
run;
%mend gen_est;

%gen_est(p=&dt);
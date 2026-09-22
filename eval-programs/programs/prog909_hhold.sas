options mlogic nomprint;
libname xin '/sasdata/arch/hhold';
%let dt=202012;

data d1;
  length HHID $10 RGN $1 IMTH $6 INCB $2 LFST $2;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ INCB $ LFST $;
  datalines;
  HHI0001,0,202012,B,U
  HHI0002,0,202012,E,I
  HHI0003,0,202012,A,E
  HHI0004,1,202012,D,N
  ;
run;

data d2;
  length HHID $10 RGN $1 NPER 8 UHRS 8 PWGT 8;
  infile datalines dsd truncover;
  input HHID $ RGN $ NPER UHRS PWGT;
  datalines;
  HHI0001,0,707.14,310.53,61.72
  HHI0002,0,902.46,536.91,402.18
  HHI0003,0,159.37,765.87,824.35
  HHI0004,1,444.85,95.20,151.49
  ;
run;

%macro hh_sched(p=, lb=work);
proc sql;
  create table j1 as
    select a.*,
           b.NPER,
           b.UHRS,
           b.PWGT
    from d1 a
    inner join d2 b
      on a.HHID = b.HHID and a.RGN = b.RGN;
quit;

data hold;
  set j1;
  if IMTH = '' then IMTH = "&p";
  if UHRS > 0 then NPERR = round(100*NPER/UHRS, 0.01);
  else NPERR = .;
run;

proc summary data=hold nway;
  class RGN;
  var UHRS NPER;
  output out=agg1(drop=_type_ _freq_) mean=;
run;

data &lb..o1;
  set hold;
run;
%mend hh_sched;

%hh_sched(p=&dt);
options nonotes;
libname xin '/sasdata/arch/hhold';
%let dt=201607;

data d1;
  length HHID $10 RGN $1 IMTH $6 UHRS 8 PRXF $1;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ UHRS PRXF $;
  datalines;
  HHI0001,0,201607,390.57,N
  HHI0002,0,201607,78.36,Y
  HHI0003,0,201607,845.09,Y
  HHI0004,1,201607,520.46,N
  ;
run;

data d2;
  length HHID $10 RGN $1 NPER 8 LFST $2 PWGT 8 INCB $2;
  infile datalines dsd truncover;
  input HHID $ RGN $ NPER LFST $ PWGT INCB $;
  datalines;
  HHI0001,0,583.16,U,224.91,B
  HHI0002,0,278.40,I,348.75,A
  HHI0003,0,64.97,E,897.53,D
  HHI0004,1,437.12,N,96.20,C
  ;
run;

%macro hhold_std(p=, lb=work, dbg=0);
proc sql;
  create table j1 as
    select a.*,
           b.NPER,
           b.LFST,
           b.PWGT,
           b.INCB
    from d1 a
    inner join d2 b
      on a.HHID = b.HHID and a.RGN = b.RGN;
quit;

data hold;
  set j1;
  if IMTH = '' then IMTH = "&p";
  if NPER > 0 then UHRSR = round(100*UHRS/NPER, 0.01);
  else UHRSR = .;
run;

proc transpose data=hold out=wide_hh prefix=v;
  by HHID;
  var UHRS;
run;

proc summary data=hold nway;
  class RGN;
  var UHRS NPER;
  output out=agg1(drop=_type_ _freq_) sum=;
run;

data &lb..o1;
  set hold;
run;
%if &dbg=0 %then %do;
  proc datasets lib=work nolist; delete j1 hold wide_hh; quit;
%end;
%mend hhold_std;

%hhold_std(p=&dt);
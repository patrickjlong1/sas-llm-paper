options mlogic nomprint;
libname xin '/prod/legacy/hhold/in';
%let dt=201805;

data d1;
  length HHID $10 RGN $1 IMTH $6 NPER 8 PWGT 8 UHRS 8;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ NPER PWGT UHRS;
  datalines;
  HHI0001,0,201805,512.42,388.61,141.93
  HHI0002,0,201805,83.76,774.28,660.50
  HHI0003,0,201805,247.10,215.39,901.77
  HHI0004,1,201805,698.85,497.06,79.44
  ;
run;

data d2;
  length HHID $10 RGN $1 LFST $2 INCB $2 PRXF $1;
  infile datalines dsd truncover;
  input HHID $ RGN $ LFST $ INCB $ PRXF $;
  datalines;
  HHI0001,0,E,B,N
  HHI0002,0,I,C,Y
  HHI0003,0,U,A,N
  HHI0004,1,E,D,Y
  ;
run;

data d3;
  length HHID $10 RGN $1 IMTH $6 NPER 8;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ NPER;
  datalines;
  HHI0001,0,201805,433.15
  HHI0002,0,201805,99.60
  HHI0003,0,201805,205.84
  HHI0004,1,201805,603.27
  ;
run;

%macro hh_core(p=, lb=work);
proc sql;
  create table j1 as
    select a.*,
           b.LFST,
           b.INCB,
           b.PRXF,
           c.NPER as P_NPER
    from d1 a
    inner join d2 b
      on a.HHID = b.HHID and a.RGN = b.RGN
    left join d3 c
      on a.HHID = c.HHID and a.RGN = c.RGN;
quit;

data hold;
  set j1;
  if IMTH = '' then IMTH = "&p";
  NPDIF = NPER - P_NPER;
  if PWGT > 0 then PWGTR = round(100*PWGT/NPER, 0.01);
  else PWGTR = .;
run;

proc summary data=hold nway;
  class RGN;
  var UHRS PWGT;
  output out=agg1(drop=_type_ _freq_) mean=;
run;

data &lb..o1;
  set hold;
run;
%mend hh_core;

%hh_core(p=&dt);
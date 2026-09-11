options validvarname=v7;
libname xin '/sasdata/arch/hhold';
%let dt=201603;

data d1;
  length HHID $10 RGN $1 IMTH $6 UHRS 8 PWGT 8;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ UHRS PWGT;
  datalines;
  HHI0001,0,201603,191.07,436.12
  HHI0002,0,201603,727.00,831.21
  HHI0003,0,201603,51.41,789.23
  HHI0004,1,201603,157.63,877.87
  ;
run;

data d2;
  length HHID $10 RGN $1 LFST $2 PRXF $1;
  infile datalines dsd truncover;
  input HHID $ RGN $ LFST $ PRXF $;
  datalines;
  HHI0001,0,E,A
  HHI0002,0,I,P
  HHI0003,0,P,P
  HHI0004,1,Y,A
  ;
run;

%macro bldout9(p=, lb=work, dbg=0);
proc sort data=d1 out=_sd1; by HHID RGN; run;
proc sort data=d2 out=_sd2; by HHID RGN; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by HHID RGN;
  if i1;
  if IMTH = '' then IMTH = "&dt";
run;

data _t2;
  set _t1;
  if UHRS > 0 then UHRSR = round(100*UHRS/UHRS, 0.01);
  else UHRSR = .;
run;

proc summary data=_t2 nway;
  class RGN;
  var UHRS PWGT;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t3; set _t2; run;

data &lb..o1;
  set _t3;
run;
%%if &dbg=0 %%then %%do;
  proc datasets lib=work nolist; delete _t: _s: _x:; quit;
%%end;
%mend bldout9;

%bldout9(p=&dt);

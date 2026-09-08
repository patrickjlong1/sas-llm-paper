options nomprint nosymbolgen;
libname xin '/prod/legacy/hhold/in';
%let dt=202108;

data d1;
  length HHID $10 RGN $1 IMTH $6 NPER 8 PWGT 8;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ NPER PWGT;
  datalines;
  HHI0001,0,202108,128.65,510.82
  HHI0002,0,202108,433.40,352.59
  HHI0003,0,202108,656.63,366.68
  HHI0004,1,202108,620.51,626.81
  ;
run;

data d2;
  length HHID $10 RGN $1 UHRS 8 INCB $2 LFST $2;
  infile datalines dsd truncover;
  input HHID $ RGN $ UHRS INCB $ LFST $;
  datalines;
  HHI0001,0,842.37,A,I
  HHI0002,0,523.70,N,E
  HHI0003,0,295.70,Y,E
  HHI0004,1,854.92,R,I
  ;
run;

data d3;
  length HHID $10 RGN $1 IMTH $6 NPER 8;
  infile datalines dsd truncover;
  input HHID $ RGN $ IMTH $ NPER;
  datalines;
  HHI0001,0,202108,288.49
  HHI0002,0,202108,529.64
  HHI0003,0,202108,163.14
  HHI0004,1,202108,83.92
  ;
run;

%macro prcstep4(p=, lb=work);
proc sort data=d1 out=_sd1; by HHID RGN; run;
proc sort data=d2 out=_sd2; by HHID RGN; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by HHID RGN;
  if i1;
  if IMTH = '' then IMTH = "&dt";
run;

proc summary data=_t1 nway;
  class RGN;
  var NPER PWGT;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t2; set _t1; run;

data _t3;
  set _t2;
  if NPER > 0 then NPERR = round(100*NPER/NPER, 0.01);
  else NPERR = .;
run;

proc sql noprint;
  create table _t4 as
    select a.*, b.LFST as LFST_b
    from _t3 a left join _sd2 b
      on a.HHID = b.HHID;
quit;

proc transpose data=_t4 out=_x5 prefix=v;
  by HHID;
  var NPER;
run;
data _t5; set _t4; run;

data &lb..o1;
  set _t5;
run;
%mend prcstep4;

%prcstep4(p=&dt);
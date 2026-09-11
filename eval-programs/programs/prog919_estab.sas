options mlogic nomprint;
libname xin '/sasdata/arch/estab';
%let dt=201708;

data d1;
  length ESTID $12 ST $2 PER $6 EMPL 8 HIR 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ EMPL HIR;
  datalines;
  EST0001,01,201708,297.28,265.69
  EST0002,06,201708,808.07,409.23
  EST0003,02,201708,364.57,329.41
  EST0004,11,201708,855.82,702.39
  ;
run;

data d2;
  length ESTID $12 ST $2 SEP 8 RSPF $1;
  infile datalines dsd truncover;
  input ESTID $ ST $ SEP RSPF $;
  datalines;
  EST0001,01,658.86,I
  EST0002,06,439.05,E
  EST0003,02,668.43,P
  EST0004,11,372.16,Y
  ;
run;

%macro bldout5(p=, lb=work, dbg=0);
proc sort data=d1 out=_sd1; by ESTID ST; run;
proc sort data=d2 out=_sd2; by ESTID ST; run;
data _t1;
  merge _sd1(in=i1) _sd2(in=i2);
  by ESTID ST;
  if i1;
  if PER = '' then PER = "&dt";
run;

proc transpose data=_t1 out=_x2 prefix=v;
  by ESTID;
  var EMPL;
run;
data _t2; set _t1; run;

proc summary data=_t2 nway;
  class ST;
  var EMPL HIR;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t3; set _t2; run;

data _t4;
  set _t3;
  if HIR > 0 then HIRR = round(100*HIR/EMPL, 0.01);
  else HIRR = .;
run;

data &lb..o1;
  set _t4;
run;
%%if &dbg=0 %%then %%do;
  proc datasets lib=work nolist; delete _t: _s: _x:; quit;
%%end;
%mend bldout5;

%bldout5(p=&dt);

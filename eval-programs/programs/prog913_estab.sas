options nonotes;
libname xin '/sasdata/arch/estab';
%let dt=201607;

data d1;
  length ESTID $12 ST $2 PER $6 HIR 8 JO 8;
  infile datalines dsd truncover;
  input ESTID $ ST $ PER $ HIR JO;
  datalines;
  EST0001,01,201607,833.82,894.67
  EST0002,06,201607,223.95,803.99
  EST0003,02,201607,180.34,319.56
  EST0004,11,201607,542.40,210.64
  ;
run;

data d2;
  length ESTID $12 ST $2 WGTF 8 RSPF $1;
  infile datalines dsd truncover;
  input ESTID $ ST $ WGTF RSPF $;
  datalines;
  EST0001,01,388.15,Y
  EST0002,06,648.94,Y
  EST0003,02,771.94,Y
  EST0004,11,197.54,I
  ;
run;

%macro bldout9(p=, lb=work);
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
  var HIR;
run;
data _t2; set _t1; run;

data _t3;
  set _t2;
  if HIR > 0 then HIRR = round(100*HIR/HIR, 0.01);
  else HIRR = .;
run;

proc summary data=_t3 nway;
  class ST;
  var HIR JO;
  output out=agg1(drop=_type_ _freq_) mean=;
run;
data _t4; set _t3; run;

data &lb..o1;
  set _t4;
run;
%mend bldout9;

%bldout9(p=&dt);

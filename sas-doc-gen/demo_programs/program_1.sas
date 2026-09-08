/* DATA PROCESSING WORKFLOW */

%macro setup;
    libname _t1_ v9 "%sysget(HOME)";
%mend setup;
%setup;

data _a1;
    do i = 1 to 10000;
        v1 = i;
        v2 = rand("Normal", 50, 10);
        v3 = rand("Uniform") * 100;
        
        if rand("Uniform") > 0.85 then v4 = .;
        else v4 = rand("Normal", 100, 25);
        
        if mod(i, 3) = 0 then c1 = "GRP A";
        else if mod(i, 3) = 1 then c1 = "GRP B";
        else c1 = "GRP C";
        
        if rand("Uniform") > 0.5 then c2 = "M";
        else c2 = "F";
        
        v5 = yrdif(intnx('year', today(), -rand("Uniform")*50, 's'), today(), 'Actual');
        
        output;
    end;
    drop i;
run;

data _a2;
    set _a1;
    where v2 > 25 and v3 < 95;
run;

proc sort data=_a2 out=_a3;
    by c1 c2;
run;

data _b1;
    set _a3;
    by c1 c2;
    
    retain s1 s2 0;
    
    if first.c2 then do;
        s1 = 0;
        s2 = 0;
    end;
    
    s1 + v2;
    if v4 ne . then s2 + v4;
    
    m1 = s1 / v1;
    
    if v5 > 40 then flg = 1;
    else flg = 0;
    
    if v2 > 60 then c3 = "HIGH";
    else if v2 > 40 then c3 = "MED";
    else c3 = "LOW";
run;

proc summary data=_b1 nway;
    class c1 c2 c3;
    var v2 v3 v4 v5;
    output out=_s1 
        mean(v2 v3 v4 v5)=m_v2 m_v3 m_v4 m_v5
        std(v2 v3 v4 v5)=s_v2 s_v3 s_v4 s_v5
        n(v2)=n_v2;
run;

data _s2;
    set _s1;
    where n_v2 > 5;
    
    t_val = (m_v2 - 50) / (s_v2 / sqrt(n_v2));
    p_val = (1 - probt(abs(t_val), n_v2 - 1)) * 2;
run;

%macro m1(in, out, v, c);
    proc sort data=&in out=_tmp1;
        by &c;
    run;
    
    data &out;
        set _tmp1;
        by &c;
        retain _mx _mn;
        if first.&c then do;
            _mx = -999999;
            _mn = 999999;
        end;
        if &v > _mx and &v ne . then _mx = &v;
        if &v < _mn and &v ne . then _mn = &v;
        if last.&c;
        keep &c _mx _mn;
    run;
%mend m1;

%m1(_b1, _ex1, v2, c1);
%m1(_b1, _ex2, v3, c1);

data _j1;
    merge _ex1(rename=(_mx=mx2 _mn=mn2)) _ex2(rename=(_mx=mx3 _mn=mn3));
    by c1;
run;

data _b2;
    merge _b1(in=in1) _j1(in=in2);
    by c1;
    if in1;
    
    nv2 = (v2 - mn2) / (mx2 - mn2);
    nv3 = (v3 - mn3) / (mx3 - mn3);
    
    sc1 = (nv2 * 0.4) + (nv3 * 0.6);
run;

proc rank data=_b2 out=_r1 groups=10;
    var sc1;
    ranks r_sc1;
run;

data _final1;
    set _r1;
    if r_sc1 >= 7 then top_f = 1;
    else top_f = 0;
run;

proc glm data=_final1 noprintout;
    class c1 c2;
    model sc1 = c1 c2 v5 / solution;
    ods output ParameterEstimates=_pe1;
quit;

data _pe2;
    set _pe1;
    where Probt < 0.05;
run;

filename _f1 "%sysget(HOME)/out_dat.txt";
data _null_;
    set _final1(obs=100);
    file _f1;
    put c1 $6. c2 $2. v1 6. v2 8.2 v3 8.2 sc1 8.4 r_sc1 2.;
run;

proc transpose data=_s2 out=_tr1(rename=(_name_=var_nm));
    by c1 c2;
    var m_v2 m_v3 m_v4 m_v5;
run;

proc transpose data=_s2 out=_tr2(rename=(_name_=var_nm));
    by c1 c2;
    var s_v2 s_v3 s_v4 s_v5;
run;

data _tr3;
    merge _tr1(rename=(col1=mean_val)) _tr2(rename=(col1=std_val));
    by c1 c2 var_nm;
    
    lbl_var = substr(var_nm, 3, 2);
run;

%macro c_loop;
    %do i = 1 %to 3;
        %if &i = 1 %then %let g = GRP A;
        %if &i = 2 %then %let g = GRP B;
        %if &i = 3 %then %let g = GRP C;
        
        data _g&i;
            set _final1;
            where c1 = "&g";
        run;
        
        proc corr data=_g&i noprint outP=_cr&i;
            var v2 v3 v5 sc1;
        run;
    %end;
%mend c_loop;
%c_loop;

data _all_cr;
    set _cr1(in=i1) _cr2(in=i2) _cr3(in=i3);
    length src $10;
    if i1 then src = "GRP A";
    if i2 then src = "GRP B";
    if i3 then src = "GRP C";
    where _TYPE_ = "CORR";
run;

proc sort data=_final1 out=_s_age;
    by v5;
run;

data _age_g;
    set _s_age;
    retain g_cnt 0;
    by v5;
    
    g_cnt + 1;
    
    if v5 <= 25 then age_cat = "Y";
    else if v5 <= 45 then age_cat = "M";
    else age_cat = "O";
run;

proc freq data=_age_g noprint;
    tables age_cat * top_f / out=_fr_out;
run;

data _final_metrics;
    set _fr_out;
    pct_cell = (count / 10000) * 100;
run;

data _chk1;
    set _final1;
    if flg = 1 and top_f = 1 then chk_c = "A";
    else if flg = 1 and top_f = 0 then chk_c = "B";
    else if flg = 0 and top_f = 1 then chk_c = "C";
    else chk_c = "D";
run;

proc freq data=_chk1 noprint;
    tables chk_c / out=_chk_s;
run;

%macro fin_rep(d_in, title);
    proc print data=&d_in(obs=20);
        title "&title";
    run;
%mend fin_rep;

options nodate nonumber;
%fin_rep(_chk_s, Summary Breakdowns);
%fin_rep(_all_cr, Correlation Matrix);
%fin_rep(_tr3, Transposed Variables Structure);

data _null_;
    rc = filename("fclear", "%sysget(HOME)/out_dat.txt");
    if rc = 0 then rc = fdelete("fclear");
run;


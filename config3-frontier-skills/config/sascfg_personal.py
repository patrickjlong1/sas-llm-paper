# sascfg_personal.py -- SASPy config for SAS OnDemand for Academics (ODA)
#
# Copy this next to your saspy install (same dir as sascfg.py) or point
# SASsession(cfgfile=...) at it. sas_metadata.py / push_to_oda.py resolve the
# path automatically -- see PATH note at the bottom of this file.
#
# `java` is pointed at the portable JRE shared by every config in this repo
# (../../jre/, no sudo/system Java needed). Resolution is NOT simply
# relative to this file's own location: saspy's SASsession(cfgfile=...)
# copies this file into a throwaway tempdir before importing it, so
# __file__ at import time points into /tmp, not this repo -- computing
# _project_root from __file__ alone silently resolves to "/" and breaks
# the java path. Callers (sas_metadata.py, push_to_oda.py) set the
# SAS_DOC_GEN_PROJECT_ROOT env var from their OWN __file__ (which saspy
# does not relocate) before opening the session; this file trusts that
# and only falls back to the __file__ guess if it's missing.
#
# The iomhost list below is ALREADY FILLED IN for the account this was set
# up under (US region, usw2 pod). If you're a different ODA account/region,
# see this folder's SETUP.md for how to find your own host list -- that's
# the only thing you should need to change here.
#
# Requirements per SAS: Java 1.8.0_162+, SASPy 3.3.4+ (installed: check with
# /internal/venvs/main/bin/pip show saspy), remote IOM over Java.
#
# Deliberately NOT setting a "classpath" key below -- leave that to saspy's
# own default (built in sasioiom.py, triggered whenever `classpath` is
# absent from this dict). A hand-built classpath here previously listed
# only iomclient/*.jar and broke on any JRE 9+ (Temurin 17, our jre/):
# SAS's IOM protocol needs `org.omg.CORBA.*`, which the JDK carried through
# Java 8 but dropped in JEP 320 -- saspy ships a CORBA back-port
# (java/thirdparty/glassfish-corba-*.jar + pfl-*.jar) and its default
# classpath already includes it; a hand-rolled list here just omitted it,
# producing "NoClassDefFoundError: org/omg/CORBA/COMM_FAILURE" at connect
# time instead of a clear "missing jar" error.

import os
import shutil

import saspy

_project_root = os.environ.get("SAS_DOC_GEN_PROJECT_ROOT") or \
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# config/ -> config3-frontier-skills/ -> sas-doc-gen-project/ (jre/ is shared at the repo root)

def _resolve_java():
    """Prefer the portable JRE bundled at the repo root; fall back to whatever
    `java` is on PATH.

    `jre/` is 136 MB and gitignored, so it exists on the box it was unpacked
    on and NOT in a fresh `git clone` -- which is exactly the situation on
    Colab/Kaggle. Hard-coding the bundled path there produced a SASPy failure
    at connect time pointing at a java binary that was never in the clone.
    Colab/Kaggle sessions run as root and can `apt-get install default-jdk`
    (see each config's SETUP.md), which puts a JRE 9+ on PATH; saspy's own
    default classpath carries the CORBA back-port that JRE needs, so a
    PATH java works there."""
    bundled = os.path.join(_project_root, "jre", "bin", "java")
    if os.path.exists(bundled):
        return bundled
    found = shutil.which("java")
    if found:
        return found
    # Neither: report the bundled path anyway so the error names the thing
    # this repo expects, and SETUP.md's install step is the obvious fix.
    return bundled


SAS_config_names = ["oda"]

oda = {
    # ---- confirmed for this account: US region, usw2 pod (2026-09-10) -------
    # Europe:              odaws01-euw1.oda.sas.com / odaws02-euw1.oda.sas.com
    # Asia Pacific:        odaws01-apse1.oda.sas.com / odaws02-apse1.oda.sas.com
    # (kept for reference in case a different account ever needs this file --
    # if the connection ever gets "No server is available at that port on
    # that machine", double check the region on the ODA dashboard again.)
    "iomhost": [
        "odaws01-usw2.oda.sas.com",
        "odaws02-usw2.oda.sas.com",
        "odaws03-usw2.oda.sas.com",
        "odaws04-usw2.oda.sas.com",
    ],

    # ---- already correct for this project -----------------------------------
    # bundled jre/ when present (this box), else a PATH java (Colab/Kaggle,
    # where jre/ is gitignored and absent) -- see _resolve_java() above.
    "java": _resolve_java(),

    # ---- leave the rest alone ----------------------------------------------
    "iomport": 8591,
    "encoding": "utf-8",
    "authkey": "oda",          # matches the 'oda' line in ~/.authinfo
}

# ---------------------------------------------------------------------------
# Setup still needed before this file does anything -- see this folder's
# SETUP.md for the full walkthrough. Short version:
#
# 1. Create ~/.authinfo (chmod 600) with ONE line -- do this yourself, don't
#    paste your password into a chat session:
#       oda user YOUR_ODA_EMAIL password YOUR_ODA_PASSWORD
#    then: chmod 600 ~/.authinfo
#
# 2. If your ODA account is NOT US-region/usw2, update the iomhost list above
#    (SETUP.md shows where to find your region's hosts on the ODA dashboard).
#
# 3. Run everything through the venv that has saspy installed:
#       /internal/venvs/main/bin/python3 push_to_oda.py ...
#       /internal/venvs/main/bin/python3 sas_metadata.py ...
#
# Licence note: ODA is for academic/non-commercial use. Check current terms
# before pushing anything work-adjacent there.

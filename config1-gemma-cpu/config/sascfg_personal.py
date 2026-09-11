# sascfg_personal.py -- SASPy config for SAS OnDemand for Academics (ODA)
#
# Copy this next to your saspy install (same dir as sascfg.py) or point
# SASsession(cfgfile=...) at it. document_sas.py / push_to_oda.py resolve the
# path automatically -- see PATH note at the bottom of this file.
#
# `java` is pointed at the portable JRE shared by every config in this repo
# (../../jre/, no sudo/system Java needed), resolved below relative to this
# file's own location so it keeps working no matter where this repo is
# checked out.
#
# The iomhost list below is ALREADY FILLED IN for the account this was set
# up under (US region, usw2 pod). If you're a different ODA account/region,
# see the SETUP.md in this folder for how to find your own host list --
# that's the only thing you should need to change here.
#
# Requirements per SAS: Java 1.8.0_162+ (provided: Temurin 17, portable, see
# jre/), SASPy 3.3.4+ (installed: check with
# /internal/venvs/main/bin/pip show saspy), remote IOM over Java. Since ODA
# moved to 9.4M7 the encryption jars must be on the classpath -- they ship
# with saspy, which is why we build the classpath from saspy's own path
# rather than hardcoding it.

import os
import saspy

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# config/ -> config1-gemma-cpu/ -> sas-doc-gen-project/ (jre/ is shared at the repo root)
_jars = os.path.join(os.path.dirname(saspy.__file__), "java", "iomclient")
cpath = os.pathsep.join([
    os.path.join(_jars, "log4j.jar"),
    os.path.join(_jars, "sas.security.sspi.jar"),
    os.path.join(_jars, "sas.core.jar"),
    os.path.join(_jars, "sas.svc.connection.jar"),
    os.path.join(_jars, "sas.rutil.jar"),
    os.path.join(os.path.dirname(saspy.__file__), "java", "saspyiom.jar"),
])

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
    "java": os.path.join(_project_root, "jre", "bin", "java"),

    # ---- leave the rest alone ----------------------------------------------
    "iomport": 8591,
    "encoding": "utf-8",
    "authkey": "oda",          # matches the 'oda' line in ~/.authinfo
    "classpath": cpath,
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
#
# Licence note: ODA is for academic/non-commercial use. Check current terms
# before pushing anything work-adjacent there.

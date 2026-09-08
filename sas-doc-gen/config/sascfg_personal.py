# sascfg_personal.py -- SASPy config for SAS OnDemand for Academics (ODA)
#
# Copy this next to your saspy install (same dir as sascfg.py) or point
# SASsession(cfgfile=...) at it. document_sas.py / push_to_oda.py resolve the
# path automatically -- see PATH note at the bottom of this file.
#
# Adapted from seasug-paper/scripts/sascfg_personal.py, with `java` pointed at
# the portable JRE bundled in this project (no sudo/system Java needed):
# resolved below relative to this file's own location, so it keeps working
# no matter where this repo is checked out.
#
# You should only need to change ONE line, marked CHANGE ME -- the iomhost
# list for your ODA region. Everything else (classpath, java) is already
# wired to files that exist in this repo.
#
# Requirements per SAS: Java 1.8.0_162+ (provided: Temurin 17, portable, see
# jre/), SASPy 3.3.4+ (installed: check with
# /internal/venvs/main/bin/pip show saspy), remote IOM over Java. Since ODA
# moved to 9.4M7 the encryption jars must be on the classpath -- they ship
# with saspy, which is why we build the classpath from saspy's own path
# rather than hardcoding it.

import os
import saspy

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # config/ -> project root
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
    # ---- CHANGE ME: use the host list for YOUR ODA region -------------------
    # US home region:      odaws01-usw2.oda.sas.com ... odaws04-usw2.oda.sas.com
    # Europe:              odaws01-euw1.oda.sas.com / odaws02-euw1.oda.sas.com
    # Asia Pacific:        odaws01-apse1.oda.sas.com / odaws02-apse1.oda.sas.com
    # Look yours up on the ODA dashboard before guessing -- wrong region gives
    # "No server is available at that port on that machine".
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
# Setup still needed before this file does anything (none of this is done
# yet on this box):
#
# 1. Put this file where SASPy's auto-discovery finds it, OR pass it
#    explicitly:
#       saspy.SASsession(cfgfile="/internal/sas-doc-gen/config/sascfg_personal.py")
#    Auto-discovery copy (only if you want to skip cfgfile= everywhere):
#       cp /internal/sas-doc-gen/config/sascfg_personal.py \
#          /internal/venvs/main/lib/python3.12/site-packages/saspy/
#
# 2. Create ~/.authinfo (chmod 600) with ONE line -- do this yourself, don't
#    paste your password into a chat session:
#       oda user YOUR_ODA_EMAIL password YOUR_ODA_PASSWORD
#    then: chmod 600 ~/.authinfo
#
# 3. Fill in the CHANGE ME host list above for your ODA region.
#
# 4. Run everything through the venv that has saspy installed:
#       /internal/venvs/main/bin/python3 push_to_oda.py ...
#
# Licence note: ODA is for academic/non-commercial use. Check current terms
# before pushing anything work-adjacent there.

# sascfg_personal.py -- SASPy config for SAS OnDemand for Academics (ODA),
# for use in a Colab/Kaggle GPU session (see SETUP.md).
#
# Unlike config1-gemma-cpu/ and config3-frontier-skills/ (which bundle a
# portable JRE since this box has no sudo/system Java), this version just
# points at whatever `java` SETUP.md's `apt-get install default-jdk` step
# put on PATH -- Colab/Kaggle sessions have sudo, so there's no reason to
# bundle one here too.
#
# You should only need to change ONE line, marked CHANGE ME -- the iomhost
# list for your ODA region (already filled in below for US-region/usw2).

import os
import shutil

import saspy

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
    # ---- CHANGE ME only if you're NOT US-region/usw2 -------------------------
    # Europe:              odaws01-euw1.oda.sas.com / odaws02-euw1.oda.sas.com
    # Asia Pacific:        odaws01-apse1.oda.sas.com / odaws02-apse1.oda.sas.com
    "iomhost": [
        "odaws01-usw2.oda.sas.com",
        "odaws02-usw2.oda.sas.com",
        "odaws03-usw2.oda.sas.com",
        "odaws04-usw2.oda.sas.com",
    ],

    # ---- already correct for a Colab/Kaggle session after `apt-get install
    # default-jdk` (see SETUP.md) --------------------------------------------
    "java": shutil.which("java") or "/usr/bin/java",

    # ---- leave the rest alone ----------------------------------------------
    "iomport": 8591,
    "encoding": "utf-8",
    "authkey": "oda",          # matches the 'oda' line in ~/.authinfo
    "classpath": cpath,
}

# ---------------------------------------------------------------------------
# Setup still needed -- see this folder's SETUP.md for the full walkthrough:
#   1. !apt-get -qq install default-jdk  (Colab/Kaggle cell)
#   2. Write ~/.authinfo (chmod 600) via Colab Secrets, never a literal in a cell
#   3. Copy this file next to your saspy install (SETUP.md shows the one-liner)
#
# Licence note: ODA is for academic/non-commercial use. Check current terms
# before pushing anything work-adjacent there.

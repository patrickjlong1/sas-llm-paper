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

import shutil

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
    # Deliberately NOT setting "classpath" -- leave it to saspy's own default.
    # A hand-built classpath here previously listed only iomclient/*.jar and
    # broke on any JRE 9+ (which is what `apt-get install default-jdk` gives
    # you on Colab/Kaggle): SAS's IOM protocol needs org.omg.CORBA.*, which
    # the JDK carried through Java 8 but dropped in JEP 320. saspy ships a
    # CORBA back-port and its default classpath already includes it; see
    # config1-gemma-cpu/config/sascfg_personal.py for the full writeup of
    # the "NoClassDefFoundError: org/omg/CORBA/COMM_FAILURE" this caused.
}

# ---------------------------------------------------------------------------
# Setup still needed -- see this folder's SETUP.md for the full walkthrough:
#   1. !apt-get -qq install default-jdk  (Colab/Kaggle cell)
#   2. Write ~/.authinfo (chmod 600) via Colab Secrets, never a literal in a cell
#   3. Copy this file next to your saspy install (SETUP.md shows the one-liner)
#
# Licence note: ODA is for academic/non-commercial use. Check current terms
# before pushing anything work-adjacent there.

# sascfg_personal.py -- SASPy config for SAS OnDemand for Academics
#
# Copy this next to your saspy install (same dir as sascfg.py) or point
# SASsession(cfgfile=...) at it.
#
# You should only need to change the TWO lines marked CHANGE ME.
#
# Requirements per SAS: Java 1.8.0_162+, SASPy 3.3.4+, remote IOM over Java.
# Since ODA moved to 9.4M7 the encryption jars must be on the classpath -- they
# ship with saspy, which is why we build the classpath from saspy's own path
# rather than hardcoding it.

import os
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
    # ---- CHANGE ME 1: use the host list for YOUR ODA region -----------------
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

    # ---- CHANGE ME 2: path to java ------------------------------------------
    # Colab / Linux after `apt-get install default-jdk`: /usr/bin/java
    # Windows: r'C:\Program Files\Java\jdk-11\bin\java.exe'
    "java": "/usr/bin/java",

    # ---- leave the rest alone ----------------------------------------------
    "iomport": 8591,
    "encoding": "utf-8",
    "authkey": "oda",          # matches the 'oda' line in ~/.authinfo
    "classpath": cpath,
}

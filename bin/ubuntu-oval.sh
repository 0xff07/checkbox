#!/bin/bash

if [ -z $1 ]; then
  echo "usage: $0 {output}"
  exit 0
fi

mkdir -p $1 && cd $1

# See also: https://ubuntu.com/security/oval

OVAL_XML=com.ubuntu.$(lsb_release -cs).usn.oval.xml
OVAL_XML_BZ2=$OVAL_XML.bz2
REPORT_HTML=report.html

# 1. Download the compressed XML
wget https://security-metadata.canonical.com/oval/$OVAL_XML_BZ2 &>/dev/null

# 2. Extract the OVAL XML
bunzip2 $OVAL_XML_BZ2

# 3. Generate the report HTML
oscap oval eval --report $REPORT_HTML $OVAL_XML &>/dev/null

oval-report.py --version
oval-report.py --report $REPORT_HTML
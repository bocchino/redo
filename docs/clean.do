#!/bin/sh -e

# ----------------------------------------------------------------------
# clean.do
# ----------------------------------------------------------------------

. ./defs.sh

subdir_targets redo clean
doall rm '*.1' md-to-man
rm_tmp
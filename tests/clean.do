# ----------------------------------------------------------------------
# clean.do
# ----------------------------------------------------------------------

. ./defs.sh

subdir_targets redo clean
rm -f broken shellfile
rm_tmp
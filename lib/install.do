#!/bin/sh -e

# ----------------------------------------------------------------------
# install.do
# Install redo lib files
# ----------------------------------------------------------------------

. ./defs.sh

exec >&2

vars_require_set INSTALL LIBDIR

evald $INSTALL -d $LIBDIR

for src in *.py
do
	dest=`echo $src | sed 's,-,_,g'`
	evald $INSTALL -m 0644 $src $LIBDIR/$dest
done

subdir_targets redo install

evald python -mcompileall $LIBDIR

#!/bin/sh -e

# ----------------------------------------------------------------------
# test.do
# ----------------------------------------------------------------------

redo-ifchange all
redo t/all
[ -n "$DO_BUILT" ] || echo "Don't forget to test 'minimal/do test'" >&2

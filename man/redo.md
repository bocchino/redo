% redo(1) Redo %VERSION%
% Avery Pennarun (*apenwarr@gmail.com*)
% %DATE%

# NAME

redo - rebuild target files when source files have changed

# SYNOPSIS

redo [options...] [targets...]


# DESCRIPTION

redo is a simple yet powerful tool for rebuilding target
files, and any of their dependencies, based on a set of
rules.  The rules are encoded in simple `sh`(1) scripts
called '.do scripts.'

redo supports GNU `make`(1)-style parallel builds using the
`-j` option; in fact, redo's parallel jobserver is compatible
with GNU Make, so redo and make can share build tokens with
each other.  redo can call a sub-make (e.g. to build a
subproject that uses Makefiles) or vice versa (e.g. if a
make-based project needs to build a redo-based subproject).

Unlike make, redo does not have any special syntax of its
own; each *target* is built by running a .do file, which is
simply a shell script that redo executes for you with a
particular environment and command-line arguments.

If no *targets* are specified, redo pretends you specified
exactly one target named `all`.

Note that redo *always* rebuilds the given targets
(although it may skip rebuilding the targets' dependencies
if they are up to date).  If you only want to rebuild
targets that are not up to date, use `redo-ifchange`(1)
instead.

A .do script can call redo recursively to build its
dependencies.


# OPTIONS

-j, --jobs=*maxjobs*
:   execute at most *maxjobs* .do scripts in parallel.  The
    default value is 1.

-d, --debug
:   print dependency checks as they happen.  You can use
    this to figure out why a particular target is/isn't being
    rebuilt when your .do script calls it using
    `redo-ifchange`.

-v, --verbose
:   pass the -v option to /bin/sh when executing scripts. 
    This normally causes the shell to echo the .do script lines
    to stderr as it reads them.  Most shells will print the
    exact source line (e.g. `echo $3`) and not the
    substituted value of variables (e.g. `echo
    mytarget.redo.tmp`).
    
-x, --xtrace
:   pass the -x option to /bin/sh when executing scripts. 
    This normally causes the shell to echo exactly which
    commands are being executed.  Most shells will print
    the substituted variables (e.g. `echo
    mytarget.redo.tmp`) and not the original source line
    (e.g. `echo $3`).
    
-k, --keep-going
:   keep building as many targets as possible even if some
    of them return an error.  If one target fails, any
    target that depends on it also cannot be built, of course.
    
--shuffle
:   randomize the order in which requested targets are
    built.  Normally, if you run `redo a b c`, the targets
    will be built exactly in that order: first `a`, then
    `b`, then `c`.  But if you use `-j`, they might end up
    being built in parallel, so it isn't safe to rely on
    this precise ordering.  Using `--shuffle`, redo will
    build its targets in random order even without `-j`,
    which makes it easier to find accidental dependency
    problems of this sort.  NOTE: if you really just want
    to guarantee that `a` is built, then `b`, then `c`, you
    can just run three `redo` commands consecutively. 
    Because your .do script is just a script, it will not
    be accidentally parallelized.
    
--debug-locks
:   print messages about acquiring, releasing, and waiting
    on locks.  Because redo can be highly parallelized,
    one instance may end up waiting for a target to be
    built by some other instance before it can continue. 
    If you suspect this is causing troubles, use this
    option to see which instance is waiting and when.
    
--debug-pids
:   add the process id of the particular redo instance to each
    output message.  This makes it easier to figure out
    which sub-instance of redo is doing what.


# USAGE

The core of redo is extremely simple.  When you type `redo
targetname`, then it will search for a matching .do file
based on a simple algorithm.  For example, given a target
named `mytarget.a.b.c.d`, redo will look for a .do file in
the following order:

- mytarget.a.b.c.d.do
- default.a.b.c.d.do
- default.b.c.d.do
- default.c.d.do
- default.d.do
- default.do

In all cases, the .do file must be in the same directory as
the target file, or in one of the target's parent
directories.  For example, if given a target named
`../a/b/xtarget.y`, redo will look for a .do file in the
following order:

- $PWD/../a/b/xtarget.y
- $PWD/../a/b/default.y.do
- $PWD/../a/b/default.do
- $PWD/../a/default.y.do
- $PWD/../a/default.do
- $PWD/../default.y.do
- $PWD/../default.do

The first matching .do file is executed as a `/bin/sh`
script.  The .do script is always executed with the current
working directory set to the directory containing the .do
file.  Because of that rule, the
following two commands always have exactly identical
behaviour:

    redo path/to/target
    
    cd path/to && redo target
    
(Note: in `make`(1), these commands have confusingly
different semantics.  The first command would look for a
target named `path/to/target` in `./Makefile`, while the
second command would look for a target named `target` in
`./path/to/Makefile`.  The two Makefiles might give
completely different results, and it's likely that the
first command would have incomplete dependency information. 
redo does not have this problem.)

The three arguments passed to the .do script are:

- $1: the target name (e.g. mytarget.a.b)
- $2: the base name of the target, minus its extension (e.g. mytarget)
- $3: a temporary filename that the .do script should write
  its output to.
  
Instead of using $3, the .do script may also write the
produced data to stdout.

If the .do file is in the same directory as the target, $1
is guaranteed to be a simple filename (with no path
component).  If the .do file is in a parent directory of
the target, $1 and $3 will be relative paths (i.e. will
contain slashes).

redo is designed to update its targets atomically, and only
if the do script succeeds (i.e. returns a zero exit code). 
Thus, you should never write directly to the target file,
only to $3 or stdout.

Normally, a .do script will call other .do scripts
recursively, by running either `redo` (which will always
build the sub-target) or `redo-ifchange` (which only
rebuilds the sub-target if its dependencies have changed). 

Running `redo-ifchange` is also the way your .do script
declares dependencies on other targets; any target that is
`redo-ifchange`d during your .do script's execution is both
executed (if needed) and added as a dependency.

You may have heard that 'recursive make is considered
harmful' (http://miller.emu.id.au/pmiller/books/rmch/). 
Unlike `make`(1), redo does correct locking, state
management, and global dependency checking, so none of the
arguments in that essay apply to redo.  In fact, recursive
redo is really the only kind of redo.


# RELATED COMMANDS

When writing a .do script, it will probably need to run
one or more of the following commands:

`redo`
:   to build a sub-target unconditionally.

`redo-ifchange` 
:   to build a sub-target only if the sub-target's
    dependencies have changed.

`redo-ifcreate`
:   to tell redo that the current target must be rebuilt if
    a particular file gets created.

`redo-always`
:   to tell redo that the current target must always be
    rebuilt, even if someone calls it using `redo-ifchange`.
    (This might happen if the current target has
    dependencies other than the contents of files.)

`redo-stamp`
:   to tell redo that even though the current target has
    been rebuilt, it may not actually be any different from
    the previous version, so targets that depend on it
    might not need to be rebuilt.  Often used in
    conjunction with `redo-always` to reduce the impact of
    always rebuilding a target.
    
    
# THE DEPENDENCY DATABASE

When `redo` and related commands run, they maintain dependency information in
an sqlite database in a directory called `.redo`. The `.redo` directory is
automatically created the first time you run `redo` and related commands, and it
persists thereafter.

The directory where `.redo` goes is called the *base directory*. By default the
base directory is your home directory. Optionally, you can select the top-level
directory of a project as the base directory for that project. This approach is
more modular, because different projects get different databases. To do this,
create an empty file called `.redo-base` in the top-level directory.

When `redo` runs, it searches in the current directory and upwards for files
named `.redo-base`. If it finds any such file, then the topmost directory
containing such a file is the base directory. That way, if you nest projects
containing `.redo-base`, the base directory is the one associated with the
outermost enclosing project.

You can check an empty file called `.redo-base` into the top-level directory of
any repository that uses `redo`. That way, anyone who clones your repository
and runs `redo` anywhere in it will get the top-level directory of the project
as the base directory, unless he or she already has a `.redo-base` file in
a higher-level directory.

Always use `.redo-base` at the top level of a project (i.e., a set of
interconnected `.do` scripts). It's OK to have unrelated `.do` scripts above
the highest-level `.redo-base` in your system. However, no builds initiated by
those scripts may cross the `.redo-base` boundary. Otherwise you will get
inconsistent behavior: when `redo` is run above `.redo-base`, it will use the
database in your home directory;  and when it is run at or below `.redo-base`,
it will use the database there.

Occasionally the dependency database may get corrupted or become inconsistent.
If that happens, you can reset everything by deleting the `.redo` directory in
the base directory. If you are unsure where the base directory is for
a particular project, run the command `redo-base` anywhere in that project.

For projects that use `.redo-base`, it is useful to include the command `rm -rf
.redo` in the `clean.do` script at the top level. That way, whenever a user
cleans the project, he or she will start with a fresh `.redo` directory the
next time any part of the project is built.


.CREDITS


# SEE ALSO

`sh`(1), `make`(1),
`redo-ifchange`(1), `redo-ifcreate`(1), `redo-always`(1),
`redo-stamp`(1), `redo-base`(1), `redo-remove`(1)

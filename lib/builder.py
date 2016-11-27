# ======================================================================
# builder.py
# Build redo targets
# ======================================================================

import sys, os, errno, stat
import vars, jobs, state
from helpers import unlink, close_on_exec, join
from log import log, log_, debug, debug2, err, warn

# ---------------------------------------------------------------------- 
# Public interface
# ---------------------------------------------------------------------- 

class ImmediateReturn(Exception):
    def __init__(self, rv):
        Exception.__init__(self, "immediate return with exit code %d" % rv)
        self.rv = rv


def main(targets, shouldbuildfunc):
    retcode = [0]  # a list so that it can be reassigned from done()
    if vars.SHUFFLE:
        import random
        random.shuffle(targets)

    locked = []

    def done(t, rv):
        if rv:
            retcode[0] = 1

    # In the first cycle, we just build as much as we can without worrying
    # about any lock contention.  If someone else has it locked, we move on.
    seen = {}
    lock = None
    for t in targets:
        if t in seen:
            continue
        seen[t] = 1
        if not jobs.has_token():
            state.commit()
        jobs.get_token(t)
        if retcode[0] and not vars.KEEP_GOING:
            break
        if not state.check_sane():
            err('.redo directory disappeared; cannot continue.\n')
            retcode[0] = 205
            break
        f = state.File(name=t)
        lock = state.Lock(f.id)
        if vars.UNLOCKED:
            lock.owned = True
        else:
            lock.trylock()
        if not lock.owned:
            if vars.DEBUG_LOCKS:
                log('%s (locked...)\n' % _nice(t))
            locked.append((f.id,t))
        else:
            BuildJob(t, f, lock, shouldbuildfunc, done).start()

    del lock

    # Now we've built all the "easy" ones.  Go back and just wait on the
    # remaining ones one by one.  There's no reason to do it any more
    # efficiently, because if these targets were previously locked, that
    # means someone else was building them; thus, we probably won't need to
    # do anything.  The only exception is if we're invoked as redo instead
    # of redo-ifchange; then we have to redo it even if someone else already
    # did.  But that should be rare.
    while locked or jobs.running():
        state.commit()
        jobs.wait_all()
        # at this point, we don't have any children holding any tokens, so
        # it's okay to block below.
        if retcode[0] and not vars.KEEP_GOING:
            break
        if locked:
            if not state.check_sane():
                err('.redo directory disappeared; cannot continue.\n')
                retcode[0] = 205
                break
            fid,t = locked.pop(0)
            lock = state.Lock(fid)
            lock.trylock()
            while not lock.owned:
                if vars.DEBUG_LOCKS:
                    warn('%s (WAITING)\n' % _nice(t))
                # this sequence looks a little silly, but the idea is to
                # give up our personal token while we wait for the lock to
                # be released; but we should never run get_token() while
                # holding a lock, or we could cause deadlocks.
                jobs.put_token()
                lock.waitlock()
                lock.unlock()
                jobs.get_token(t)
                lock.trylock()
            assert(lock.owned)
            if vars.DEBUG_LOCKS:
                log('%s (...unlocked!)\n' % _nice(t))
            if state.File(name=t).is_failed():
                err('%s: failed in another thread\n' % _nice(t))
                retcode[0] = 2
                lock.unlock()
            else:
                BuildJob(t, state.File(id=fid), lock,
                         shouldbuildfunc, done).start()
    state.commit()
    return retcode[0]


# ----------------------------------------------------------------------
# Private functions
# ----------------------------------------------------------------------

def _default_do_files(filename):
    l = filename.split('.')
    for i in range(1,len(l)+1):
        basename = join('.', l[:i])
        ext = join('.', l[i:])
        if ext: ext = '.' + ext
        yield ("default%s.do" % ext), basename, ext
    

def _possible_do_files(t):
    dirname,filename = os.path.split(t)
    yield (os.path.join(vars.BASE, dirname), "%s.do" % filename,
           '', filename, '')

    # It's important to try every possibility in a directory before resorting
    # to a parent directory.  Think about nested projects: I don't want
    # ../../default.o.do to take precedence over ../default.do, because
    # the former one might just be an artifact of someone embedding my project
    # into theirs as a subdir.  When they do, my rules should still be used
    # for building my project in *all* cases.
    t = os.path.normpath(os.path.join(vars.BASE, t))
    dirname,filename = os.path.split(t)
    dirbits = dirname.split('/')
    for i in range(len(dirbits), -1, -1):
        basedir = join('/', dirbits[:i])
        subdir = join('/', dirbits[i:])
        for dofile,basename,ext in _default_do_files(filename):
            yield (basedir, dofile,
                   subdir, os.path.join(subdir, basename), ext)
        

def _find_do_file(f):
    for dodir,dofile,basedir,basename,ext in _possible_do_files(f.name):
        dopath = os.path.join(dodir, dofile)
        debug2('%s: %s:%s ?\n' % (f.name, dodir, dofile))
        if os.path.exists(dopath):
            f.add_dep('m', dopath)
            return dodir,dofile,basedir,basename,ext
        else:
            f.add_dep('c', dopath)
    return None,None,None,None,None


def _nice(t):
    return state.relpath(t, vars.STARTDIR)


def _try_stat(filename):
    try:
        return os.stat(filename)
    except OSError, e:
        if e.errno == errno.ENOENT:
            return None
        else:
            raise

# ----------------------------------------------------------------------
# Private classes
# ----------------------------------------------------------------------

class BuildJob:
    def __init__(self, t, sf, lock, shouldbuildfunc, donefunc):
        self.t = t  # original target name, not relative to vars.BASE
        self.sf = sf
        tmpbase = t
        while not os.path.isdir(os.path.dirname(tmpbase) or '.'):
            ofs = tmpbase.rfind('/')
            assert(ofs >= 0)
            tmpbase = tmpbase[:ofs] + '__' + tmpbase[ofs+1:]
        self.tmpname1 = '%s.redo1.tmp' % tmpbase
        self.tmpname2 = '%s.redo2.tmp' % tmpbase
        self.lock = lock
        self.shouldbuildfunc = shouldbuildfunc
        self.donefunc = donefunc
        self.before_t = _try_stat(self.t)

    def start(self):
        assert(self.lock.owned)
        try:
            dirty = self.shouldbuildfunc(self.t)
            if not dirty:
                # target doesn't need to be built; skip the whole task
                return self._after2(0)
        except ImmediateReturn, e:
            return self._after2(e.rv)

        if vars.NO_OOB or dirty == True:
            self._start_do()
        else:
            self._start_unlocked(dirty)

    def _start_do(self):
        assert(self.lock.owned)
        t = self.t
        sf = self.sf
        newstamp = sf.read_stamp()
        if (sf.is_generated and
            newstamp != state.STAMP_MISSING and 
            (sf.stamp != newstamp or sf.is_override)):
                state.warn_override(_nice(t))
                sf.set_override()
                sf.set_checked()
                sf.save()
                return self._after2(0)
        if (os.path.exists(t) and not os.path.isdir(t + '/.')
             and not sf.is_generated):
            # an existing source file that was not generated by us.
            # This step is mentioned by djb in his notes.
            # For example, a rule called default.c.do could be used to try
            # to produce hello.c, but we don't want that to happen if
            # hello.c was created by the end user.
            # FIXME: always refuse to redo any file that was modified outside
            # of redo?  That would make it easy for someone to override a
            # file temporarily, and could be undone by deleting the file.
            debug2("-- static (%r)\n" % t)
            sf.set_static()
            sf.save()
            return self._after2(0)
        sf.zap_deps1()
        (dodir, dofile, basedir, basename, ext) = _find_do_file(sf)
        if not dofile:
            if os.path.exists(t):
                sf.set_static()
                sf.save()
                return self._after2(0)
            else:
                err('no rule to make %r\n' % t)
                return self._after2(1)
        unlink(self.tmpname1)
        unlink(self.tmpname2)
        ffd = os.open(self.tmpname1, os.O_CREAT|os.O_RDWR|os.O_EXCL, 0666)
        close_on_exec(ffd, True)
        self.f = os.fdopen(ffd, 'w+')
        # this will run in the dofile's directory, so use only basenames here
        if vars.OLD_ARGS:
            arg1 = basename  # target name (no extension)
            arg2 = ext       # extension (if any), including leading dot
        else:
            arg1 = basename + ext  # target name (including extension)
            arg2 = basename        # target name (without extension)
        argv = ['sh', '-e',
                dofile,
                arg1,
                arg2,
                # temp output file name
                state.relpath(os.path.abspath(self.tmpname2), dodir),
                ]
        if vars.VERBOSE: argv[1] += 'v'
        if vars.XTRACE: argv[1] += 'x'
        if vars.VERBOSE or vars.XTRACE: log_('\n')
        firstline = open(os.path.join(dodir, dofile)).readline().strip()
        if firstline.startswith('#!/'):
            argv[0:2] = firstline[2:].split(' ')
        log('%s\n' % _nice(t))
        self.dodir = dodir
        self.basename = basename
        self.ext = ext
        self.argv = argv
        sf.is_generated = True
        sf.save()
        dof = state.File(name=os.path.join(dodir, dofile))
        dof.set_static()
        dof.save()
        state.commit()
        jobs.start_job(t, self._do_subproc, self._after)

    def _start_unlocked(self, dirty):
        # out-of-band redo of some sub-objects.  This happens when we're not
        # quite sure if t needs to be built or not (because some children
        # look dirty, but might turn out to be clean thanks to checksums). 
        # We have to call redo-unlocked to figure it all out.
        #
        # Note: redo-unlocked will handle all the updating of sf, so we
        # don't have to do it here, nor call _after1.  However, we have to
        # hold onto the lock because otherwise we would introduce a race
        # condition; that's why it's called redo-unlocked, because it doesn't
        # grab a lock.
        argv = ['redo-unlocked', self.sf.name] + [d.name for d in dirty]
        log('(%s)\n' % _nice(self.t))
        state.commit()
        def run():
            os.chdir(vars.BASE)
            os.environ['REDO_DEPTH'] = vars.DEPTH + '  '
            os.execvp(argv[0], argv)
            assert(0)
            # returns only if there's an exception
        def after(t, rv):
            return self._after2(rv)
        jobs.start_job(self.t, run, after)

    def _do_subproc(self):
        # careful: REDO_PWD was the PWD relative to the STARTPATH at the time
        # we *started* building the current target; but that target ran
        # redo-ifchange, and it might have done it from a different directory
        # than we started it in.  So os.getcwd() might be != REDO_PWD right
        # now.
        dn = self.dodir
        newp = os.path.realpath(dn)
        os.environ['REDO_PWD'] = state.relpath(newp, vars.STARTDIR)
        os.environ['REDO_TARGET'] = self.basename + self.ext
        os.environ['REDO_DEPTH'] = vars.DEPTH + '  '
        if dn:
            os.chdir(dn)
        os.dup2(self.f.fileno(), 1)
        os.close(self.f.fileno())
        close_on_exec(1, False)
        if vars.VERBOSE or vars.XTRACE: log_('* %s\n' % ' '.join(self.argv))
        os.execvp(self.argv[0], self.argv)
        assert(0)
        # returns only if there's an exception

    def _after(self, t, rv):
        try:
            state.check_sane()
            rv = self._after1(t, rv)
            state.commit()
        finally:
            self._after2(rv)

    def _after1(self, t, rv):
        f = self.f
        before_t = self.before_t
        after_t = _try_stat(t)
        st1 = os.fstat(f.fileno())
        st2 = _try_stat(self.tmpname2)
        if (after_t and 
            (not before_t or before_t.st_ctime != after_t.st_ctime) and
            not stat.S_ISDIR(after_t.st_mode)):
            err('%s modified %s directly!\n' % (self.argv[2], t))
            err('...you should update $3 (a temp file) or stdout, not $1.\n')
            rv = 206
        elif st2 and st1.st_size > 0:
            err('%s wrote to stdout *and* created $3.\n' % self.argv[2])
            err('...you should write status messages to stderr, not stdout.\n')
            rv = 207
        if rv==0:
            if st2:
                os.rename(self.tmpname2, t)
                os.unlink(self.tmpname1)
            elif st1.st_size > 0:
                try:
                    os.rename(self.tmpname1, t)
                except OSError, e:
                    if e.errno == errno.ENOENT:
                        unlink(t)
                    else:
                        raise
                if st2:
                    os.unlink(self.tmpname2)
            else: # no output generated at all; that's ok
                unlink(self.tmpname1)
                unlink(t)
            sf = self.sf
            sf.refresh()
            sf.is_generated = True
            sf.is_override = False
            if sf.is_checked() or sf.is_changed():
                # it got checked during the run; someone ran redo-stamp.
                # update_stamp would call set_changed(); we don't want that
                sf.stamp = sf.read_stamp()
            else:
                sf.csum = None
                sf.update_stamp()
                sf.set_changed()
        else:
            unlink(self.tmpname1)
            unlink(self.tmpname2)
            sf = self.sf
            sf.set_failed()
        sf.zap_deps2()
        sf.save()
        f.close()
        if rv != 0:
            err('%s: exit code %d\n' % (_nice(t),rv))
        else:
            if vars.VERBOSE or vars.XTRACE or vars.DEBUG:
                log('%s (done)\n\n' % _nice(t))
        return rv

    def _after2(self, rv):
        try:
            self.donefunc(self.t, rv)
            assert(self.lock.owned)
        finally:
            self.lock.unlock()



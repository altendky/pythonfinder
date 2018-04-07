# -*- coding=utf-8 -*-
import os
from pythonfinder._vendor import six
from pythonfinder._vendor import delegator
from pythonfinder._vendor.packaging.version import parse as parse_version
try:
    from pathlib import Path
except ImportError:
    from pythonfinder._vendor.pathlib2 import Path


PYENV_INSTALLED = (bool(os.environ.get('PYENV_SHELL')) or bool(os.environ.get('PYENV_ROOT')))
PYENV_ROOT = os.environ.get('PYENV_ROOT', os.path.expanduser('~/.pyenv'))


def shellquote(s):
    """Prepares a string for the shell (on Windows too!)

    Only for use on grouped arguments (passed as a string to Popen)
    """
    if s is None:
        return None
    # Additional escaping for windows paths
    if os.name == 'nt':
        s = "{}".format(s.replace("\\", "\\\\"))

    return '"' + s.replace("'", "'\\''") + '"'


class PathFinder(object):
    WHICH = {}

    def __init__(self, path=None):
        self.path = path if path else os.environ.get('PATH')
        self._populate_which_dict()

    @classmethod
    def which(cls, cmd):
        if not cls.WHICH:
            cls._populate_which_dict()
        return cls.WHICH.get(cmd, cmd)

    @classmethod
    def _populate_which_dict(cls):
        for path in os.environ.get('PATH', '').split(os.pathsep):
            files = os.listdir(path)
            for fn in files:
                full_path = os.sep.join([path, fn])
                if os.access(full_path, os.X_OK) and not os.path.isdir(full_path):
                    if not cls.WHICH.get(fn):
                        cls.WHICH[fn] = full_path
                    base_exec = os.path.splitext(fn)[0]
                    if not cls.WHICH.get(base_exec):
                        cls.WHICH[base_exec] = full_path


class PythonFinder(PathFinder):
    """Find pythons given a specific version, path, or nothing."""

    PYENV_VERSIONS = {}
    PYTHON_VERSIONS = {}
    PYTHON_PATHS = {}
    MAX_PYTHON = {}
    WHICH_PYTHON = {}
    RUNTIMES = ['python', 'pypy', 'ipy', 'jython', 'pyston']

    def __init__(self, path=None, version=None, full_version=None):
        self.version = version
        self.full_version = full_version
        super(PythonFinder, self).__init__(path=path)

    @classmethod
    def from_line(cls, python):
        if os.path.isabs(python) and os.access(python, os.X_OK):
            return python
        if python.startswith('py'):
            return cls.WHICH_PYTHON.get(python) or cls.which(python)

    @classmethod
    def from_version(cls, version):
        guess = cls.PYTHON_VERSIONS.get(cls.MAX_PYTHON.get(version, version))
        if guess:
            return guess
        if os.name == 'nt':
            path = cls.from_windows_finder(version)
        else:
            parsed_version = parse_version(version)
            full_version = parsed_version.base_version
            if PYENV_INSTALLED:
                path = cls.from_pyenv(full_version)
            else:
                path = cls._crawl_path_for_version(full_version)
        return path

    @classmethod
    def from_windows_finder(cls, version):
        from pythonfinder._vendor.pep514tools import environment
        versions = environment.find(version)
        path = None
        for version_object in versions:
            path = Path(version_object.info.install_path.__getattr__('')).joinpath('python.exe')
            version = version_object.info.sys_version
            full_version = version_object.info.version
            for v in [version, full_version]:
                if not cls.PYTHON_VERSIONS.get(v):
                    cls.PYTHON_VERSIONS[v] = '{0}'.format(path)
            cls.register_python(path, full_version)
        return cls.PYTHON_VERSIONS[version]

    @classmethod
    def _populate_python_versions(cls):
        import fnmatch
        match_rules = ['*python', '*python?', '*python?.?', '*python?.?m']
        runtime_execs = []
        exts = list(filter(None, os.environ.get('PATHEXT', '').split(os.pathsep)))
        for path in os.environ.get('PATH', '').split(os.pathsep):
            from glob import glob
            pythons = glob(os.sep.join([path, 'python*']))
            execs = [match for rule in match_rules for match in fnmatch.filter(pythons, rule)]
            for executable in execs:
                exec_name = os.path.basename(executable)
                if os.access(executable, os.X_OK):
                    runtime_execs.append(executable)
                if not cls.WHICH_PYTHON.get(exec_name):
                    cls.WHICH_PYTHON[exec_name] = executable
                for e in exts:
                    pext = executable + e
                    if os.access(pext, os.X_OK):
                        runtime_execs.append(pext)
        for python in runtime_execs:
            version_cmd = '{0} -c "import sys; print(sys.version.split()[0])"'.format(shellquote(python))
            version = delegator.run(version_cmd).out.strip()
            cls.register_python(python, version)

    @classmethod
    def _crawl_path_for_version(cls, version):
        if not cls.PYTHON_VERSIONS:
            cls._populate_python_versions()
        return cls.PYTHON_VERSIONS.get(version)

    @classmethod
    def from_pyenv(cls, version):
        if not cls.PYENV_VERSIONS:
            cls.populate_pyenv_runtimes()
        return cls.PYENV_VERSIONS[version]

    @classmethod
    def register_python(cls, path, full_version, pre=False, pyenv=False):
        parsed_version = parse_version(full_version)
        pre = pre or parsed_version.is_prerelease
        major_minor = '.'.join(['{0}'.format(v) for v in parsed_version._version.release[:2]])
        major = '{0}'.format(parsed_version._version.release[0])
        cls.PYTHON_PATHS[path] = full_version
        if not pre and parsed_version > parse_version(cls.MAX_PYTHON.get(major_minor, '0.0.0')):
            if major_minor != full_version:
                if parsed_version > parse_version(cls.MAX_PYTHON.get(full_version, '0.0.0')):
                    cls.MAX_PYTHON[full_version] = parsed_version.base_version
            cls.MAX_PYTHON[major_minor] = parsed_version.base_version
            cls.PYTHON_VERSIONS[major_minor] = path
            if parsed_version > parse_version(cls.MAX_PYTHON.get(major, '0.0.0')):
                cls.MAX_PYTHON[major] = parsed_version.base_version
                cls.PYTHON_VERSIONS[major] = path
        if not pyenv:
            for v in [full_version, major_minor, major]:
                if not cls.PYTHON_VERSIONS.get(v) or cls.MAX_PYTHON[v] == full_version:
                    cls.PYTHON_VERSIONS[v] = path
        else:
            for v in[full_version, major_minor, major]:
                if (not cls.PYENV_VERSIONS.get(v) and (v == major and not pre) or v != major) or cls.MAX_PYTHON[v] == full_version:
                    cls.PYENV_VERSIONS[v] = path
            if not cls.PYTHON_VERSIONS.get(full_version):
                cls.PYTHON_VERSIONS[full_version] = path

    @classmethod
    def populate_pyenv_runtimes(cls):
        from glob import glob
        search_path = os.sep.join(['{0}'.format(PYENV_ROOT), 'versions', '*'])
        runtimes = ['pypy', 'ipy', 'jython', 'pyston']
        for pyenv_path in glob(search_path):
            parsed_version = parse_version(os.path.basename(pyenv_path))
            if parsed_version.is_prerelease and cls.PYENV_VERSIONS.get(parsed_version.base_version):
                continue
            bin_path = os.sep.join([pyenv_path, 'bin'])
            runtime = os.sep.join([bin_path, 'python'])
            if not os.path.exists(runtime):
                exes = [os.sep.join([bin_path, exe]) for exe in runtimes if os.path.exists(os.sep.join([bin_path, exe]))]
                if exes:
                    runtime = exes[0]
            cls.register_python(runtime, parsed_version.base_version, pre=parsed_version.is_prerelease, pyenv=True)
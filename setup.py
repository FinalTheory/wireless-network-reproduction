"""
This is a setup.py script generated by py2applet

Usage:
    python setup.py py2app
"""

import os
import re
import sys
import glob
import shutil

import PIL

dirname, filename = os.path.split(os.path.abspath(__file__))
sys.path.append(os.path.join(dirname, 'tcptrace_gui'))
from setuptools import setup
from subprocess import Popen, PIPE

PAT = re.compile(r'python\d+\.\d+')

PIL_path, init_file = os.path.split(PIL.__file__)

PYTHON_VERSION = PAT.search(PIL_path).group()

APP_NAME = 'NetworkProfiler'

DATA_FILES = glob.glob(os.path.join(PIL_path, '.dylibs/*'))

OPTIONS = {
    'argv_emulation': False,
    'packages': ['pytcptrace', 'macdivert'],
    'iconfile': 'resource/icon.icns',
    'plist': {
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleIconFile': 'icon.icns',
    },
    'extra_scripts': ['network_emulator.py'],
    'resources': [('lib/%s/lib-dynload/PIL/.dylibs/'
                   % PYTHON_VERSION, DATA_FILES), ]
}


def call_cmd(cmd_list):
    p = Popen(cmd_list, stdout=PIPE,
              stdin=PIPE, stderr=PIPE)
    p.wait()
    print '*' * 30 + 'STDOUT' + '*' * 30
    print p.stdout.read()
    print '*' * 30 + 'STDERR' + '*' * 30
    print p.stderr.read()
    print '*' * 66
    print '\n'


def cmake_build(src_dir):
    build_path = os.path.join(dirname, src_dir + '_cmake')
    source_path = os.path.join(dirname, src_dir)
    if os.path.exists(build_path):
        shutil.rmtree(build_path)
    os.mkdir(build_path)
    call_cmd(['cmake', '-B' + build_path, '-H' + source_path,
              '-DCMAKE_BUILD_TYPE=Release'])
    call_cmd(['make', '-C', build_path])
    return build_path


def xcode_build(src_dir):
    src_path = os.path.join(dirname, src_dir)
    build_path = os.path.join(dirname, src_dir + '_xcode')
    if os.path.exists(build_path):
        shutil.rmtree(build_path)
    os.mkdir(build_path)

    kext_path = os.path.join(dirname, 'macdivert', 'PacketPID.kext')
    if os.path.exists(kext_path):
        shutil.rmtree(kext_path)

    os.chdir(src_path)
    call_cmd(['xcodebuild', '-configuration', 'Release',
              'CONFIGURATION_BUILD_DIR=' + build_path])
    shutil.copytree(os.path.join(build_path, 'PacketPID.kext'), kext_path)
    os.chdir(dirname)


def archive_dmg():
    call_cmd(['hdiutil', 'create', os.path.join('dist', APP_NAME + '.dmg'),
              '-srcfolder', os.path.join('dist', APP_NAME + '.app')])


# first remove previous builds
for name in ('dist', 'build'):
    del_path = os.path.join(dirname, name)
    if os.path.exists(del_path):
        shutil.rmtree(del_path)

# then compile the binaries and copy them
shutil.copy(os.path.join(cmake_build('libdivert'), 'libdivert.so'),
            os.path.join(dirname, 'macdivert', 'libdivert.so'))

shutil.copy(os.path.join(cmake_build('tcptrace'), 'tcptrace'),
            os.path.join(dirname, 'tcptrace_gui', 'pytcptrace', 'tcptrace'))

xcode_build('PacketPID')

setup(
    # Application name
    name=APP_NAME,
    # Entry file
    app=['tcptrace_gui/main.py'],
    # Static data files
    data_files=DATA_FILES,
    # Other options
    options={'py2app': OPTIONS},
    # Requirements
    setup_requires=['py2app'],
)


# finally archive entire app into disk image
archive_dmg()

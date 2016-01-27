# encoding: utf8

import os
import json
import psutil
import signal
import threading
import Tkinter as tk
from macdivert import MacDivert
from tkMessageBox import showerror
from enum import Defaults
from tkFileDialog import askopenfilename, askdirectory
from ctypes import POINTER, pointer, cast
from ctypes import (c_uint8, c_void_p, c_int32, c_char_p, c_int,  c_float,
                    create_string_buffer, c_size_t, c_ssize_t, c_uint64)

__author__ = 'huangyan13@baidu.com'


class Flags(object):
    # direction flags
    DIRECTION_IN = 0
    DIRECTION_OUT = 1
    DIRECTION_UNKNOWN = 2

    # feature flags
    EMULATOR_IS_RUNNING = 1
    EMULATOR_DUMP_PCAP = (1 << 1)
    EMULATOR_RECHECKSUM = (1 << 2)

    # pipe flags
    PIPE_DROP = 0
    PIPE_DELAY = 1
    PIPE_THROTTLE = 2
    PIPE_DISORDER = 3
    PIPE_BITERR = 4
    PIPE_DUPLICATE = 5
    PIPE_BANDWIDTH = 6
    PIPE_REINJECT = 7

    # buffer size
    EMULALTOR_BUF_SIZE = 8172
    DELAY_QUEUE_SIZE = 8172


class BasicPipe(object):
    def __init__(self):
        self.handle = None
        if Emulator.libdivert_ref is None:
            raise RuntimeError("Should first instantiate an Emulator object")
        else:
            self._lib = Emulator.libdivert_ref


class DelayPipe(BasicPipe):
    def __init__(self, t, delay_time, queue_size=Flags.DELAY_QUEUE_SIZE, size_filter_obj=None):
        super(DelayPipe, self).__init__()
        # first set function signature
        setattr(getattr(self._lib, 'delay_pipe_create'), "argtypes",
                [c_void_p, c_size_t, POINTER(c_float), POINTER(c_float), c_size_t])
        setattr(getattr(self._lib, 'delay_pipe_create'), "restype", c_void_p)
        arr_len = len(t)
        arr_type = c_float * arr_len
        # then check packet size filter handle
        filter_handle = None if size_filter_obj is None else size_filter_obj.handle
        self.handle = self._lib.delay_pipe_create(filter_handle, arr_len,
                                                  arr_type(*list(t)),
                                                  arr_type(*list(delay_time)),
                                                  queue_size)


class DropPipe(BasicPipe):
    def __init__(self, t, drop_rate, size_filter_obj=None):
        super(DropPipe, self).__init__()
        # first set function signature
        setattr(getattr(self._lib, 'drop_pipe_create'), "argtypes",
                [c_void_p, c_size_t, POINTER(c_float), POINTER(c_float)])
        setattr(getattr(self._lib, 'drop_pipe_create'), "restype", c_void_p)
        arr_len = len(t)
        arr_type = c_float * arr_len
        # then check packet size filter handle
        filter_handle = None if size_filter_obj is None else size_filter_obj.handle
        self.handle = self._lib.drop_pipe_create(filter_handle, arr_len,
                                                 arr_type(*list(t)),
                                                 arr_type(*list(drop_rate)))


class BandwidthPipe(BasicPipe):
    def __init__(self, t, bandwidth, queue_size=Flags.DELAY_QUEUE_SIZE, size_filter_obj=None):
        super(BandwidthPipe, self).__init__()
        # first set function signature
        setattr(getattr(self._lib, 'bandwidth_pipe_create'), "argtypes",
                [c_void_p, c_size_t, POINTER(c_float), POINTER(c_float), c_size_t])
        setattr(getattr(self._lib, 'bandwidth_pipe_create'), "restype", c_void_p)
        arr_len = len(t)
        arr_type = c_float * arr_len
        # then check packet size filter handle
        filter_handle = None if size_filter_obj is None else size_filter_obj.handle
        self.handle = self._lib.bandwidth_pipe_create(filter_handle, arr_len,
                                                      arr_type(*list(t)),
                                                      arr_type(*list(bandwidth)),
                                                      queue_size)


class Emulator(object):
    libdivert_ref = None

    emulator_argtypes = {
        'emulator_callback': [c_void_p, c_void_p, c_char_p, c_char_p],
        'emulator_create_config': [c_void_p, c_size_t],
        'emulator_destroy_config': [c_void_p],
        'emulator_start': [c_void_p],
        'emulator_stop': [c_void_p],
        'emulator_add_pipe': [c_void_p, c_void_p, c_int],
        'emulator_del_pipe': [c_void_p, c_void_p, c_int],
        'emulator_add_flag': [c_void_p, c_uint64],
        'emulator_clear_flags': [c_void_p],
        'emulator_clear_flag': [c_void_p, c_uint64],
        'emulator_set_dump_pcap': [c_void_p, c_char_p],
        'emulator_set_pid_list': [c_void_p, POINTER(c_int32), c_ssize_t],
        'emulator_config_check': [c_void_p, c_char_p],
        'emulator_is_running': [c_void_p],
        'emulator_data_size': [c_void_p, c_int]
    }

    emulator_restypes = {
        'emulator_callback': None,
        'emulator_create_config': c_void_p,
        'emulator_destroy_config': None,
        'emulator_start': None,
        'emulator_stop': None,
        'emulator_add_pipe': c_int,
        'emulator_del_pipe': c_int,
        'emulator_add_flag': None,
        'emulator_clear_flags': None,
        'emulator_clear_flag': None,
        'emulator_set_dump_pcap': None,
        'emulator_set_pid_list': None,
        'emulator_config_check': c_int,
        'emulator_is_running': c_int,
        'emulator_data_size': c_uint64,
    }

    def __init__(self):
        # get reference for libdivert
        if Emulator.libdivert_ref is None:
            lib_obj = MacDivert()
            Emulator.libdivert_ref = lib_obj.get_reference()
            # initialize prototype of functions
            self._init_func_proto()
        # create divert handle and emulator config
        self.handle, self.config = self._create_config()
        # background thread for divert loop
        self.thread = None
        # list to store pids
        self.pid_list = []
        # error information
        self.errmsg = create_string_buffer(Defaults.DIVERT_ERRBUF_SIZE)

    def __del__(self):
        lib = self.libdivert_ref
        lib.emulator_destroy_config(self.config)
        if lib.divert_close(self.handle) != 0:
            raise RuntimeError('Divert handle could not be cleaned.')

    def _init_func_proto(self):
        # set the types of parameters
        for func_name, argtypes in self.emulator_argtypes.items():
            # first check if function exists
            if not hasattr(self.libdivert_ref, func_name):
                raise RuntimeError("Not a valid libdivert library")
            setattr(getattr(self.libdivert_ref, func_name), "argtypes", argtypes)

        # set the types of return value
        for func_name, restype in self.emulator_restypes.items():
            setattr(getattr(self.libdivert_ref, func_name), "restype", restype)

    def _create_config(self):
        lib = self.libdivert_ref
        # create divert handle
        divert_handle = lib.divert_create(0, 0)
        if not divert_handle:
            raise RuntimeError('Fail to create divert handle.')
        # create config handle
        config = lib.emulator_create_config(divert_handle,
                                            Flags.EMULALTOR_BUF_SIZE)
        if not config:
            raise RuntimeError('Fail to create emulator configuration')
        # set callback function and callback data for divert handle
        if lib.divert_set_callback(divert_handle,
                                   lib.emulator_callback,
                                   config) != 0:
            raise RuntimeError(divert_handle.errmsg)
        # activate divert handle
        if lib.divert_activate(divert_handle) != 0:
            raise RuntimeError(divert_handle.errmsg)
        return divert_handle, config

    def _divert_loop(self, filter_str):
        # first apply filter string
        lib = self.libdivert_ref
        if filter_str:
            if lib.divert_update_ipfw(self.handle, filter_str) != 0:
                raise RuntimeError(self.handle.errmsg)
        # then add all pids into list
        self._wait_pid()
        # finally check the config
        if lib.emulator_config_check(self.config, self.errmsg) != 0:
            raise RuntimeError('Invalid configuration: %s' % self.errmsg)
        lib.emulator_start(self.config)
        lib.divert_loop(self.handle, -1)

    def _divert_loop_stop(self):
        lib = self.libdivert_ref
        lib.divert_loop_stop(self.handle)
        lib.divert_wait_loop_finish(self.handle)
        lib.emulator_stop(self.config)

    def add_pipe(self, pipe, direction=Flags.DIRECTION_IN):
        lib = self.libdivert_ref
        if lib.emulator_add_pipe(self.config, pipe.handle, direction) != 0:
            raise RuntimeError("Pipe already exists.")

    def del_pipe(self, pipe, free_mem=False):
        lib = self.libdivert_ref
        if lib.emulator_del_pipe(self.config, pipe.handle, int(free_mem)) != 0:
            raise RuntimeError("Pipe do not exists.")

    def add_pid(self, pid):
        self.pid_list.append(pid)

    def _wait_pid(self):
        # first wait until all processes are started
        proc_list = filter(lambda x: isinstance(x, str) or isinstance(x, unicode), self.pid_list)
        real_pid_list = filter(lambda x: isinstance(x, int), self.pid_list)
        while True:
            if len(real_pid_list) == len(self.pid_list):
                break
            for proc in psutil.process_iter():
                proc_name = proc.name().lower()
                for name in proc_list:
                    if name.lower() in proc_name:
                        real_pid_list.append(proc.pid)
            time.sleep(0.2)
        lib = self.libdivert_ref
        arr_len = len(real_pid_list)
        arr_type = c_int32 * arr_len
        lib.emulator_set_pid_list(self.config, arr_type(*real_pid_list), arr_len)

    def set_dump(self, directory):
        lib = self.libdivert_ref
        if not os.path.isdir:
            raise RuntimeError('Invalid save position.')
        lib.emulator_set_dump_pcap(self.config, directory)

    def start(self, filter_str=''):
        # start a new thread to run emulator
        self.thread = threading.Thread(target=self._divert_loop, args=(filter_str,))
        self.thread.start()

    def stop(self):
        self._divert_loop_stop()
        self.thread.join(timeout=1.0)
        if self.thread.isAlive():
            raise RuntimeError('Divert loop failed to stop.')
        self.thread = None

    @property
    def is_looping(self):
        return self.thread is not None

    def data_size(self, direction):
        lib = self.libdivert_ref
        return lib.emulator_data_size(self.config, direction)


class EmulatorGUI(object):
    kext_errmsg = """
    Kernel extension load failed.
    Please check if you have root privilege on your Mac.
    Since we do not have a valid developer certificate,
    you should manually disable the kernel extension protection.

    For Mac OS X 10.11:
    1. Start your computer from recovery mode: restart your Mac
    and hold down the Command and R keys at startup.
    2. Run "csrutil enable --without kext" under recovery mode.
    3. Reboot.

    For Mac OS X 10.10:
    1. Run "sudo nvram boot-args=kext-dev-mode=1" from terminal.
    2. Reboot.
    """

    def __init__(self, master):
        self.master = master
        master.title("Network Emulator")
        master.protocol("WM_DELETE_WINDOW",
                        lambda: (master.quit(), master.destroy()))

        # first check root privilege
        if os.getuid() != 0:
            self.master.withdraw()
            showerror('Privilege Error', 'You should run this program as root.')
            self.master.destroy()
            return

        self.inbound_list = []
        self.outbound_list = []
        self.filter_str = tk.StringVar(value='ip from any to any via en0')
        self.proc_str = tk.StringVar(value='PID / comma separated process name')
        self.data_file = tk.StringVar()
        self.dump_pos = tk.StringVar()
        self.start_btn = None

        self.conf = None
        self.emulator = None

        self.init_GUI()

        try:
            self.emulator = Emulator()
        except OSError:
            def close_func():
                self.master.quit()
                self.master.destroy()
            self.master.withdraw()
            top = tk.Toplevel(self.master)
            top.title('Kernel Extension Error')
            tk.Message(top, text=self.kext_errmsg)\
                .pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            tk.Button(top, text="Close", command=close_func).pack(side=tk.TOP)
            top.protocol("WM_DELETE_WINDOW", close_func)
        except Exception as e:
            self.master.withdraw()
            showerror('Emulator Loading Error', e.message)
            self.master.destroy()

    def init_GUI(self):
        new_frame = tk.Frame(master=self.master)
        tk.Label(master=new_frame, text='File:').pack(side=tk.LEFT)
        tk.Entry(master=new_frame, textvariable=self.data_file)\
            .pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Button(master=new_frame, text='Select',
                  command=self.load_data_file).pack(side=tk.LEFT)
        new_frame.pack(side=tk.TOP, fill=tk.X, expand=True)

        new_frame = tk.Frame(master=self.master)
        tk.Label(master=new_frame, text='Dump to:').pack(side=tk.LEFT)
        tk.Entry(master=new_frame, textvariable=self.dump_pos)\
            .pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Button(master=new_frame, text='Select',
                  command=self.load_dump_pos).pack(side=tk.LEFT)
        new_frame.pack(side=tk.TOP, fill=tk.X, expand=True)

        new_frame = tk.Frame(master=self.master)
        tk.Label(master=new_frame, text='Filter Expr').pack(side=tk.LEFT)
        tk.Entry(master=new_frame, textvariable=self.filter_str, font='Monaco') \
            .pack(side=tk.LEFT, fill=tk.X, expand=True)
        new_frame.pack(side=tk.TOP, fill=tk.X, expand=True)

        new_frame = tk.Frame(master=self.master)
        tk.Label(master=new_frame, text='Proc List').pack(side=tk.LEFT)
        tk.Entry(master=new_frame, textvariable=self.proc_str,
                 font='Monaco', width=len(self.proc_str.get()))\
            .pack(side=tk.LEFT, fill=tk.X, expand=True)
        new_frame.pack(side=tk.TOP, fill=tk.X, expand=True)

        new_frame = tk.Frame(master=self.master)
        self.start_btn = tk.Button(master=new_frame, text='Start',
                                   command=self.start, font=('Monaco', 20))
        self.start_btn.pack(side=tk.TOP)
        new_frame.pack(side=tk.TOP, fill=tk.X, expand=True)

    def load_data_file(self):
        dir_name, file_name = os.path.split(__file__)
        dir_name = os.path.join(dir_name, 'examples')
        file_path = askopenfilename(title='Choose .json file', initialdir=dir_name)
        if file_path and os.path.isfile(file_path):
            try:
                self.data_file.set(file_path)
                with open(self.data_file.get(), 'r') as fid:
                    data = fid.read()
                    self.conf = json.loads(data)
            except Exception as e:
                showerror(title='Open file',
                          message='Unable to load data: %s' % e.message)

    def load_dump_pos(self):
        dir_name, file_name = os.path.split(__file__)
        dir_name = os.path.join(dir_name, 'examples')
        dir_path = askdirectory(title='Choose dump position',
                                initialdir=dir_name)
        self.dump_pos.set(dir_path)

    def start(self):
        if self.emulator is None:
            try:
                self.start_btn.config(text='Stop')
                self.start_btn.config(status=tk.DISABLED)
                self.emulator = Emulator()
                self._load_config()
                self.emulator.start(self.filter_str.get())
                self.start_btn.config(status=tk.NORMAL)
            except Exception as e:
                showerror(title='Runtime error',
                          message='Unable to start emulator: %s' % e.message)
        else:
            try:
                self.start_btn.config(text='Start')
                self.start_btn.config(status=tk.DISABLED)
                self.emulator.stop()
                self.emulator = None
                self.start_btn.config(status=tk.NORMAL)
            except Exception as e:
                showerror(title='Runtime error',
                          message='Unable to stop emulator: %s' % e.message)

    def _load_config(self):
        if self.emulator is None:
            return
        # set dump position
        dump_path = self.dump_pos.get()
        if dump_path and os.path.isdir(dump_path):
            self.emulator.set_dump(dump_path)
        # set pid list if not empty
        if self.proc_str.get().strip():
            self.emulator.add_pid(-1)
            for pid in map(lambda x: x.strip(), self.proc_str.get().split(',')):
                self.emulator.add_pid(pid)
        # finally load all pipes

    def mainloop(self):
        self.master.mainloop()


if __name__ == '__main__':
    import sys
    import time
    import signal

    pid_num = 0

    try:
        pid_num = int(sys.argv[1])
    except Exception as e:
        print 'Exception: %s' % e.message
        print 'Usage: python emulator.py <PID>'
        exit(-1)

    emulator = Emulator()
    emulator.add_pid(pid_num)
    emulator.add_pid(-1)
    emulator.set_dump('/Users/baidu/Downloads')

    # 2G
    # emulator.add_pipe(DelayPipe([0, 10], [0.6, 0.6], 1024), Flags.DIRECTION_IN)
    # emulator.add_pipe(DelayPipe([0, 10], [0.6, 0.6], 1024), Flags.DIRECTION_OUT)
    # emulator.add_pipe(BandwidthPipe([0, 10], [5, 5], 1024), Flags.DIRECTION_IN)

    # 2.5G
    # emulator.add_pipe(DelayPipe([0, 10], [0.3, 0.3], 1024), Flags.DIRECTION_IN)
    # emulator.add_pipe(DelayPipe([0, 10], [0.3, 0.3], 1024), Flags.DIRECTION_OUT)
    # emulator.add_pipe(BandwidthPipe([0, 10], [10, 10], 1024), Flags.DIRECTION_IN)

    # 2.75G
    emulator.add_pipe(DelayPipe([0, 10], [0.1, 0.1], 1024), Flags.DIRECTION_IN)
    emulator.add_pipe(DelayPipe([0, 10], [0.2, 0.2], 1024), Flags.DIRECTION_OUT)
    emulator.add_pipe(BandwidthPipe([0, 10], [30, 30], 1024), Flags.DIRECTION_IN)

    # 3G
    # emulator.add_pipe(DelayPipe([0, 10], [0.05, 0.05], 1024), Flags.DIRECTION_IN)
    # emulator.add_pipe(DelayPipe([0, 10], [0.05, 0.05], 1024), Flags.DIRECTION_OUT)
    # emulator.add_pipe(BandwidthPipe([0, 10], [125, 125], 1024), Flags.DIRECTION_IN)

    # 4G
    # emulator.add_pipe(DelayPipe([0, 10], [0.015, 0.015], 1024), Flags.DIRECTION_IN)
    # emulator.add_pipe(DelayPipe([0, 10], [0.015, 0.015], 1024), Flags.DIRECTION_OUT)
    # emulator.add_pipe(BandwidthPipe([0, 10], [500, 500], 1024), Flags.DIRECTION_IN)

    is_looping = True

    # register signal handler
    def sig_handler(signum, frame):
        print 'Catch signal: %d' % signum
        global is_looping
        is_looping = False
    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTSTP, sig_handler)

    perMB = 1024 * 1024

    trans_size = 0
    # start loop
    emulator.start('ip from any to any via en0')
    while is_looping:
        data_size = emulator.data_size(Flags.DIRECTION_IN)
        if data_size > 5 * perMB:
            print 'Finish'
            break
        if data_size > (trans_size + 1) * perMB:
            trans_size = data_size / perMB
            print 'Transfer %d MB data.' % trans_size
        time.sleep(0.5)
    # stop loop
    emulator.stop()
    print 'Program exited.'

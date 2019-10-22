'''
 * This software was created by United States Government employees
 * and may not be copyrighted.
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
 * IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 * WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 * DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT,
 * INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 * (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
 * SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
 * HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
 * STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
 * ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
'''

from simics import *
import procInfo
import traceback
import sys
import pageUtils
import logging
import decode
import decodeArm
import memUtils
import pageUtils
import resim_utils
import armCond
'''
BEWARE syntax errors are not seen.  TBD make unit test
'''
''' 
    Manage reverse step into and over
    TBD add other executable pages 
    The log for this is in its own log file
'''
class RegisterModType():
    UNKNOWN = 0
    REG = 1
    ADDR = 2
    ''' pursuing taint via other means '''
    BAIL = 3
    def __init__(self, value, mod_type, src_reg=None):
        self.value = value
        self.mod_type = mod_type
        self.src_reg = None


class reverseToCall():
    def __init__(self, top, param, task_utils, page_size, context_manager, name, is_monitor_running, bookmarks, logdir):
            #print('call getLogger')
            self.lgr = resim_utils.getLogger(name, logdir)
            self.context_manager = context_manager 
            #sys.stderr = open('err.txt', 'w')
            self.top = top 
            self.cpu = None
            self.pid = None
            self.cell_name = None
            #self.lgr = lgr
            self.page_size = page_size
            self.lgr.debug('reverseToCall, in init')
            self.param = param
            self.task_utils = task_utils
            self.decode = None
            ''' hackish for sharing this with genMonitor and cgcMonitor '''
            self.x_pages = None
            self.the_breaks = []
            self.reg = None
            self.reg_num = None
            self.reg_val = None
            self.stop_hap = None
            self.uncall = False
            self.is_monitor_running = is_monitor_running
            self.taint = False
            self.bookmarks = bookmarks
            self.previous_eip = None
            self.step_into = None
            self.sysenter_cycles = {}
            self.jump_stop_hap = None
            self.sysenter_hap = None
            self.enter_break1 = None
            self.enter_break2 = None
            self.start_cycles = None
            self.page_faults = None
            self.frame_ips = []
            self.uncall_hap = None
            self.uncall_break = None
            self.value = None
            self.save_cycle = None
            self.save_reg_mod = None

    def getStartCycles(self):
        return self.start_cycles

    def noWatchSysenter(self):
        if self.enter_break1 is not None:
            self.lgr.debug('noWatchSystenter, remove sysenter breaks and hap')
            self.context_manager.genDeleteBreakpoint(self.enter_break1)
            self.context_manager.genDeleteBreakpoint(self.enter_break2)
            self.context_manager.genDeleteHap(self.sysenter_hap, immediate=True)
            self.enter_break1 = None

    def v2p(self, cpu, v):
        try:
            phys_block = cpu.iface.processor_info.logical_to_physical(v, Sim_Access_Read)
            if phys_block.address != 0:
                return phys_block.address
            else:
                if v < self.param.kernel_base:
                    phys_addr = v & ~self.param.kernel_base 
                    return phys_addr
                else:
                    return 0
                    
        except:
            return None

    def watchSysenter(self, dumb=None):
        cell = self.top.getCell()
        if self.enter_break1 is None:
            if self.cpu.architecture == 'arm':
                self.lgr.debug('watchSysenter set linear break at 0x%x' % (self.param.arm_entry))
                self.enter_break1 = self.context_manager.genBreakpoint(cell, Sim_Break_Linear, Sim_Access_Execute, self.param.arm_entry, 1, 0)
                self.sysenter_hap = self.context_manager.genHapIndex("Core_Breakpoint_Memop", self.sysenterHap, None, self.enter_break1, 'reverseToCall sysenter')
            else:
                if self.param.sysenter is not None and self.param.sys_entry is not None:
                    self.lgr.debug('watchSysenter set linear breaks at 0x%x and 0x%x' % (self.param.sysenter, self.param.sys_entry))
                    self.enter_break1 = self.context_manager.genBreakpoint(cell, Sim_Break_Linear, Sim_Access_Execute, self.param.sysenter, 1, 0)
                    self.enter_break2 = self.context_manager.genBreakpoint(cell, Sim_Break_Linear, Sim_Access_Execute, self.param.sys_entry, 1, 0)
                    self.sysenter_hap = self.context_manager.genHapRange("Core_Breakpoint_Memop", self.sysenterHap, None, self.enter_break1, self.enter_break2, 'reverseToCall sysenter')
                elif self.param.sysenter is not None:
                    self.lgr.debug('watchSysenter sysenter set linear breaks at 0x%x ' % (self.param.sysenter))
                    self.enter_break1 = self.context_manager.genBreakpoint(cell, Sim_Break_Linear, Sim_Access_Execute, self.param.sysenter, 1, 0)
                    self.sysenter_hap = self.context_manager.genHapIndex("Core_Breakpoint_Memop", self.sysenterHap, None, self.enter_break1, 'reverseToCall sysenter')
                elif self.param.sys_entry is not None:
                    self.lgr.debug('watchSysenter sys_entry set linear breaks at 0x%x ' % (self.param.sys_entry))
                    self.enter_break1 = self.context_manager.genBreakpoint(cell, Sim_Break_Linear, Sim_Access_Execute, self.param.sys_entry, 1, 0)
                    self.sysenter_hap = self.context_manager.genHapIndex("Core_Breakpoint_Memop", self.sysenterHap, None, self.enter_break1, 'reverseToCall sys_entry')

    def setup(self, cpu, x_pages, bookmarks=None, page_faults = None):
            self.cpu = cpu
            self.start_cycles = self.cpu.cycles & 0xFFFFFFFFFFFFFFFF
            self.cell_name = self.top.getTopComponentName(cpu)
            self.x_pages = x_pages
            self.page_faults = page_faults
            if bookmarks is not None: 
                self.bookmarks = bookmarks
            if (hasattr(self.param, 'sysenter') and self.param.sysenter is not None) or \
               (hasattr(self.param, 'sys_entry') and self.param.sys_entry is not None) or \
               (hasattr(self.param, 'arm_entry') and self.param.arm_entry is not None):
                '''  Track sysenter to support reverse over those.  TBD currently only works with genMonitor'''
                SIM_run_alone(self.watchSysenter, None)

            dum_cpu, cur_addr, comm, pid = self.task_utils.currentProcessInfo(self.cpu)
            self.context_manager.changeDebugPid(pid) 
            self.lgr.debug('reverseToCall setup')
            if cpu.architecture == 'arm':
                self.decode = decodeArm
                self.lgr.debug('setup using arm decoder')
            else:
                self.decode = decode


    def doBreaks(self, pcell, range_start, page_count, call_ret):
        size = page_count * pageUtils.PAGE_SIZE
        if call_ret:
            # Set exectution breakpoints for "call" and "ret" instructions
            #call_break_num = self.context_manager.genBreakpoint(pcell, Sim_Break_Physical, 
            #   Sim_Access_Execute, range_start, size, 0)
            call_break_num = SIM_breakpoint(pcell, Sim_Break_Physical, 
               Sim_Access_Execute, range_start, size, 0)
            self.the_breaks.append(call_break_num)
            command = 'set-prefix %d "call"' % call_break_num
            if self.cpu.architecture == 'arm':
                command = 'set-prefix %d "bl"' % call_break_num
            else:
                command = 'set-prefix %d "call"' % call_break_num
            SIM_run_alone(SIM_run_command, command)
            if self.cpu.architecture == 'arm':
                ret_break_num = SIM_breakpoint(pcell, Sim_Break_Physical, 
                   Sim_Access_Execute, range_start, size, 0)
                self.the_breaks.append(ret_break_num)
                command = 'set-substr %d "PC"' % ret_break_num
                SIM_run_alone(SIM_run_command, command)
                ret_break_num = SIM_breakpoint(pcell, Sim_Break_Physical, 
                   Sim_Access_Execute, range_start, size, 0)
                self.the_breaks.append(ret_break_num)
                command = 'set-substr %d "LR"' % ret_break_num
                SIM_run_alone(SIM_run_command, command)
            else:
                ret_break_num = SIM_breakpoint(cell, Sim_Break_Physical, 
                   Sim_Access_Execute, range_start, size, 0)
                self.the_breaks.append(ret_break_num)
                command = 'set-prefix %d "ret"' % ret_break_num
                SIM_run_alone(SIM_run_command, command)
            self.lgr.debug('done setting breakpoints for call and ret addr: 0x%x len: 0x%x' % (range_start, size))
        else:
            break_num = self.context_manager.genBreakpoint(pcell, Sim_Break_Physical, Sim_Access_Execute, 
                range_start, size, 0)
            self.the_breaks.append(break_num)

    def thinkExecuted(self, page_info):
        if self.cpu.architecture == 'arm':
            nx = memUtils.testBit(page_info.entry, 0)
            accessed = memUtils.testBit(page_info.entry, 4)
            if nx or not accessed: 
                #self.lgr.debug('thinkExecuted will skip 0x%x nx %r accessed %r' % (page_info.logical, nx, accessed)) 
                return False
        else:
            writable = memUtils.testBit(page_info.entry, 1)
            accessed = memUtils.testBit(page_info.entry, 5)
            if writable or not accessed:
                #self.lgr.debug('thinkExecuted will skip %r %r' % (writable, accessed)) 
                return False
        return True

    def pageTableBreaks(self, call_ret):
        ''' set call/ret breaks on all pages that appear executable '''
        pages = pageUtils.getPageBases(self.cpu, self.lgr, self.param.kernel_base)
        range_start = None
        prev_physical = None
        pcell = self.cpu.physical_memory
        page_count = 1
        for page_info in pages:
            if not self.thinkExecuted(page_info):
                continue
            #self.lgr.debug('phys: 0x%x  logical: 0x%x' % (page_info.physical, page_info.logical))
            if range_start is None:
                range_start = page_info.physical
                prev_physical = page_info.physical
            else:
                if page_info.physical == prev_physical + pageUtils.PAGE_SIZE:
                    prev_physical = page_info.physical
                    page_count = page_count + 1
                else:
                    #self.lgr.debug('Page not contiguous: 0x%x  range_start: 0x%x  prev_physical: 0x%x' % (page_info.physical, range_start, prev_physical))
                    self.doBreaks(pcell, range_start, page_count, call_ret) 
                    page_count = 1
                    range_start = page_info.physical
                    prev_physical = page_info.physical
        self.doBreaks(pcell, range_start, page_count, call_ret) 
        self.lgr.debug('set %d breaks', len(self.the_breaks)) 

    def doUncall(self, frame_ips=[]):
        ''' set breaks on calls and returns and reverse to find call into current function'''
        self.frame_ips = frame_ips
        self.need_calls = 0
        self.got_calls = 0
        self.is_monitor_running.setRunning(True)
        self.first_back = True
        dum_cpu, cur_addr, comm, pid = self.task_utils.currentProcessInfo(self.cpu)
        self.pid = pid
        self.lgr.debug('reservseToCall, back from call get procInfo %s' % comm)
        my_args = procInfo.procInfo(comm, self.cpu, pid)
        self.stop_hap = SIM_hap_add_callback("Core_Simulation_Stopped", 
	        self.stoppedReverseToCall, my_args)
        self.lgr.debug('doUncall, added stop hap')
        self.need_calls = 1
        self.uncall = True
        self.pageTableBreaks(True)
        #for item in self.x_pages:
        #    self.setBreakRange(self.cell_name, pid, item.address, item.length, self.cpu, comm, True)
        self.lgr.debug('doUncall, set break range')
        SIM_run_alone(SIM_run_command, 'reverse')
        #self.lgr.debug('reverseToCall, did reverse-step-instruction')
        self.lgr.debug('doUncall, did reverse')

    def tryBackOne(self, my_args):
        
        self.stop_hap = SIM_hap_add_callback("Core_Simulation_Stopped", 
	        self.tryOneStopped, my_args)
        self.lgr.debug('tryBackOne from cycle 0x%x' % my_args.cpu.cycles)
        SIM_run_command('rev 1')

    def jumpStopped(self, my_args, one, exception, error_string):
        eip = self.top.getEIP(self.cpu)
        self.lgr.debug('jumpStopped at 0x%x' % eip)
        SIM_hap_delete_callback_id("Core_Simulation_Stopped", self.jump_stop_hap)
        self.top.skipAndMail()

    def jumpCycle(self, cycle):
        self.lgr.debug('would jump to 0x%x' % cycle)
        #self.jump_stop_hap = SIM_hap_add_callback("Core_Simulation_Stopped", 
	#        self.jumpStopped, None)
        cmd = 'skip-to cycle = %d ' % cycle
        SIM_run_command(cmd)
        self.top.skipAndMail()

    def isExit(self, instruct, eip):
        if self.cpu.architecture == 'arm':
            lr = self.top.getReg('lr', self.cpu)
            #if eip == self.param.arm_ret or (instruct.startswith('mov') and instruct.endswith('lr') and lr < self.param.kernel_base):
            if eip == self.param.arm_ret:
                return True
        else: 
            if instruct == 'sysexit' or instruct == 'iretd' or instruct.startswith('sysret'):
                return True
        return False

        
    def isCall(self, instruct):
        if self.cpu.architecture == 'arm':
            N, Z, C, V = armCond.flags(self.cpu)
            if instruct.startswith('ble'):
                return Z or (N and not V) or (not N and V)
            if instruct.startswith('blt'):
                return (N and not V) or (not N and V)
            if instruct.startswith('blo'):
                return (not C)
            if instruct.startswith('bls'):
               return (not C) or Z
            elif instruct.startswith('bl'):
               return True
        else:
            if instruct.startswith('call'):
               return True
        return False
        
    def isRet(self, instruct):
        if self.cpu.architecture == 'arm':
            parts = instruct.split()
            if parts[0].strip().startswith('ld') and parts[1].startswith('pc'):
                return True
            if parts[0].strip().startswith('ldm') and 'pc' in instruct:
                return True

            if parts[0].strip().startswith('bxcc'):
                #return not armCond.cSet(self.cpu)
                # TBD fix this ?
                return False
            if parts[0].strip().startswith('bxeq'):
                return armCond.zSet(self.cpu)
            if parts[0].strip().startswith('bxne'):
                return not armCond.zSet(self.cpu)
            elif parts[0].strip().startswith('bx') and parts[1] == 'lr':
                return True

            if parts[0] == 'pop' and 'pc' in instruct:
                return True
        else:
            if instruct.startswith('ret'):
                return True
        return False

    def tooFarBack(self):
        cycles = self.cpu.cycles & 0xFFFFFFFFFFFFFFFF
        if cycles-1 <= self.start_cycles:
            return True
        else:
            return False

    def tryOneStopped(self, my_args, one, exception, error_string):
        '''
        Invoked when the simulation stops after trying to go back one
        '''
        if self.stop_hap is None:
            self.lgr.error('stoppedReverseToCall invoked though hap is none')
            return
        SIM_hap_delete_callback_id("Core_Simulation_Stopped", self.stop_hap)
        self.stop_hap = None
        #cmd = 'reverse-step-instruction'
        if self.tooFarBack():
            self.lgr.debug('At start of recording, cycle: 0x%x' % self.cpu.cycles)
            print('At start of recording, cycle: 0x%x' % self.cpu.cycles)
            self.cleanup(self.cpu)
            self.top.skipAndMail() 
            return
        cur_cpu, comm, pid  = self.task_utils.curProc()
        self.lgr.debug('tryOneStopped, pid:%d entered at cycle 0x%x' % (pid, self.cpu.cycles))
        eip = self.top.getEIP(self.cpu)
        instruct = SIM_disassemble_address(self.cpu, eip, 1, 0)
        self.lgr.debug('tryOneStopped reversed 1, eip: %x  %s' % (eip, instruct[1]))
        cpl = memUtils.getCPL(self.cpu)
        done = False
        if cpl > 0:
            self.lgr.debug('tryBackOne user space')
            if self.step_into or not self.isRet(instruct[1]):
                self.lgr.debug('tryBackOne worked ok')
                done = True
                self.cleanup(self.cpu)
                self.top.skipAndMail()
                self.context_manager.setExitBreaks()
        elif len(self.sysenter_cycles[pid]) > 0:
            cur_cycles = self.cpu.cycles
            self.lgr.debug('tryBackOne kernel space pid %d expected %d' % (pid, my_args.pid))
            is_exit = self.isExit(instruct[1], eip)
            if pid in self.sysenter_cycles and is_exit:
                self.lgr.debug('tryOneStopped is sysexit, cur_cycles is 0x%x' % cur_cycles)
                prev_cycles = None
                got_it = None
                page_cycles = self.sysenter_cycles[pid]
                if self.page_faults is not None:
                    self.lgr.debug('tryBackOne adding %d page faults to cycles' % (len(self.page_faults.getFaultingCycles())))
                    page_cycles = page_cycles + self.page_faults.getFaultingCycles()
                for cycles in sorted(page_cycles):
                    if cycles > cur_cycles:
                        self.lgr.debug('tryOneStopped found cycle between 0x%x and 0x%x' % (prev_cycles, cycles))
                        got_it = prev_cycles - 1
                        break
                    else:
                        self.lgr.debug('tryOneStopped is not cycle 0x%x' % (cycles))
                        prev_cycles = cycles

                if not got_it:
                    self.lgr.debug('tryOneStopped nothing between, assume last cycle of 0x%x' % prev_cycles)
                    got_it = prev_cycles - 1
                SIM_run_alone(self.jumpCycle, got_it)
                done = True
            elif pid in self.sysenter_cycles and not is_exit:
                self.lgr.debug('tryOneStopped in kernel but not exit? 0x%x  %s' % (eip, instruct[1]))
        

        if not done:
            self.lgr.debug('tryOneStopped, back one did not work, starting at %x' % eip)
            self.stop_hap = SIM_hap_add_callback("Core_Simulation_Stopped", 
    	        self.stoppedReverseToCall, my_args)
            self.lgr.debug('tryOneStopped, added stop hap')
            if self.previous_eip is not None and eip != self.previous_eip and cpl > 0:
                self.lgr.debug('tryOneStopped, prev %x not equal eip %x, assume syscall, set break on prev and rev' % (self.previous_eip, eip))
                self.setOneBreak(self.previous_eip, self.cpu)
            else: 
                self.uncall = False
                #for item in self.x_pages:
                #    self.setBreakRange(self.cell_name, my_args.pid, item.address, item.length, self.cpu, my_args.comm, False)
                self.pageTableBreaks(False)
                self.lgr.debug('tryOneStopped, set break range')
            SIM_run_alone(SIM_run_command, 'reverse')
            #self.lgr.debug('reverseToCall, did reverse-step-instruction')
            self.lgr.debug('tryOneStopped, did reverse')

        
    def doRevToCall(self, step_into, prev=None):
        self.noWatchSysenter()
        '''
        Run backwards.  If uncall is true, run until the previous call.
        If step_into is true, and the previous instruction is a return,
        enter the function at its return.
        '''

        dum_cpu, cur_addr, comm, pid = self.task_utils.currentProcessInfo(self.cpu)
        self.pid = pid
        self.is_monitor_running.setRunning(True)
        self.step_into = step_into
        self.first_back = True
        self.lgr.debug('reservseToCall, call get procInfo')
        self.lgr.debug('reservseToCall, back from call get procInfo %s' % comm)
        my_args = procInfo.procInfo(comm, self.cpu, self.pid)
        self.lgr.debug('reservseToCall, got my_args ')
        self.previous_eip = prev
        self.tryBackOne(my_args)

    def jumpOverKernel(self, pid):
        retval = False
        cur_cycles = self.cpu.cycles
        eip = self.top.getEIP(self.cpu)
        instruct = SIM_disassemble_address(self.cpu, eip, 1, 0)
        self.lgr.debug('doRevToModReg kernel space pid %d eip:0x%x %s' % (pid, eip, instruct[1]))
        is_exit = self.isExit(instruct[1], eip)
        if pid in self.sysenter_cycles and is_exit:
            self.lgr.debug('jumpOverKernel is sysexit, cur_cycles is 0x%x' % cur_cycles)
            '''
            prev_cycles = 0
            got_it = None
            page_cycles = self.sysenter_cycles[pid]
            if self.page_faults is not None:
                self.lgr.debug('jumpOverKernel adding %d page faults to cycles' % (len(self.page_faults.getFaultingCycles())))
                page_cycles = page_cycles + self.page_faults.getFaultingCycles()
            for cycles in sorted(page_cycles, reverse=True):
            #for cycles in sorted(page_cycles):
                self.lgr.debug('jumpOverKernel cur_cycles 0x%x cycles: 0x%x prev: 0x%x' % (cur_cycles, cycles, prev_cycles))
                if cycles < cur_cycles:
                    self.lgr.debug('jumpOverKernel found cycle between 0x%x and 0x%x' % (prev_cycles, cycles))
                    #got_it = prev_cycles - 1
                    got_it = cycles - 1
                    break
                else:
                    #self.lgr.debug('jumpOverKernel is not cycle 0x%x' % (cycles))
                    prev_cycles = cycles

            if not got_it:
                self.lgr.debug('jumpOverKernel nothing between, assume last cycle of 0x%x' % prev_cycles)
                got_it = prev_cycles - 1
            '''


            prev_cycles = None
            got_it = None
            page_cycles = self.sysenter_cycles[pid]
            if self.page_faults is not None:
                self.lgr.debug('tryBackOne adding %d page faults to cycles' % (len(self.page_faults.getFaultingCycles())))
                page_cycles = page_cycles + self.page_faults.getFaultingCycles()
            for cycles in sorted(page_cycles):
                if cycles > cur_cycles:
                    self.lgr.debug('tryOneStopped found cycle between 0x%x and 0x%x' % (prev_cycles, cycles))
                    got_it = prev_cycles - 1
                    break
                else:
                    self.lgr.debug('tryOneStopped is not cycle 0x%x' % (cycles))
                    prev_cycles = cycles

            if not got_it:
                self.lgr.debug('tryOneStopped nothing between, assume last cycle of 0x%x' % prev_cycles)
                got_it = prev_cycles - 1

            cmd = 'skip-to cycle = %d ' % got_it
            SIM_run_command(cmd)
            dum_cpu, cur_addr, comm, pid = self.task_utils.currentProcessInfo(self.cpu)
            rval = self.top.getReg(self.reg, self.cpu) 
            self.lgr.debug('jumpOverKernel pid:%d did skip to 0x%x landed at 0x%x rval 0x%x' % (pid, got_it, self.cpu.cycles, rval))
            if rval == self.reg_val:
                retval = True
            else:
                retval = False
                self.lgr.error('jumpOverKernel failed to maintain register')
        else:
            forward = self.cpu.cycles+1
            cmd = 'skip-to cycle = %d ' % forward
            SIM_run_command(cmd)
            eip = self.top.getEIP(self.cpu)
            self.lgr.error('jumpOverKernel in kernel, but not exit %s run back to 0x%x' % (instruct[1], eip-1))
            cell = self.top.getCell()
            self.uncall_break = SIM_breakpoint(cell, Sim_Break_Linear, Sim_Access_Execute, eip-1, 1, 0)
            self.uncall_hap = SIM_hap_add_callback("Core_Simulation_Stopped", self.kernInterruptHap, None)
            SIM_run_alone(SIM_run_command, 'rev')
        return retval

    def kernInterruptHap(self, my_args, one, exception, error_string):
        if self.uncall_break is None:
            return
        eip = self.top.getEIP(self.cpu)
        dum_cpu, cur_addr, comm, pid = self.task_utils.currentProcessInfo(self.cpu)
        self.lgr.debug('kernInterruptHap ip: 0x%x uncall_break %d pid: %d expected %d reg:%s self.reg_val 0x%x' % (eip, self.uncall_break, 
              pid, self.pid, self.reg, self.reg_val))
        if pid == self.pid:
            SIM_delete_breakpoint(self.uncall_break)
            SIM_hap_delete_callback_id("Core_Simulation_Stopped", self.uncall_hap)
            self.uncall_break = None
            val = self.top.getReg(self.reg, self.cpu) 
            if val == self.reg_val:
                self.lgr.debug('kernInterruptHap reg %s still 0x%x, now cycle back through instructions, but run alone' % (self.reg, val))
                SIM_run_alone(self.cycleAlone, None)
            else: 
                self.lgr.error('kernInterruptHap got val 0x%x, does not match 0x%x return to previous cycle?' % (val, self.reg_val))
                
        else:
            self.lgr.debug('kernInterruptHap, wrong pid, rev')
            SIM_run_alone(SIM_run_command, 'rev')

    '''
    BEWARE syntax errors are not seen.  TBD make unit test
    '''
    def doRevToModReg(self, reg, taint=False, offset=0, value=None, num_bytes=None):
        '''
        Run backwards until a write to the given register
        '''
        self.offset =  offset 
        self.taint = taint
        self.value = value
        self.num_bytes = num_bytes
        self.lgr.debug('\ndoRevToModReg cycle 0x%x for register %s offset is %x' % (self.cpu.cycles, reg, offset))
        self.reg = reg
        dum_cpu, cur_addr, comm, pid = self.task_utils.currentProcessInfo(self.cpu)
        self.pid = pid
        self.reg_num = self.cpu.iface.int_register.get_number(reg.upper())
        try:
            self.reg_val = self.cpu.iface.int_register.read(self.reg_num)
        except:
            self.lgr.error('doRevToModReg got bad regnum %d for reg <%s>' % (self.reg_num, reg))
            return
        eip = self.top.getEIP(self.cpu)
        self.lgr.debug('doRevToModReg starting at %x, looking for %s change from 0x%x' % (eip, reg, self.reg_val))
        done = False
        while not done:
            reg_mod_type = self.cycleRegisterMod()
            if reg_mod_type is None:
                ''' stepped back into kernel.  set hap and reverse '''
                self.lgr.debug('doRevToModReg entered kernel')
                if not self.tooFarBack():
    
                    if len(self.sysenter_cycles[pid]) > 0:
                        if not self.jumpOverKernel(pid):
                            self.lgr.debug('doRevModReg failed to jump over kernel')
                            done = True
                    else:
                        my_args = procInfo.procInfo(comm, self.cpu, self.pid)
                        self.stop_hap = SIM_hap_add_callback("Core_Simulation_Stopped", 
                    	     self.stoppedReverseModReg, my_args)
                        self.lgr.debug('doRevToModReg, added stop hap')
                        self.cell_name = self.top.getTopComponentName(self.cpu)
                        self.pageTableBreaks(False)
                        #for item in self.x_pages:
                        #    self.setBreakRange(self.cell_name, pid, item.address, item.length, self.cpu, comm, False, reg)
                        self.lgr.debug('doRevToModReg, set break range')
                        #SIM_run_alone(SIM_run_command, 'reverse-step-instruction')
                        SIM_run_alone(SIM_run_command, 'reverse')
                        #self.lgr.debug('reverseToCall, did reverse-step-instruction')
                        self.lgr.debug('reverseToModReg, did reverse')
                        done=True
                else:
                    self.lgr.debug('doRevModReg must have backed to 0x%x, first cycle was 0x%x' % (self.cpu.cycles, self.start_cycles))
                    done=True
            elif reg_mod_type.mod_type != RegisterModType.BAIL:
                done=True
                ''' current eip modifies self.reg, done, or continue taint '''
                self.lgr.debug('reverseToModReg got mod reg right off')
                if not self.taint:
                    self.cleanup(self.cpu)
                else:
                    if not self.tooFarBack():
                        if self.cpu.architecture == 'arm':
                            self.followTaintArm(reg_mod_type)
                        else:
                            self.followTaint(reg_mod_type)
                    else:
                        self.lgr.debug('doRevModReg must have backed to first cycle 0x%x' % self.start_cycles)
            else:
                self.lgr.debug('doRevModReg bailed, maybe trying uncall')
                done=True

    def rmBreaks(self):
        self.lgr.debug('rmBreaks')
        for breakpt in self.the_breaks:
            SIM_delete_breakpoint(breakpt)
        self.the_breaks = []

    def conditionalMet(self, mn):
        if self.cpu.architecture == 'arm':
            return armCond.condMet(self.cpu, mn)
        else:
            if mn.startswith('cmov'):
                eflags = self.top.getReg('eflags', self.cpu)
                if mn == 'cmovne' and not memUtils.testBit(eflags, 6):
                    return True
                elif mn == 'cmove' and memUtils.testBit(eflags, 6):
                    return True
                else:
                    return False
            else: 
                return True
    
    def cycleRegisterMod(self):
        '''
        Step backwards one cycle at a time looking for the register being modified.
        If kernel entered before the register is found, return False.
        TBD: ARM write-back operations
        '''
        retval = None
        done = False
        cur_val = self.cpu.iface.int_register.read(self.reg_num)
        self.lgr.debug('cycleRegisterMod start for %s value 0x%x cur_val 0x%x' % (self.reg, self.reg_val, cur_val))
        while not done:
            #current = SIM_cycle_count(self.cpu)
            current = self.cpu.cycles
            previous = current - 1
            SIM_run_command('pselect %s' % self.cpu.name)
            SIM_run_command('skip-to cycle = %d' % previous)
            self.lgr.debug('cycleRegisterMod skipped to 0x%x  cycle is 0x%x' % (previous, self.cpu.cycles))
            if self.tooFarBack():
                self.lgr.debug('cycleRegisterMod prev cycle 0x%x prior to first 0x%x, stop here' %(previous, self.start_cycles))
                break
            cpl = memUtils.getCPL(self.cpu)
            if cpl == 0:
                self.lgr.debug('cycleRegisterMod entered kernel')
                done = True
            else:
                cur_val = self.cpu.iface.int_register.read(self.reg_num)
                eip = self.top.getEIP(self.cpu)
                self.lgr.debug('crm compare %x to %x eip: %x' % (cur_val, self.reg_val, eip))
                '''
                if cur_val != self.reg_val: 
                    eip = self.top.getEIP(self.cpu)
                    self.lgr.debug('cycleRegisterMod at %x, we are done' % eip)
                    done = True
                    retval = True
                    self.is_monitor_running.setRunning(False)
                '''
                eip = self.top.getEIP(self.cpu)
                #self.lgr.debug('cycleRegisterMod do disassemble for eip 0x%x' % eip)
                instruct = SIM_disassemble_address(self.cpu, eip, 1, 0)
                self.lgr.debug('cycleRegisterMod disassemble for eip 0x%x is %s' % (eip, str(instruct)))
                mn = self.decode.getMn(instruct[1])
                self.lgr.debug('cycleRegisterMod decode is %s' % mn)
                if self.conditionalMet(mn):
                    if self.decode.modifiesOp0(mn):
                        self.lgr.debug('get operands from %s' % instruct[1])
                        op1, op0 = self.decode.getOperands(instruct[1])
                        self.lgr.debug('cycleRegisterMod mn: %s op0: %s  op1: %s' % (mn, op0, op1))
                        if self.decode.isReg(op0) and self.decode.regIsPart(op0, self.reg):
                            self.lgr.debug('cycleRegisterMod at %x, we are done' % eip)
                            done = True
                            retval = RegisterModType(None, RegisterModType.UNKNOWN)
                            if mn.startswith('ldr') and op1.startswith('[') and op1.endswith(']'):
                                addr = decodeArm.getAddressFromOperand(self.cpu, op1, self.lgr)
                                addr = addr & self.task_utils.getMemUtils().SIZE_MASK
                                if addr is not None:
                                    retval = RegisterModType(addr, RegisterModType.ADDR)
                            elif mn.startswith('mov') and self.decode.isReg(op1):
                                retval = RegisterModType(op1, RegisterModType.REG)
                                
                    elif self.cpu.architecture == 'arm': 
                        if ']!' in instruct[1]:
                            ''' Look for write-back register mod '''
                            ''' for now just look for [myreg, xxx]! '''
                            if self.decode.armWriteBack(instruct[1], self.reg):
                                done = True
                                retval = RegisterModType(None, RegisterModType.UNKNOWN)
                        elif mn.startswith('ldm') and self.reg in instruct[1] and '{' in instruct[1]:
                            addr = self.decode.armLDM(self.cpu, instruct[1], self.reg, self.lgr)
                            rval = self.task_utils.getMemUtils().readPtr(self.cpu, addr)
                            self.lgr.debug('cycleRegisterMod at %x, is ldm instruction addr 0x%x reg val 0x%x wanting 0x%x' % (eip, addr, rval, self.reg_val))
                            if rval != self.reg_val:
                                self.lgr.error('cycleRegisterMod wrong value')
                                done = True
                                retval = RegisterModType(None, RegisterModType.BAIL)
                            elif addr is not None:
                                done = True
                                pc_addr = self.decode.armLDM(self.cpu, instruct[1], 'pc', self.lgr)
                                if pc_addr is not None:
                                    pc = self.task_utils.getMemUtils().readPtr(self.cpu, pc_addr)
                                    self.lgr.debug('cycleRegisterMod try uncalling pc_addr 0x%x  pc 0x%x' % (pc_addr, pc))
                                    cell = self.top.getCell()
                                    pre_call = pc - 4
                                    self.uncall_break = SIM_breakpoint(cell, Sim_Break_Linear, Sim_Access_Execute, pre_call, 1, 0)
                                    self.uncall_hap = SIM_hap_add_callback("Core_Simulation_Stopped", self.uncallHap, None)
                                    retval = RegisterModType(None, RegisterModType.BAIL)
                                    self.lgr.debug('cycleRegisterMod set break number %d stop hap, now rev to 0x%x' % (self.uncall_break, pre_call))
                                    self.save_cycle = self.cpu.cycles
                                    SIM_run_alone(SIM_run_command,'rev')
                                else:
                                    retval = RegisterModType(addr, RegisterModType.ADDR)
                            else:
                                self.lgr.debug('cycleRegisterMod at %x, ldm instruction got None for addr' % eip)
                     
        self.lgr.debug('cycleRegisterMod return') 
        return retval

    def uncallHap(self, my_args, one, exception, error_string):
        if self.uncall_break is None:
            return
        eip = self.top.getEIP(self.cpu)
        dum_cpu, cur_addr, comm, pid = self.task_utils.currentProcessInfo(self.cpu)
        self.lgr.debug('uncallHap ip: 0x%x uncall_break %d pid: %d expected %d reg:%s self.reg_val 0x%x' % (eip, self.uncall_break, 
              pid, self.pid, self.reg, self.reg_val))
        if pid == self.pid:
            SIM_delete_breakpoint(self.uncall_break)
            SIM_hap_delete_callback_id("Core_Simulation_Stopped", self.uncall_hap)
            self.uncall_break = None
            val = self.top.getReg(self.reg, self.cpu) 
            if val == self.reg_val:
                self.lgr.debug('uncallHap reg %s still 0x%x, now cycle back through instructions, but run alone' % (self.reg, val))
                SIM_run_alone(self.cycleAlone, None)
            else: 
                self.lgr.debug('uncallHap got val 0x%x, does not match 0x%x return to previous cycle?' % (val, self.reg_val))
                cmd = 'skip-to cycle = %d ' % self.save_cycle
                SIM_run_command(cmd)
                if not self.taint:
                    self.cleanup(self.cpu)
                else:
                    if self.cpu.architecture == 'arm':
                        self.followTaintArm(self.save_reg_mod)
                    else:
                        self.followTaint(self.save_reg_mod)
                
        else:
            self.lgr.debug('uncallHap, wrong pid, rev')
            SIM_run_alone(SIM_run_command, 'rev')
                       

    def multOne(self, op0, mn):
        self.lgr.debug('multOne %s %s' % (op0, mn))
        if mn == 'imul':
            self.lgr.debug('multOne is imul')
            if self.decode.isReg(op0):
                mul = self.decode.getValue(op0, self.cpu, self.lgr)
                self.lgr.debug('multOne val of %s is 0x%x' % (op0, mul))
                if mul == 1:
                    return True
        return False

    def orValue(self, op1, mn):
        if self.value is not None and mn == 'or':
            if self.num_bytes == 1:
                address = self.decode.getAddressFromOperand(self.cpu, op1, self.lgr)
                if address is not None:
                    value = self.task_utils.getMemUtils().readWord32(self.cpu, address)
                    self.lgr.debug('orValue, address is 0x%x value 0x%x' % (address, value))
                    if value == self.value:
                        return True
        return False
            
    def followTaintArm(self, reg_mod_type):
        eip = self.top.getEIP(self.cpu)
        instruct = SIM_disassemble_address(self.cpu, eip, 1, 0)
        self.lgr.debug('followTaintArm %s' % instruct[0])
        if reg_mod_type is not None:
            if reg_mod_type.mod_type == RegisterModType.ADDR:
                address = reg_mod_type.value
                value = self.task_utils.getMemUtils().readWord32(self.cpu, address)
                self.lgr.debug('followTaintArm address 0x%x value 0x%x' % (address, value))
                self.bookmarks.setDebugBookmark('backtrack eip:0x%x inst:"%s"' % (eip, instruct[1]))
                self.cleanup(self.cpu)
                self.top.stopAtKernelWrite(address, self)
            elif reg_mod_type.mod_type == RegisterModType.REG:
                self.lgr.debug('followTaintArm reg %s' % reg_mod_type.value)
                self.doRevToModReg(reg_mod_type.value, taint=True)
                 

    def followTaint(self, reg_mod_type):
        ''' we believe the instruction at the current ip modifies self.reg 
            Where does its value come from? '''
        eip = self.top.getEIP(self.cpu)
        instruct = SIM_disassemble_address(self.cpu, eip, 1, 0)
        self.lgr.debug('followTaint instruct at 0x%x is %s' % (eip, str(instruct)))
        op1, op0 = self.decode.getOperands(instruct[1])
        mn = self.decode.getMn(instruct[1])
        if not self.multOne(op0, mn) and not mn.startswith('mov') and not mn == 'pop' and not mn.startswith('cmov') \
                                     and not self.orValue(op1, mn) and not mn == 'add':
            ''' NOTE: treating "or" and "add" and imult of one as a "mov" '''
            if mn == 'add':
               offset = None
               #offset = int(op1, 16)
               if '[' in op1:
                   address = self.decode.getAddressFromOperand(self.cpu, op1, self.lgr)
                   offset = self.task_utils.getMemUtils().readWord32(self.cpu, address)
                   self.lgr.debug('followTaint, add check of %s, address 0x%x offset is 0x%x' % (op1, address, offset))
               else:
                   offset = self.decode.getValue(op1, self.cpu, self.lgr)
                   self.lgr.debug('followTaint, add check offset of %s is 0x%x' % (op1, offset))
               if offset is not None and offset <= 8:
                   ''' wth, just an address adjustment? '''
                   self.lgr.debug('followTaint, add of %x, assume address adjust, e.g., heap struct' % offset)
                   self.bookmarks.setDebugBookmark('backtrack eip:0x%x inst:"%s"' % (eip, instruct[1]))
                   self.doRevToModReg(op0, taint=True)
                   return 
            self.lgr.debug('followTaint, not a move, we are stumped')
            self.bookmarks.setDebugBookmark('backtrack eip:0x%x inst:"%s" stumped' % (eip, instruct[1]))
            self.top.skipAndMail()

        elif mn == 'pop':
            esp = self.top.getReg('esp', self.cpu) 
            self.bookmarks.setDebugBookmark('backtrack eip:0x%x inst:"%s"' % (eip, instruct[1]))
            self.cleanup(self.cpu)
            self.top.stopAtKernelWrite(esp, self)

        elif self.decode.isReg(op1) and not self.decode.isIndirect(op1):
            self.lgr.debug('followTaint, is reg, track %s' % op1)
            self.doRevToModReg(op1, taint=True)
        elif self.decode.isReg(op1) and self.decode.isIndirect(op1):
            self.lgr.debug('followTaint, is indrect reg, track %s' % op1)
            address = self.decode.getAddressFromOperand(self.cpu, op1, self.lgr)
            self.bookmarks.setDebugBookmark('backtrack switch to indirect value:0x%x eip:0x%x inst:"%s"' % (self.value, eip, instruct[1]))
            self.doRevToModReg(op1, taint=True)

        #elif mn == 'lea':
        #    address = decode.getAddressFromOperand(self.cpu, op1, self.lgr)

        else:
            self.lgr.debug('followTaint, see if %s is an address' % op1)
            address = self.decode.getAddressFromOperand(self.cpu, op1, self.lgr)
            if address is not None:
                self.lgr.debug('followTaint, yes, address is 0x%x' % address)
                if self.decode.isByteReg(op0):
                    value = self.task_utils.getMemUtils().readByte(self.cpu, address)
                else:
                    value = self.task_utils.getMemUtils().readWord32(self.cpu, address)
                newvalue = self.task_utils.getMemUtils().getUnsigned(address+self.offset)
                protected_memory = ''
                if self.top.isProtectedMemory(newvalue):
                    protected_memory = ' protected'
                self.lgr.debug('followTaint BACKTRACK eip: 0x%x value 0x%x at address of 0x%x wrote to register %s call stopAtKernelWrite for 0x%x' % (eip, value, address, op0, newvalue))
                if not mn.startswith('mov'):
                    self.bookmarks.setDebugBookmark('taint branch %s eip:0x%x inst:%s' % (protected_memory, eip, instruct[1]))
                    self.lgr.debug('BT bookmark: taint branch %s eip:0x%x inst %s' % (protected_memory, eip, instruct[1]))
                else:
                    self.bookmarks.setDebugBookmark('backtrack%s eip:0x%x inst:"%s"' % (protected_memory, eip, instruct[1]))
                    self.lgr.debug('BT bookmark: backtrack %s eip:0x%x inst:"%s"' % (protected_memory, eip, instruct[1]))
                self.cleanup(self.cpu)
                if len(protected_memory) == 0:
                    self.top.stopAtKernelWrite(newvalue, self)
                else:
                    self.top.skipAndMail()
            else:
                self.lgr.debug('followTaint, BACKTRACK op1 %s not an address or register, stopping traceback' % op1)
                self.bookmarks.setDebugBookmark('backtrack eip:0x%x inst:"%s" stumped' % (eip, instruct[1]))
                self.top.skipAndMail()
       
    def cycleAlone(self, dumb): 
        self.lgr.debug('cycleAlone, entered looking for %s' % self.reg)
        cmd = 'reverse'
        reg_mod_type = self.cycleRegisterMod()
        if reg_mod_type is None:
            if not self.tooFarBack():
                ''' stepped back into kernel, rev '''
                self.lgr.debug('cycleAlone must have entered kernel, continue to previous place where this process ran')
                SIM_run_alone(SIM_run_command, cmd)
            else:
                self.lgr.debug('cycleAlone must have backed to first cycle 0x%x' % self.start_cycles)
        elif reg_mod_type.mod_type != RegisterModType.BAIL:
            ''' current eip modifies self.reg, done, or continue taint '''
            if not self.taint:
                self.cleanup(self.cpu)
            else:
                if not self.tooFarBack():
                    if self.cpu.architecture == 'arm':
                        self.followTaintArm(reg_mod_type)
                    else:
                        self.followTaint(reg_mod_type)
                else:
                    self.lgr.debug('cycleAlone must backed to first cycle 0x%x' % self.start_cycles)
 
    def stoppedReverseModReg(self, my_args, one, exception, error_string):
        '''
        Invoked when the simulation stops while looking for a modified register
        '''
        self.lgr.debug('stoppedReverseModReg, entered looking for %s' % self.reg)
        dum_cpu, cur_addr, comm, pid = self.task_utils.currentProcessInfo(self.cpu)
        cpl = memUtils.getCPL(self.cpu)
        if pid == self.pid and cpl != 0:
            self.cycleAlone(None)
        else:
            self.lgr.error('stoppedReverseModReg wrong process or in kernel pid %d expected %d' % (pid, self.pid))
            SIM_run_alone(SIM_run_command, cmd)
 
    def cleanup(self, cpu):
        self.lgr.debug('reverseToCall cleanup')
        self.context_manager.setExitBreaks()
        if self.stop_hap is not None:
            SIM_hap_delete_callback_id("Core_Simulation_Stopped", self.stop_hap)
            self.stop_hap = None
        self.rmBreaks()
        self.is_monitor_running.setRunning(False)
        if not self.taint:
            self.top.skipAndMail()
        self.lgr.debug('cleanup complete')

    def isSyscall(self, instruct):
        if self.cpu.architecture == 'arm':
            if instruct.startswith('svc 0'):
                return True
        else:
            if instruct.startswith('int 128') or instruct.startswith('sysenter'):
                return True
        return False

    def stoppedReverseToCall(self, my_args, one, exception, error_string):
        '''
        Invoked when the simulation stops while looking for a previous call
        '''
        if self.stop_hap is None:
            self.lgr.error('stoppedReverseToCall invoked though hap is none')
            return
        #cmd = 'reverse-step-instruction'
        cmd = 'reverse'
        cpu, cur_addr, comm, pid = self.task_utils.currentProcessInfo(self.cpu)
        current = SIM_cycle_count(cpu)
        self.lgr.debug('stoppedReverseToCall, entered %d (%s) cycle: 0x%x' % (pid, comm, current))
        #if current < self.top.getFirstCycle():
        if current <= self.start_cycles:
            self.lgr.debug('stoppedReverseToCall found cycle 0x%x prior to first, stop here' %(current))
            self.cleanup(cpu)
        #elif pid == my_args.pid and SIM_processor_privilege_level(cpu) != 0:
        elif pid == self.pid and memUtils.getCPL(cpu) != 0:
            eip = self.top.getEIP(cpu)
            instruct = SIM_disassemble_address(cpu, eip, 1, 0)
            if self.first_back and self.isSyscall(instruct[1]):
                self.lgr.debug('stoppedReverseToCall first back is syscall at %x, we are done' % eip)
                self.cleanup(cpu)
            elif (self.first_back and not self.uncall) and (not self.isRet(instruct[1]) or self.step_into):
                self.lgr.debug('stoppedReverseToCall first back not a ret or step_into at %x, we are done' % eip)
                self.cleanup(cpu)
            elif self.isCall(instruct[1]):
                self.got_calls += 1
                if self.got_calls == self.need_calls:
                    self.lgr.debug('stoppedReverseToCall %s at %x we must be done' % (instruct[1], eip))
                    self.cleanup(cpu)
                elif eip in self.frame_ips:
                    self.lgr.debug('stoppedReverseToCall %s at %x found stack frame entry, declare we are done' % (instruct[1], eip))
                    self.cleanup(cpu)
                else:
                   self.lgr.debug('stoppedReverseToCall 0x%x got call %s   got_calls %d, need %d' % (eip, instruct[1], self.got_calls, self.need_calls))
                   SIM_run_alone(SIM_run_command, cmd)
            elif self.isRet(instruct[1]):
                self.need_calls += 1
                self.lgr.debug('stoppedReverseToCall 0x%x got ret %s  need: %d' % (eip, instruct[1], self.need_calls))
                if self.first_back and not self.uncall:
                    self.rmBreaks()
                    ''' TBD fix this? '''
                    for item in self.x_pages:
                        self.setBreakRange(self.cell_name, pid, item.address, item.length, cpu, comm, True)
                SIM_run_alone(SIM_run_command, cmd)
            else:
                self.lgr.debug('stoppedReverseToCall Not call or ret at %x, is %s' % (eip, instruct[1]))
                SIM_run_alone(SIM_run_command, cmd)
        else:
            self.lgr.debug('stoppedReverseInstruction in wrong pid (%d) or in kernel, try again' % pid)
            SIM_run_alone(SIM_run_command, cmd)
        self.first_back = False
   
    def setOneBreak(self, address, cpu):
        self.lgr.debug('setOneBreak at 0x%x' % address)
        phys_block = cpu.iface.processor_info.logical_to_physical(address, Sim_Access_Read)
        cell = cpu.physical_memory
        call_break_num = SIM_breakpoint(cell, Sim_Break_Physical, 
                       Sim_Access_Execute, phys_block.address, 1, 0)
        self.the_breaks.append(call_break_num)

    def setBreakRange(self, cell_name, pid, start, length, cpu, comm, call_ret, reg=None):
        '''
        Set breakpoints to carpet the process's address space
        '''
        self.lgr.debug('setBreakRange begin')
        start, end = pageUtils.adjust(start, length, self.page_size)
        cell = cpu.physical_memory
        my_args = procInfo.procInfo(comm, cpu, pid, None, False)
        self.pid = pid
      
        self.lgr.debug('Adding breakpoints for %s:%d (%s) at %x through %x, given length was %x' % (cell_name, pid, comm, start, end, length))
        while start <= end:
            limit = start + self.page_size
            phys_block = cpu.iface.processor_info.logical_to_physical(start, Sim_Access_Read)
            if phys_block.address != 0:
                if call_ret:
                    # Set exectution breakpoints for "call" and "ret" instructions
                    call_break_num = SIM_breakpoint(cell, Sim_Break_Physical, 
                       Sim_Access_Execute, phys_block.address, self.page_size, 0)
                    self.the_breaks.append(call_break_num)
                    if cpu.architecture == 'arm':
                        command = 'set-prefix %d "bl"' % call_break_num
                    else:
                        command = 'set-prefix %d "call"' % call_break_num
                    SIM_run_alone(SIM_run_command, command)
                 
                    if cpu.architecture == 'arm':
                        ret_break_num = SIM_breakpoint(cell, Sim_Break_Physical, 
                           Sim_Access_Execute, phys_block.address, self.page_size, 0)
                        self.the_breaks.append(ret_break_num)
                        command = 'set-substr %d "PC"' % ret_break_num
                        SIM_run_alone(SIM_run_command, command)
                        ret_break_num = SIM_breakpoint(cell, Sim_Break_Physical, 
                           Sim_Access_Execute, phys_block.address, self.page_size, 0)
                        self.the_breaks.append(ret_break_num)
                        command = 'set-substr %d "LR"' % ret_break_num
                        SIM_run_alone(SIM_run_command, command)
                    else:
                        ret_break_num = SIM_breakpoint(cell, Sim_Break_Physical, 
                           Sim_Access_Execute, phys_block.address, self.page_size, 0)
                        self.the_breaks.append(ret_break_num)
                        command = 'set-prefix %d "ret"' % ret_break_num
                        SIM_run_alone(SIM_run_command, command)
                    self.lgr.debug('done setting breakpoints for call and ret addr: %x', phys_block.address)
                elif reg is not None:
                    all_break_num = SIM_breakpoint(cell, Sim_Break_Physical, 
                       Sim_Access_Execute, phys_block.address, self.page_size, 0)
                    # TBD substr only applies to mnemonic?
                    #command = 'set-substr %d "%s"' % (all_break_num, reg)
                    #SIM_run_alone(SIM_run_command, command)
                    self.the_breaks.append(all_break_num)
                    self.lgr.debug('done setting breakpoints for reg substring %s addr: %x' % (reg, phys_block.address))
                else:
                    all_break_num = SIM_breakpoint(cell, Sim_Break_Physical, 
                       Sim_Access_Execute, phys_block.address, self.page_size, 0)
                    self.lgr.debug('setBreakRange set phys addr 0x%x linear 0x%x' % (phys_block.address, start))
                    self.the_breaks.append(all_break_num)
                    
            elif phys_block.address == 0:
                self.lgr.debug('reverseToCall FAILED breakpoints for %s:%d (%s) at %x ' % (cell_name, pid, comm,
                    start))

            start = limit
        self.lgr.debug('setBreakRange done')

    def sysenterHap(self, prec, third, forth, memory):
        #reversing = SIM_run_command('simulation-reversing')
        reversing = False
        if reversing:
            return
        else:
            cur_cpu, comm, pid  = self.task_utils.curProc()
            if True or (cur_cpu == self.cpu and pid == self.pid):
                cycles = self.cpu.cycles
                if pid not in self.sysenter_cycles:
                    self.sysenter_cycles[pid] = []
                if cycles not in self.sysenter_cycles[pid]:
                    #eip = self.top.getEIP(self.cpu)
                    #reg_num = self.cpu.iface.int_register.get_number('eax')
                    #eax = self.cpu.iface.int_register.read(reg_num)
                    #self.lgr.debug('sysenterHap call %d at 0x%x, add cycle 0x%x' % (eax, eip, cycles))
                    #self.lgr.debug('third: %s  forth: %s' % (str(third), str(forth)))
                    self.sysenter_cycles[pid].append(cycles)
            


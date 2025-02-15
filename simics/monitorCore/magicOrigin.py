import cli
from simics import *
from resimHaps import *
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
'''
    Detect execution of magic instruction 99 and reset origin.
    Intended that a driver will execute the instruction to signify
    it is safe to reverse to that point without real world leakage.
'''
class MagicOrigin():
    def __init__(self, top, cpu, bookmarks, lgr):
        self.bookmarks = bookmarks
        self.cpu = cpu
        self.top = top
        self.lgr = lgr
        self.did_magic = False
        self.magic_hap = None
        self.break_simulation = False
        self.setMagicHap()

    def setMagicHap(self):
        if self.did_magic:
            return
        self.magic_hap = RES_hap_add_callback("Core_Magic_Instruction", self.magicHap, None)
        self.lgr.debug('magicOrigin setMagicHap')

    def deleteMagicHap(self):
        if self.magic_hap is not None:
            self.lgr.debug('magicOrigin deleteMagicHap')
            SIM_run_alone(self.deleteMagicHapAlone, None)

    def deleteMagicHapAlone(self, dumb):
        if self.magic_hap is not None:
            RES_hap_delete_callback_id("Core_Magic_Instruction", self.magic_hap)
            self.magic_hap = None

    def setOrigin(self, dumb=None):
        cmd = 'disconnect-real-network'
        SIM_run_command(cmd)
        cmd = 'default_service_node0.status'
        dumb,result = cli.quiet_run_command(cmd)
       
        ok = False 
        for line in result.splitlines():
            if 'connector_link0' in line:
                parts = line.split(':')
                node_connect = parts[0].strip()
                switch = parts[1].strip()
                cmd = '%s.status' % switch
                dumb,result = cli.quiet_run_command(cmd)
                for line in result.splitlines():
                    if 'default_service_node0' in line:
                        switch_device = line.split(':')[0].strip()
                        cmd = 'disconnect default_service_node0.%s %s.%s' % (node_connect, switch, switch_device)
                        dumb,result = cli.quiet_run_command(cmd)
                        cmd = 'default_service_node0.disable-service -all'
                        dumb,result = cli.quiet_run_command(cmd)
                        #cmd = 'default_service_node0.delete' 
                        #dumb,result = cli.quiet_run_command(cmd)
                        ok = True
                        break
                break
        if ok:
            self.lgr.debug('MagicOrigin real network disconnected along with connection to switch, set origin')
        else:
            self.lgr.debug('Did not find a service node to disconnect.')
        cmd = 'disable-reverse-execution'
        SIM_run_command(cmd)
        cmd = 'enable-reverse-execution'
        SIM_run_command(cmd)
        self.did_magic = True
        self.deleteMagicHap()
        self.lgr.debug('MagicOrigin to pid and then set origin')
        self.top.toPid(-1, callback=self.top.setOrigin)
        #self.bookmarks.setOrigin(self.cpu)
        #self.lgr.debug('MagicOrigin, continue')
        #SIM_run_command('c')

    def magicHap(self, dumb, cell, magic_number):
        ''' invoked when driver executes a magic instruction, indicating save to  
            establish a new origin '''
        if self.magic_hap is not None:
            if magic_number == 99:
                if self.break_simulation:
                    SIM_break_simulation('magic stop')
                else:
                    self.lgr.debug('MagicOrigin in magic hap 99    cell: %s  number: %d' % (str(cell), magic_number))
                    self.top.stopAndGo(self.setOrigin)
                    #SIM_run_alone(self.deleteMagicHapAlone, None)
    def didMagic(self):
        return self.did_magic

    def magicStop(self):
        self.break_simulation = True

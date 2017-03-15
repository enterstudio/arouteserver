# Copyright (C) 2017 Pier Carlo Chiodi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import subprocess
import time

from instances import InstanceError, BGPSpeakerInstance

class KVMInstance(BGPSpeakerInstance):

    MAX_BOOT_TIME = 60
    VIRSH_DOMAINNAME = None

    def __init__(self, *args, **kwargs):
        super(KVMInstance, self).__init__(*args, **kwargs)
        self.domain_name = self.VIRSH_DOMAINNAME

    @classmethod
    def _run(cls, cmd):
        cls.debug("Executing '{}'".format(cmd))
        try:
            dev_null = open(os.devnull, "w")
            stdout = subprocess.check_output(
                cmd.split(), stderr=dev_null
            )
            return stdout
        except subprocess.CalledProcessError as e:
            raise InstanceError(
                "Error executing the following command:\n"
                "\t{}\n"
                "Output follows:\n\n"
                "{}".format(cmd, e.output)
            )

    def is_running(self):
        res = self._run("virsh list --name --state-running")
        return self.domain_name in res

    def start(self):
        if not self.is_running():
            res = self._run("virsh start {}".format(self.domain_name))

            if "error:" in res:
                raise InstanceError(
                    "Can't run instance '{}'; "
                    "an error occurred while starting virsh domain '{}':\n"
                    "{}".format(self.name, self.domain_name, res)
                )

            time.sleep(3)
            if not self.is_running():
                raise InstanceError(
                    "The virsh domain '{}' failed to start".format(
                        self.domain_name
                    )
                )

            running = False
            for i in range(self.MAX_BOOT_TIME / 5):
                time.sleep(5)
                try:
                    res = self.run_cmd("uname -n")
                    if self.domain_name in res:
                        running = True
                        break
                except:
                    pass

            if not running:
                raise InstanceError(
                    "Instance '{}' seems not running after {} seconds".format(
                        self.name, self.MAX_BOOT_TIME
                    )
                )

            # The VM is now up and bgpd should be started too,
            # but configuration files have not been updated yet,
            # so call reload_config() in order to push them
            # to the VM and reload the daemon.
            self.reload_config()
        else:
            raise InstanceError("Instance '{}' already running.".format(self.name))

    def _graceful_shutdown(self):
        return False

    def stop(self):
        if not self.is_running():
            return

        if self._graceful_shutdown():
            time.sleep(10)

        for i in range(20 / 5):
            if not self.is_running():
                return
            time.sleep(5)

        if self.is_running():
            try:
                self._run("virsh shutdown {}".format(self.domain_name))
                for i in range(30 / 5):
                    if not self.is_running():
                        return
                    time.sleep(5)
            except:
                pass

        if self.is_running():
            try:
                self._run("virsh destroy {}".format(self.domain_name))
            except:
                pass

    def run_cmd(self, args):
        if not self.is_running():
            raise InstanceNotRunning(self.name)

        cmd = ("ssh -o BatchMode=yes -o ConnectTimeout=5 "
               "-o ServerAliveInterval=10 {user}@{ip} -i {path_to_key} "
               "{cmd}").format(
            user="root",
            ip=self.ip,
            path_to_key=os.path.expanduser("~/.ssh/arouteserver"),
            cmd=" ".join(args) if isinstance(args, list) else args
        )
        res = self._run(cmd)
        return res

    def _mount_files(self):
        for mount in self.get_mounts():
            cmd = ("scp -i {path_to_key} {host_file} "
                   "{user}@{ip}:{container_file} ".format(
                       host_file=mount["host"],
                       user="root",
                       ip="[{}]".format(self.ip) if ":" in self.ip else self.ip,
                       container_file=mount["container"],
                       path_to_key=os.path.expanduser("~/.ssh/arouteserver")
                    ))
            res = self._run(cmd)

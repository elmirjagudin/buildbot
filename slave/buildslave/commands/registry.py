# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

from twisted.python import reflect

commandRegistry = {
    # command name : fully qualified factory name (callable)
    "shell": "buildslave.commands.shell.SlaveShellCommand",
    "uploadFile": "buildslave.commands.transfer.SlaveFileUploadCommand",
    "uploadDirectory": "buildslave.commands.transfer.SlaveDirectoryUploadCommand",
    "downloadFile": "buildslave.commands.transfer.SlaveFileDownloadCommand",
    "repo": "buildslave.commands.repo.Repo",
    "mkdir": "buildslave.commands.fs.MakeDirectory",
    "rmdir": "buildslave.commands.fs.RemoveDirectory",
    "cpdir": "buildslave.commands.fs.CopyDirectory",
    "stat": "buildslave.commands.fs.StatFile",
    "glob": "buildslave.commands.fs.GlobPath",
    "listdir": "buildslave.commands.fs.ListDir",
}

# The command that have been supported by earlier versions of buildslave,
# but have been removed. Used for sending errors to older build masters.
removedCommands = [
    "svn", "bk", "cvs", "darcs", "git", "bzr", "hg", "p4", "mtn"
]


def getFactory(command):
    factory_name = commandRegistry[command]
    factory = reflect.namedObject(factory_name)
    return factory


def removedCommand(command):
    return command in removedCommands


def getAllCommandNames():
    return commandRegistry.keys() + removedCommands

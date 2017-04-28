"""

    Mininet: A simple networking testbed for OpenFlow/SDN!

author: Bob Lantz (rlantz@cs.stanford.edu)
author: Brandon Heller (brandonh@stanford.edu)

Mininet creates scalable OpenFlow test networks by using
process-based virtualization and network namespaces.

Simulated hosts are created as processes in separate network
namespaces. This allows a complete OpenFlow network to be simulated on
top of a single Linux kernel.

Each host has:

A virtual console (pipes to a shell)
A virtual interfaces (half of a veth pair)
A parent shell (and possibly some child processes) in a namespace

Hosts have a network interface which is configured via ifconfig/ip
link/etc.

This version supports both the kernel and user space datapaths
from the OpenFlow reference implementation (openflowswitch.org)
as well as OpenVSwitch (openvswitch.org.)

In kernel datapath mode, the controller and switches are simply
processes in the root namespace.

Kernel OpenFlow datapaths are instantiated using dpctl(8), and are
attached to the one side of a veth pair; the other side resides in the
host namespace. In this mode, switch processes can simply connect to the
controller via the loopback interface.

In user datapath mode, the controller and switches can be full-service
nodes that live in their own network namespaces and have management
interfaces and IP addresses on a control network (e.g. 192.168.123.1,
currently routed although it could be bridged.)

In addition to a management interface, user mode switches also have
several switch interfaces, halves of veth pairs whose other halves
reside in the host nodes that the switches are connected to.

Consistent, straightforward naming is important in order to easily
identify hosts, switches and controllers, both from the CLI and
from program code. Interfaces are named to make it easy to identify
which interfaces belong to which node.

The basic naming scheme is as follows:

    Host nodes are named h1-hN
    Switch nodes are named s1-sN
    Controller nodes are named c0-cN
    Interfaces are named {nodename}-eth0 .. {nodename}-ethN

Note: If the network topology is created using mininet.topo, then
node numbers are unique among hosts and switches (e.g. we have
h1..hN and SN..SN+M) and also correspond to their default IP addresses
of 10.x.y.z/8 where x.y.z is the base-256 representation of N for
hN. This mapping allows easy determination of a node's IP
address from its name, e.g. h1 -> 10.0.0.1, h257 -> 10.0.1.1.

Note also that 10.0.0.1 can often be written as 10.1 for short, e.g.
"ping 10.1" is equivalent to "ping 10.0.0.1".

Currently we wrap the entire network in a 'mininet' object, which
constructs a simulated network based on a network topology created
using a topology object (e.g. LinearTopo) from mininet.topo or
mininet.topolib, and a Controller which the switches will connect
to. Several configuration options are provided for functions such as
automatically setting MAC addresses, populating the ARP table, or
even running a set of terminals to allow direct interaction with nodes.

After the network is created, it can be started using start(), and a
variety of useful tasks maybe performed, including basic connectivity
and bandwidth tests and running the mininet CLI.

Once the network is up and running, test code can easily get access
to host and switch objects which can then be used for arbitrary
experiments, typically involving running a series of commands on the
hosts.

After all desired tests or activities have been completed, the stop()
method may be called to shut down the network.

"""

import os
import re
import select
import signal
import random
import sys
import threading

from time import sleep
from itertools import chain, groupby
from math import ceil

from mininet.cli import CLI
from mininet.log import info, error, debug, output, warn
from mininet.node import ( Node, Docker, Host, OVSKernelSwitch,
                           DefaultController, Controller, OVSSwitch )
from mininet.nodelib import NAT
from mininet.link import Link, Intf, TCLink
from mininet.util import ( quietRun, fixLimits, numCores, ensureRoot,
                           macColonHex, ipStr, ipParse, netParse, ipAdd,
                           waitListening )
from mininet.term import cleanUpScreens, makeTerms
from mininet.wifiAssociation import association
from mininet.wifiAccessPoint import accessPoint
from mininet.wifiChannel import channelParameters
from mininet.wifiDevices import deviceRange, deviceDataRate
from mininet.wifiMobility import mobility
from mininet.wifiModule import module
from mininet.wifiParameters import wifiParameters
from mininet.wifiPlot import plot
from mininet.wifiReport import report
from mininet.wifiPropagationModels import propagationModel_
from mininet.wifiMeshRouting import meshRouting

sys.path.append(str(os.getcwd())+'/mininet/')
from sumo.runner import sumo
from mininet.vanet import vanet
from __builtin__ import True

# Mininet version: should be consistent with README and LICENSE
VERSION = "2.3.0d1"

class Mininet( object ):
    "Network emulation with hosts spawned in network namespaces."

    def __init__( self, topo=None, switch=OVSKernelSwitch, host=Host, isWiFi=False,
                  controller=DefaultController, link=Link, intf=Intf, wifiRadios=0,
                  build=True, xterms=False, cleanup=False, ipBase='10.0.0.0/8',
                  inNamespace=False, autoSetMacs=False, autoStaticArp=False, autoPinCpus=False,
                  listenPort=None, waitConnected=False, 
                  ssid="my-ssid", mode="g", channel="6" ):
        """Create Mininet object.
           topo: Topo (topology) object or None
           switch: default Switch class
           host: default Host class/constructor
           controller: default Controller class/constructor
           link: default Link class/constructor
           intf: default Intf class/constructor
           ipBase: base IP address for hosts,
           build: build now from topo?
           xterms: if build now, spawn xterms?
           cleanup: if build now, cleanup before creating?
           inNamespace: spawn switches and controller in net namespaces?
           autoSetMacs: set MAC addrs automatically like IP addresses?
           autoStaticArp: set all-pairs static MAC addrs?
           autoPinCpus: pin hosts to (real) cores (requires CPULimitedHost)?
           listenPort: base listening port to open; will be incremented for
               each additional switch in the net if inNamespace=False"""
        self.thread = threading.Thread()
        self.topo = topo
        self.switch = switch
        self.baseStation = switch
        self.host = host
        self.controller = controller
        self.link = link
        self.intf = intf
        self.ipBase = ipBase
        self.ipBaseNum, self.prefixLen = netParse( self.ipBase )
        self.nextIP = 1  # start for address allocation
        self.inNamespace = inNamespace
        self.xterms = xterms
        self.cleanup = cleanup
        self.autoSetMacs = autoSetMacs
        self.autoStaticArp = autoStaticArp
        self.autoPinCpus = autoPinCpus
        self.numCores = numCores()
        self.nextCore = 0  # next core for pinning hosts to CPUs
        self.listenPort = listenPort
        self.waitConn = waitConnected       
        self.start_time = -1 #start mobility time
        self.set_seed = 10
        self.nroads = 0
        self.firstAssociation = True
        self.ifaceConfigured = False
        self.isVanet = False
        self.ssid = ssid        
        self.mode = mode
        self.channel = channel
        self.nameToNode = {}  # name to Node (Host/Switch) objects
        self.finalPosition = {}
        self.initialPosition = {}
        self.accessPoints = []
        self.apexists = []
        self.controllers = []
        self.hosts = []
        self.links = []
        self.missingStations = []
        self.missingWlanAP = []
        self.missingDataPath = {}
        self.newapif = []
        self.wifiNodes = []
        self.switches = []
        self.stations = []
        self.virtualWlan = []
        self.fixedPosition = []
        self.staMov = []
        self.terms = []  # list of spawned xterm processes
        self.isWiFi = isWiFi
        self.wifiRadios = wifiRadios
        Mininet.init()  # Initialize Mininet if necessary
        
        self.built = False
        if topo and build:
            self.build()

    def waitConnected( self, timeout=None, delay=.5 ):
        """wait for each switch to connect to a controller,
           up to 5 seconds
           timeout: time to wait, or None to wait indefinitely
           delay: seconds to sleep per iteration
           returns: True if all switches are connected"""
        info( '*** Waiting for switches to connect\n' )
        time = 0
        remaining = list( self.switches )
        while True:
            for switch in tuple( remaining ):
                if switch.connected():
                    info( '%s ' % switch )
                    remaining.remove( switch )
            if not remaining:
                info( '\n' )
                return True
            if time > timeout and timeout is not None:
                break
            sleep( delay )
            time += delay
        warn( 'Timed out after %d seconds\n' % time )
        for switch in remaining:
            if not switch.connected():
                warn( 'Warning: %s is not connected to a controller\n'
                      % switch.name )
            else:
                remaining.remove( switch )
        return not remaining

    def getNextIp( self ):
        ip = ipAdd( self.nextIP,
                    ipBaseNum=self.ipBaseNum,
                    prefixLen=self.prefixLen ) + '/%s' % self.prefixLen
        self.nextIP += 1
        return ip

    def addHost( self, name, cls=None, **params ):
        """Add host.
           name: name of host to add
           cls: custom host class/constructor (optional)
           params: parameters for host
           returns: added host"""      
        # Default IP and MAC addresses                
        defaults = { 'ip': ipAdd( self.nextIP,
                                  ipBaseNum=self.ipBaseNum,
                                  prefixLen=self.prefixLen ) +
                                  '/%s' % self.prefixLen }
        if self.autoSetMacs:
            defaults[ 'mac' ] = macColonHex( self.nextIP )
        if self.autoPinCpus:
            defaults[ 'cores' ] = self.nextCore
            self.nextCore = ( self.nextCore + 1 ) % self.numCores
        self.nextIP += 1
        defaults.update( params )
        if not cls:
        	cls = self.host
        h = cls( name, **defaults )  
        h.type = 'host'    
        self.hosts.append( h )
        self.nameToNode[ name ] = h
        return h

    def addStation( self, name, cls=None, **params ):
        """Add Station.
           name: name of station to add
           cls: custom host class/constructor (optional)
           params: parameters for host
           returns: added host"""
        #Default IP and MAC addresses
        defaults = { 'ip': ipAdd( self.nextIP,
                                  ipBaseNum=self.ipBaseNum,
                                  prefixLen=self.prefixLen ) +
                                  '/%s' % self.prefixLen}
        
        defaults['rssi'] = []
        defaults['txpower'] = []
        defaults['snr'] = []
        defaults['position'] = []
        defaults['frequency'] = []
        defaults['antennaGain'] = []
        defaults['antennaHeight'] = []
        defaults['wlan'] = []
        defaults['speed'] = 0
        defaults['txgain'] = []
        defaults['rxgain'] = []
        defaults['mode'] = []
        defaults['channel'] = [] 
        
        if self.autoSetMacs:
            defaults[ 'mac' ] = macColonHex( self.nextIP )
        if self.autoPinCpus:
            defaults[ 'cores' ] = self.nextCore
            self.nextCore = ( self.nextCore + 1 ) % self.numCores        
        defaults.update( params )        
        if not cls:
            cls = self.host
        sta = cls( name, **defaults )      
        
        mac = ("%s" % params.pop('mac', {}))
        if(mac!="{}"):        
            mac = mac.split(',')
            sta.mac = str(mac[0])
        elif self.autoSetMacs:
            sta.mac = defaults[ 'mac' ]
        
        self.hosts.append( sta )
        self.stations.append(sta)
        self.wifiNodes.append(sta)
        self.nameToNode[ name ] = sta        
        self.missingStations.append(sta)
        sta.type = 'station'
        
        position = ("%s" % params.pop('position', {}))
        if(position!="{}"):        
            position = position.split(',')
            sta.params['position'] = position
            self.fixedPosition.append(sta)
        else:
            sta.params['position'] = 0, 0, 0         
        
        channel = ("%s" % params.pop('channel', {}))
        if(channel!="{}"): 
            sta.params['channel'] = channel
        else:
            sta.params['channel'] = 1       
      
        mode = ("%s" % params.pop('mode', {}))
        if(mode!="{}"): 
            sta.params['mode'] = mode
        else:
            sta.params['mode'] = "g"
            
        passwd = ("%s" % params.pop('passwd', {}))
        if(passwd!="{}"): 
            sta.passwd = passwd
        else:
            sta.passwd = None
        
        equipmentModel = ("%s" % params.pop('equipmentModel', {}))
        if(equipmentModel!="{}"): 
            sta.equipmentModel = equipmentModel
        else:
            sta.equipmentModel = None
            
        encrypt = ("%s" % params.pop('encrypt', {}))
        if(encrypt!="{}"): 
            sta.encrypt = encrypt
        else:
            sta.encrypt = None
    
        self.range = ("%s" % params.pop('range', {}))
        if(self.range!="{}"):
            sta.range = int(self.range)
        else:
            value = deviceRange(sta)     
            sta.range = value.range - 15
                
        wifi = ("%s" % params.pop('wlans', {}))
        if(wifi!="{}"):        
            self.wifiRadios += int(wifi)
            for n in range(int(wifi)):
                self.virtualWlan.append(sta)    
                sta.func.append('none') 
                sta.params['txpower'].append(0)
                sta.params['wlan'].append(name+'-wlan'+str(n))
        else:
            self.wifiRadios += 1
            wifi = 1
            sta.func.append('none')
            self.virtualWlan.append(sta)
            sta.params['txpower'].append(0)
            sta.params['wlan'].append(name+'-wlan0')
        sta.nWlans = int(wifi)
        
        txpower = ("%s" % params.pop('txpower', {}))
        if(txpower!="{}"):
            sta.params['txpower'][0] = int(txpower)
        
        mobility.staList.append( sta )
        self.nextIP += 1        
        return sta

    def removeHost( self, name, **params):
        """
        Remove a host from the network at runtime.
        """
        if not isinstance( name, basestring ) and name is not None:
            name = name.name  # if we get a host object
        try:
            h = self.get(name)
        except:
            error("Host: %s not found. Cannot remove it.\n" % name)
            return False
        if h is not None:
            if h in self.hosts:
                self.hosts.remove(h)
            if name in self.nameToNode:
                del self.nameToNode[name]
            h.stop( deleteIntfs=True )
            debug("Removed: %s\n" % name)
            return True
        return False

    def addVehicle( self, name, cls=None, **params ):
        """Add Vehicle.
           name: name of vehicle to add
           cls: custom host class/constructor (optional)
           params: parameters for host
           returns: added host"""
        #Default IP and MAC addresses
        defaults = { 'ip': ipAdd( self.nextIP,
                                  ipBaseNum=self.ipBaseNum,
                                  prefixLen=self.prefixLen ) +
                                  '/%s' % self.prefixLen}
        
        if self.autoSetMacs:
            defaults[ 'mac' ] = macColonHex( self.nextIP )
        if self.autoPinCpus:
            defaults[ 'cores' ] = self.nextCore
            self.nextCore = ( self.nextCore + 1 ) % self.numCores        
        defaults.update( params )        
        if not cls:
            cls = self.host
        sta = cls( name, **defaults )      
        
        mac = ("%s" % params.pop('mac', {}))
        if(mac!="{}"):        
            mac = mac.split(',')
            sta.mac = str(mac[0])
        elif self.autoSetMacs:
            sta.mac = defaults[ 'mac' ]
        
        self.hosts.append( sta )
        self.stations.append(sta)
        self.wifiNodes.append(sta)
        self.nameToNode[ name ] = sta        
        self.missingStations.append(sta)
        sta.type = 'station'
        
        position = ("%s" % params.pop('position', {}))
        if(position!="{}"):        
            position = position.split(',')
            sta.params['position'] = position
            self.fixedPosition.append(sta)
        else:
            sta.params['position'] = 0, 0, 0         
        
        channel = ("%s" % params.pop('channel', {}))
        if(channel!="{}"): 
            sta.params['channel'] = channel
        else:
            sta.params['channel'] = 1
            
        max_speed = ("%s" % params.pop('max_speed', {}))
        if(max_speed!="{}"): 
            sta.max_speed = max_speed
        else:
            sta.max_speed = 10
            
        min_speed = ("%s" % params.pop('min_speed', {}))
        if(min_speed!="{}"): 
            sta.min_speed = min_speed
        else:
            sta.min_speed = 1
      
        mode = ("%s" % params.pop('mode', {}))
        if(mode!="{}"): 
            sta.params['mode'] = mode
        else:
            sta.params['mode'] = "g"
            
        passwd = ("%s" % params.pop('passwd', {}))
        if(passwd!="{}"): 
            sta.passwd = passwd
        else:
            sta.passwd = None
        
        equipmentModel = ("%s" % params.pop('equipmentModel', {}))
        if(equipmentModel!="{}"): 
            sta.equipmentModel = equipmentModel
        else:
            sta.equipmentModel = None
            
        encrypt = ("%s" % params.pop('encrypt', {}))
        if(encrypt!="{}"): 
            sta.encrypt = encrypt
        else:
            sta.encrypt = None
            
        self.range = ("%s" % params.pop('range', {}))
        if(self.range!="{}"):
            sta.range = int(self.range)
                
        wifi = ("%s" % params.pop('wlans', {}))
        if(wifi!="{}"):        
            self.wifiRadios += int(wifi)
            for n in range(int(wifi)):
                self.virtualWlan.append(sta)    
                sta.func.append('none')            
        else:
            self.wifiRadios += 1
            sta.func.append('none')
            wifi = 1
            self.virtualWlan.append(sta)
        sta.nWlans = int(wifi)
        
        self.nextIP += 1    
        self.isVanet = True
        return sta

    def addBaseStation( self, name, cls=None, **params ):
        """Add BaseStation.
           name: name of basestation to add
           cls: custom switch class/constructor (optional)
           returns: added switch
           side effect: increments listenPort ivar ."""
        defaults = { 'listenPort': self.listenPort,
                     'inNamespace': self.inNamespace, 
                     'channel': self.channel,
                     'mode': self.mode,
                     'ssid': self.ssid                 
                     }
        
        defaults['txpower'] = []
        defaults['position'] = []
        defaults['frequency'] = []
        defaults['antennaGain'] = []
        defaults['antennaHeight'] = []   
        defaults['txgain'] = []
        defaults['rxgain'] = []
        defaults['mode'] = []
        defaults['channel'] = [] 
        #defaults['wlan'] = []     
        defaults.update( params )        
        
        if not cls:
            cls = self.baseStation
        bs = cls( name, **defaults )
        if not self.inNamespace and self.listenPort:
            self.listenPort += 1
        self.wifiNodes.append(bs)
        self.nameToNode[ name ] = bs
        bs.type = 'accessPoint'
        
        position = ("%s" % params.pop('position', {}))
        if(position!="{}"):        
            position =  position.split(',')
            bs.params['position'] = position
        else:
            bs.params['position'] = 0, 0, 0           
      
        channel = ("%s" % params.pop('channel', {}))
        if(channel!="{}"):
            bs.params['channel'] = channel
        else:
            bs.params['channel'] = self.channel 
            
        equipmentModel = ("%s" % params.pop('equipmentModel', {}))
        if(equipmentModel!="{}"):
            bs.equipmentModel = equipmentModel
        else:
            bs.equipmentModel = None
      
        mode = ("%s" % params.pop('mode', {}))
        if(mode!="{}"):
            bs.params['mode'] = mode
        else:
            bs.params['mode'] = self.mode
                      
        ssid = ("%s" % params.pop('ssid', {}))
        if(ssid!="{}"):
            bs.ssid.append(ssid)
        else:
            bs.ssid.append(self.ssid)
            
        passwd = ("%s" % params.pop('passwd', {}))
        if(passwd!="{}"):
            bs.passwd = passwd
        else:
            bs.passwd = None
            
        encrypt = ("%s" % params.pop('encrypt', {}))
        if(encrypt!="{}"):
            bs.encrypt = encrypt
        else:
            bs.encrypt = None
        
        self.range = ("%s" % params.pop('range', {}))
        if(self.range!="{}"):
            bs.range = int(self.range)
        else:
            value = deviceRange(bs)     
            bs.range = value.range     
                
        wifi = ("%s" % params.pop('wlans', {}))
        if(wifi!="{}"):        
            self.wifiRadios += int(wifi)
            for n in range(int(wifi)):
                self.virtualWlan.append(bs)
                bs.params['txpower'].append(0)
                #bs.params['wlan'].append(name+'-wlan'+str(n))
        else:
            self.wifiRadios += 1
            wifi = 1
            self.virtualWlan.append(bs)
            bs.params['txpower'].append(0)
            #bs.params['wlan'].append(name+'-wlan0')
        
        bs.nWlans = int(wifi)
        
        txpower = ("%s" % params.pop('txpower', {}))
        if(txpower!="{}"):
            bs.params['txpower'][0] = int(txpower)  
        
        self.missingWlanAP.append(bs)
        mobility.apList.append( bs )
        self.switches.append( bs )          
        self.accessPoints.append( bs ) 
        
        return bs
    
    def addPhysicalBaseStation( self, name, cls=None, **params ):
        """Add BaseStation.
           name: name of basestation to add
           cls: custom switch class/constructor (optional)
           returns: added switch
           side effect: increments listenPort ivar ."""
        defaults = { 'listenPort': self.listenPort,
                     'inNamespace': self.inNamespace, 
                     'channel': self.channel,
                     'mode': self.mode,
                     'ssid': self.ssid                 
                     }
        
        defaults['txpower'] = []
        defaults['position'] = []
        defaults['frequency'] = []
        defaults['antennaGain'] = []
        defaults['antennaHeight'] = []   
        defaults['txgain'] = []
        defaults['rxgain'] = []     
        defaults['mode'] = []
        defaults['channel'] = [] 
        defaults.update( params )        
        
        if not cls:
            cls = self.baseStation
        bs = cls( name, **defaults )
        if not self.inNamespace and self.listenPort:
            self.listenPort += 1
        self.wifiNodes.append(bs)
        self.nameToNode[ name ] = bs
        bs.type = 'accessPoint'
        
        wlan = ("%s" % params.pop('wlan', {}))
        bs.params['wlan'] = wlan
        
        position = ("%s" % params.pop('position', {}))
        if(position!="{}"):        
            position =  position.split(',')
            bs.params['position'] = position
        else:
            bs.params['position'] = 0, 0, 0           
      
        channel = ("%s" % params.pop('channel', {}))
        if(channel!="{}"):
            bs.params['channel'] = channel
        else:
            bs.params['channel'] = self.channel 
            
        equipmentModel = ("%s" % params.pop('equipmentModel', {}))
        if(equipmentModel!="{}"):
            bs.equipmentModel = equipmentModel
        else:
            bs.equipmentModel = None
      
        mode = ("%s" % params.pop('mode', {}))
        if(mode!="{}"):
            bs.params['mode'] = mode
        else:
            bs.params['mode'] = self.mode
                      
        ssid = ("%s" % params.pop('ssid', {}))
        if(ssid!="{}"):
            bs.ssid.append(ssid)
        else:
            bs.ssid.append(self.ssid)
            
        passwd = ("%s" % params.pop('passwd', {}))
        if(passwd!="{}"):
            bs.passwd = passwd
        else:
            bs.passwd = None
            
        encrypt = ("%s" % params.pop('encrypt', {}))
        if(encrypt!="{}"):
            bs.encrypt = encrypt
        else:
            bs.encrypt = None
        
        self.range = ("%s" % params.pop('range', {}))
        if(self.range!="{}"):
            bs.range = int(self.range)
        else:
            value = deviceRange(bs)     
            bs.range = value.range       
        
        self.wifiRadios += 1
        self.virtualWlan.append(bs)
        bs.params['txpower'].append(0)
        bs.nWlans = 1
        
        txpower = ("%s" % params.pop('txpower', {}))
        if(txpower!="{}"):
            bs.params['txpower'][0] = int(txpower) 
        
        self.missingWlanAP.append(bs)
        mobility.apList.append( bs )
        self.switches.append( bs )          
        self.accessPoints.append( bs ) 
        
        return bs
     
    def addSwitch( self, name, cls=None, **params ):
        """Add switch.
           name: name of switch to add
           cls: custom switch class/constructor (optional)
           returns: added switch
           side effect: increments listenPort ivar ."""
        defaults = { 'listenPort': self.listenPort,
                     'inNamespace': self.inNamespace }
        
        defaults.update( params )
        
        if not cls:
            cls = self.switch
        
        sw = cls( name, **defaults )
        sw.type = 'switch'
        
        if not self.inNamespace and self.listenPort:
            self.listenPort += 1
        self.switches.append( sw )
        self.nameToNode[ name ] = sw
        return sw

    def addController( self, name='c0', controller=None, **params ):
        """Add controller.
           controller: Controller class"""
        # Get controller class
        if not controller:
            controller = self.controller
        # Construct new controller if one is not given
        if isinstance( name, Controller ):
            controller_new = name
            
            # Pylint thinks controller is a str()
            # pylint: disable=maybe-no-member
            name = controller_new.name
            # pylint: enable=maybe-no-member
        else:
            controller_new = controller( name, **params )
        # Add new controller to net
        if controller_new:  # allow controller-less setups
            self.controllers.append( controller_new )
            self.nameToNode[ name ] = controller_new
        return controller_new

    def addNAT( self, name='nat0', connect=True, inNamespace=False,
                **params):
        """Add a NAT to the Mininet network
           name: name of NAT node
           connect: switch to connect to | True (s1) | None
           inNamespace: create in a network namespace
           params: other NAT node params, notably:
               ip: used as default gateway address"""
        nat = self.addHost( name, cls=NAT, inNamespace=inNamespace,
                            subnet=self.ipBase, **params )
        # find first switch and create link
        if connect:
            if not isinstance( connect, Node ):
                # Use first switch if not specified
                connect = self.switches[ 0 ]
            # Connect the nat to the switch
            self.addLink( nat, connect )
            # Set the default route on hosts
            natIP = nat.params[ 'ip' ].split('/')[ 0 ]
            for host in self.hosts:
                if host.inNamespace:
                    host.setDefaultRoute( 'via %s' % natIP )
        return nat

    def addOfDataPath(self, node, iface):
        self.missingDataPath[node] = iface

    # BL: We now have four ways to look up nodes
    # This may (should?) be cleaned up in the future.
    def getNodeByName( self, *args ):
        "Return node(s) with given name(s)"
        if len( args ) == 1:
            return self.nameToNode[ args[ 0 ] ]
        return [ self.nameToNode[ n ] for n in args ]

    def get( self, *args ):
        "Convenience alias for getNodeByName"
        return self.getNodeByName( *args )

    # Even more convenient syntax for node lookup and iteration
    def __getitem__( self, key ):
        """net [ name ] operator: Return node(s) with given name(s)"""
        return self.nameToNode[ key ]

    def __iter__( self ):
        "return iterator over node names"
        for node in chain( self.hosts, self.switches, self.controllers ):
            yield node.name

    def __len__( self ):
        "returns number of nodes in net"
        return ( len( self.hosts ) + len( self.switches ) +
                 len( self.controllers ) )

    def __contains__( self, item ):
        "returns True if net contains named node"
        return item in self.nameToNode

    def keys( self ):
        "return a list of all node names or net's keys"
        return list( self )

    def values( self ):
        "return a list of all nodes or net's values"
        return [ self[name] for name in self ]

    def items( self ):
        "return (key,value) tuple list for every node in net"
        return zip( self.keys(), self.values() )

    @staticmethod
    def randMac():
        "Return a random, non-multicast MAC address"
        return macColonHex( random.randint(1, 2**48 - 1) & 0xfeffffffffff |
                            0x020000000000 )
    
    def addMesh( self, sta, cls=None, **params ):
        
        wlan = sta.wlanToAssociate        

	if not sta.func:
		sta.func.append('mesh')
	else:
	        sta.func[wlan] = 'mesh' 
        
        if self.firstAssociation:
            self.configureWifiNodes()
        self.firstAssociation = False
        
        options = { 'ip': ipAdd( self.nextIP,
                                  ipBaseNum=self.ipBaseNum,
                                  prefixLen=self.prefixLen ) +
                                  '/%s' % self.prefixLen}
        
        options.update( params ) 
         
        ip = ("%s" % params.pop('ip', {}))
        if wlan == 0 and ip!="{}":
            sta.params.update(options)
        
        node = sta if not isinstance( sta, basestring ) else self[ sta ]
        
        channel = ("%s" % params.pop('channel', {}))
        if(channel!="{}"): 
            sta.params['channel'] = channel
        else:
            sta.params['channel'] = 1
            
        ssid = ("%s" % params['ssid'])
        if(ssid!="{}"):
            if not sta.ssid: 
		sta.ssid.append(ssid) 
	    else:
		sta.ssid[wlan] = ssid
        else:
            sta.ssid[wlan] = 'meshNetwork'
        sta.params['mp' + str(wlan)] = sta.ssid[wlan]
        sta.params['isMesh'] = True
        sta.wlanToAssociate+=1
        
        mode = ("%s" % params.pop('mode', {}))
        if(mode!="{}"):
            sta.params['mode'] = mode
        else:
            sta.params['mode'] = 'g'
            
        value = deviceRange(sta)
        sta.range = value.range-15
        
        for n in self.hosts:
            if (n == node):
                #station.addMesh(n, **options)
                if n in self.missingStations:
                    self.missingStations.remove(n)
        
        value = deviceDataRate(None, sta, None)
        self.bw = value.rate        
        
        #if mac!="{}":
        #    mac = mac
        #    del options['mac']
        #else:
        #    mac = self.randMac()
        options['sta'] = sta
        options.update( params )        
        #options.setdefault( 'bw', self.bw )
        # Set default MAC - this should probably be in Link
        options.setdefault( 'addr1', self.randMac() )
        
	cls = self.link if cls is None else cls
        link = cls( node, 'mesh', **options )
        
        return link    
    
    def addHoc( self, sta, cls=None, **params ):
        sta.func[sta.wlanToAssociate] = 'adhoc' 
        
        if self.firstAssociation:
            self.configureWifiNodes()
        self.firstAssociation = False
        
        options = { 'ip': ipAdd( self.nextIP,
                                  ipBaseNum=self.ipBaseNum,
                                  prefixLen=self.prefixLen ) +
                                  '/%s' % self.prefixLen}
        options.update( params )  
        
        ip = ("%s" % params.pop('ip', {}))
        if sta.wlanToAssociate == 0 and ip!="{}":
            sta.params.update(options)
            
        node = sta if not isinstance( sta, basestring ) else self[ sta ]
        
        channel = ("%s" % params.pop('channel', {}))
        if(channel!="{}"): 
            sta.params['channel'] = channel
        else:
            sta.params['channel'] = 1
            
        ssid = ("%s" % params.pop('ssid', {}))
        if(ssid!="{}"):
            sta.ssid[sta.wlanToAssociate] = ssid
        else:
            sta.ssid[sta.wlanToAssociate] = 'adhocNetwork'
        sta.wlanToAssociate+=1
            
        mode = ("%s" % params.pop('mode', {}))
        if(mode!="{}"):
            sta.params['mode'] = mode
        else:
            sta.params['mode'] = 'g'
            
        value = deviceRange(sta)
        sta.range = value.range-15
            
        value = deviceDataRate(None, sta, None)
        self.bw = value.rate
        
        options['sta'] = sta
        options.update( params )  
        options.setdefault( 'bw', self.bw )
        # Set default MAC - this should probably be in Link
        options.setdefault( 'addr1', self.randMac() )
        
        cls = self.link if cls is None else cls
        link = cls( sta, 'alone', **options )
        
        for sta in self.hosts:
            if (sta == node):
                #station.adhoc(sta, **options)
                if sta in self.missingStations:
                    self.missingStations.remove(sta)       
        return link
    
    def wifiDirect( self, sta, cls=None, **params ):
        
        if self.firstAssociation:
            self.configureWifiNodes()
        self.firstAssociation = False
        
        options = { 'ip': ipAdd( self.nextIP,
                                  ipBaseNum=self.ipBaseNum,
                                  prefixLen=self.prefixLen ) +
                                  '/%s' % self.prefixLen}
        options.update( params )
        
        node = sta if not isinstance( sta, basestring ) else self[ sta ]
        
        cmd = ("echo \'")
        cmd = cmd + 'ctrl_interface=/var/run/wpa_supplicant\
            \nap_scan=1\
            \np2p_go_ht40=1\
            \ndevice_name=%s\
            \ndevice_type=1-0050F204-1\
            \np2p_no_group_iface=1'  % (sta)
        apcommand = cmd + ("\' > %s_wifiDirect.conf" % sta)  
        os.system(apcommand)
        node.cmd('wpa_supplicant -B -Dnl80211 -i%s-wlan0 -d -c%s_wifiDirect.conf' % (sta,sta) )
        
        accessPoint.wpa_supplicantIsRunning = True
        
        value = deviceDataRate(None, node, None)
        self.bw = value.rate
        
        options['sta'] = node
        options.update( params )  
        options.setdefault( 'bw', self.bw )
        # Set default MAC - this should probably be in Link
        options.setdefault( 'addr1', self.randMac() )
        
        cls = self.link if cls is None else cls
        link = cls( node, 'alone', **options )
        
        for sta in self.hosts:
            if (sta == node):
                #station.adhoc(sta, **options)
                if sta in self.missingStations:
                    self.missingStations.remove(sta)       
        return link
        
      
    def configureAP(self):
        """Configure AP""" 
        for ap in self.accessPoints:
            i = 0
            if 'wlan' in ap.params:
                i = -1
            for wlan in range(i,ap.nWlans):
                wifiparam = dict()
                if 'wlan' not in ap.params:
                    intf = self.newapif[self.virtualWlan.index(ap)]
                    iface = str(ap)+'-wlan%s' % wlan
                    wifiparam.setdefault( 'intf', intf )
                    ap.params['frequency'].append(wlan)
                    ap.params['antennaHeight'].append(2)
                    ap.params['antennaGain'].append(1)
                else:
                    iface = ap.params.get('wlan')
                
                self.auth_algs = None
                self.wpa = None
                self.wpa_key_mgmt = None
                self.rsn_pairwise = None
                self.wpa_passphrase = None
                self.wep_key0 = None
                self.country_code = None
                self.wmm_enabled = None    
                
                if ap.encrypt == 'wpa':
                    self.auth_algs = 1
                    self.wpa = 1
                    self.wpa_key_mgmt = 'WPA-PSK'
                    self.wpa_passphrase = ap.passwd
                    accessPoint.wpa_supplicantIsRunning = True
                elif ap.encrypt == 'wpa2':
                    self.auth_algs = 1
                    self.wpa = 2
                    self.wpa_key_mgmt = 'WPA-PSK'
                    self.rsn_pairwise = 'CCMP'
                    self.wpa_passphrase = ap.passwd
                    accessPoint.wpa_supplicantIsRunning = True
                elif ap.encrypt == 'wep':
                    self.auth_algs = 2
                    self.wep_key0 = ap.passwd
                
                wifiparam.setdefault( 'encrypt', ap.encrypt )    
                wifiparam.setdefault( 'country_code', self.country_code )
                wifiparam.setdefault( 'auth_algs', self.auth_algs )
                wifiparam.setdefault( 'wpa', self.wpa )
                wifiparam.setdefault( 'wpa_key_mgmt', self.wpa_key_mgmt )
                wifiparam.setdefault( 'rsn_pairwise', self.rsn_pairwise )
                wifiparam.setdefault( 'wpa_passphrase', self.wpa_passphrase )
                wifiparam.setdefault( 'wep_key0', self.wep_key0 )
                if 'wlan' not in ap.params:
                    wifiparam.setdefault( 'wlan', wlan )                               
                accessPoint(ap, **wifiparam)   
                
                if 'wlan' not in ap.params:
                    wifiParameters(param='get_frequency', node=ap, wlan=wlan, iface=iface)
                    wifiParameters(param='get_tx_power', node=ap, wlan=wlan, iface=iface) 
                else:
                    cls = None
                    cls = self.link if cls is None else cls
                    iface = ap.params.get('wlan')
                    options = dict()
                    options.setdefault( 'intfName1', iface )
                    cls( ap, 'alone', **options )
                    ap.params.pop("wlan", None)
            
    """    
    def wds( self, ap1, ap2, cls=None, **params ):
        
        if('ap' in str(ap1) and 'ap' in str(ap2)):
            
            if self.firstAssociation:
                module.startEnvironment()
                self.link = TCLink
                self.newapif = getWlan.virtual()  #Get Virtual Wlans      
                self.firstAssociation = False
                station.assingIface(self.hosts)
                
            node1 = ap1 if not isinstance( ap1, basestring ) else self[ ap1 ]
            node2 = ap2 if not isinstance( ap2, basestring ) else self[ ap2 ]
        
            ap1 = str(node1)
            self.apexists.append(ap1) 
            ap2 = str(node2)
            self.apexists.append(ap2)
            
            int1 = self.newapif[module.virtualWlan.index(ap1)]
            int2 = self.newapif[module.virtualWlan.index(ap2)]
            accessPoint.wds(ap1, int1, ap2, int2)
            
            #configure AP
            self.configureAP(ap1)
            self.configureAP(ap2)
                
            self.bw = wifiParameters.set_bw(self.mode)
    """
                                
    def configureWifiNodes(self):
        if self.ifaceConfigured == False:
            physicalWlan, phyList = module.start(self.wifiRadios)
            self.isWiFi = True
            self.link = TCLink
            self.newapif = module.getWlanIface(physicalWlan)  #Get Virtual Wlans      
            module.assingIface(self.stations, self.virtualWlan, physicalWlan, phyList)
            self.ifaceConfigured = True
            self.configureAP() #configure AP
            self.firstAssociation = False            
            
    def addLink( self, node1, node2, port1=None, port2=None,
                 cls=None, **params ):
        """"Add a link from node1 to node2
            node1: source node (or name)
            node2: dest node (or name)
            port1: source port (optional)
            port2: dest port (optional)
            cls: link class (optional)
            params: additional link params (optional)
            returns: link object"""
        # Accept node objects or names
        node1 = node1 if not isinstance( node1, basestring ) else self[ node1 ]
        node2 = node2 if not isinstance( node2, basestring ) else self[ node2 ]
        options = dict( params )
        
        #If AP and STA
        if((node1.type =='station' and node2.type == 'accessPoint') \
            or ( node2.type =='station' and node1.type == 'accessPoint')):
            
            if self.firstAssociation:
                self.configureWifiNodes()
                
            #Only if AP
            if node1.type == 'accessPoint' and str(node1) not in self.apexists \
                or node2.type == 'accessPoint' and str(node2) not in self.apexists:
        
                if node1.type == 'accessPoint':
                    ap = node1
                    self.apexists.append(str(node1)) 
                else:
                    ap = node2
                    self.apexists.append(str(node2))
                
            if (node1.type =='station' or node2.type =='station'):
                if node1.type =='station':
                    sta = node1
                    ap = node2
                else:
                    sta = node2
                    ap = node1
               
                if sta in self.missingStations:
                    self.missingStations.remove(sta)
                
                if sta.mac != '':
                    Node.setMac(sta) 
                    
                value = deviceDataRate(ap, sta, None)
                self.bw = value.rate
                
                options.setdefault( 'bw', self.bw )
                options.setdefault( 'use_tbf', True )
                
                # Set default MAC - this should probably be in Link
                options.setdefault( 'addr1', sta.mac )
                
                cls = self.link if cls is None else cls
                link = cls( sta, 'alone', **options )
                
                #If sta/ap have defined position 
                if sta.params['position'] !=0 and ap.params['position'] !=0:
                    dist = channelParameters.getDistance(sta, ap)
                    if dist > ap.range:
                        doAssociation = False
                    else:
                        doAssociation = True
                #if not
                else:
                    doAssociation = True
                                
                if(doAssociation):
                    Node.associate(sta, ap)
            return link
        
        else:
            """"Add a link from node1 to node2
                node1: source node (or name)
                node2: dest node (or name)
                port1: source port (optional)
                port2: dest port (optional)
                cls: link class (optional)
                params: additional link params (optional)
                returns: link object"""
            
            #Only if AP
            if node1.type == 'accessPoint' and node2.type == 'accessPoint' :   
                if self.firstAssociation:
                    self.configureWifiNodes()              
                
                listap = []
                if str(node1) not in self.apexists:
                    listap.append(str(node1))
                if str(node2) not in self.apexists:
                    listap.append(str(node2))
                    
                if str(node1) not in self.apexists:
                    self.apexists.append(str(node1))
                if str(node2) not in self.apexists:
                    self.apexists.append(str(node2))
                conn = str(node2)
                node1.connections[conn] = node2
                conn = str(node1)
                node2.connections[conn] = node1
                        
            elif node1.type == 'accessPoint' and str(node1) not in self.apexists \
                or node2.type == 'accessPoint' and str(node2) not in self.apexists: 
                
                if self.firstAssociation:
                    self.configureWifiNodes()
                
                if node1.type == 'accessPoint':
                    ap = str(node1)
                    self.apexists.append(str(node1))
                else:
                    ap = str(node2)
                    self.apexists.append(str(node2))
                
            #necessary if does not exist link between sta and other device
            if node1 in self.missingStations:
                self.missingStations.remove(node1)
                node1.params['mode'] = 'g'
                node1.associate = False
            if node2 in self.missingStations:
                self.missingStations.remove(node2)
                node2.params['mode'] = 'g'
                node2.associate = False
   
        # Port is optional
        if port1 is not None:
            options.setdefault( 'port1', port1 )
        if port2 is not None:
            options.setdefault( 'port2', port2 )
        if self.intf is not None:
            options.setdefault( 'intf', self.intf )
        # Set default MAC - this should probably be in Link
        options.setdefault( 'addr1', self.randMac() )
        options.setdefault( 'addr2', self.randMac() )
        
	cls = self.link if cls is None else cls
        link = cls( node1, node2, **options )

        # Allow to add links at runtime
        # (needs attach method provided by OVSSwitch)
        if isinstance( node1, OVSSwitch ):
            node1.attach(link.intf1)
        if isinstance( node2, OVSSwitch ):
            node2.attach(link.intf2)

        self.links.append( link )
        return link

    def removeLink(self, link=None, node1=None, node2=None):
        """
        Removes a link. Can either be specified by link object,
        or the nodes the link connects.
        """
        if link is None:
            if (isinstance( node1, basestring )
                    and isinstance( node2, basestring )):
                try:
                    node1 = self.get(node1)
                except:
                    error("Host: %s not found.\n" % node1)
                try:
                    node2 = self.get(node2)
                except:
                    error("Host: %s not found.\n" % node2)
            # try to find link by nodes
            for l in self.links:
                if l.intf1.node == node1 and l.intf2.node == node2:
                    link = l
                    break
                if l.intf1.node == node2 and l.intf2.node == node1:
                    link = l
                    break
        if link is None:
            error("Couldn't find link to be removed.\n")
            return
        # tear down the link
        link.delete()
        self.links.remove(link)

    def configHosts( self ):
        "Configure a set of hosts."
        for host in self.hosts:
            info( host.name + ' ' )
            intf = host.defaultIntf()
            if intf:
                host.configDefault()
            else:
                # Don't configure nonexistent intf
                host.configDefault( ip=None, mac=None )
            # You're low priority, dude!
            # BL: do we want to do this here or not?
            # May not make sense if we have CPU lmiting...
            # quietRun( 'renice +18 -p ' + repr( host.pid ) )
            # This may not be the right place to do this, but
            # it needs to be done somewhere.
        info( '\n' )

    def buildFromTopo( self, topo=None ):
        """Build mininet from a topology object
           At the end of this function, everything should be connected
           and up."""
        association.printCon = False
        # Possibly we should clean up here and/or validate
        # the topo
        if self.cleanup:
            pass

        info( '*** Creating network\n' )

        if not self.controllers and self.controller:
            # Add a default controller
            info( '*** Adding controller\n' )
            classes = self.controller
            if not isinstance( classes, list ):
                classes = [ classes ]
            for i, cls in enumerate( classes ):
                # Allow Controller objects because nobody understands partial()
                if isinstance( cls, Controller ):
                    self.addController( cls )
                else:
                    self.addController( 'c%d' % i, cls )
                    
        info( '*** Adding hosts and stations:\n' )
        for hostName in topo.hosts():
            if 'sta' in str(hostName):
                self.addStation( hostName, **topo.nodeInfo( hostName ) )
            else:
                self.addHost( hostName, **topo.nodeInfo( hostName ) )
            info( hostName + ' ' )  
        
        info( '\n*** Adding switches and access point(s):\n' )
        for switchName in topo.switches():
            # A bit ugly: add batch parameter if appropriate
            params = topo.nodeInfo( switchName)
            cls = params.get( 'cls', self.switch )
            #if hasattr( cls, 'batchStartup' ):
            #    params.setdefault( 'batch', True )
            if 'ap' in str(switchName):
                self.addBaseStation( switchName, **params )
            else:    
                self.addSwitch( switchName, **params )
            info( switchName + ' ' )
            
        info( '\n*** Adding links and associating station(s):\n' )
        self.firstAssociation = True
        for srcName, dstName, params in topo.links(
                sort=True, withInfo=True ):
            self.addLink( **params )
            info( '(%s, %s) ' % ( srcName, dstName ) )

        info( '\n' )

        for switch in self.switches:
            if switch in self.missingWlanAP:
                cls = None
                cls = self.link if cls is None else cls
                cls( switch, 'alone' )
       
    def configureControlNetwork( self ):
        "Control net config hook: override in subclass"
        raise Exception( 'configureControlNetwork: '
                         'should be overriden in subclass', self )

    def build( self ):
        #useful if there no link between sta and any other device
        "Build mininet."
        association.isCode=True
        
        for switch in self.switches:
            if switch in self.missingWlanAP:
                cls = None
                cls = self.link if cls is None else cls               
                if 'wlan' not in switch.params:
                    cls( switch, 'alone' )
                else:
                    iface = switch.params.get('wlan')
                    options = dict(  )
                    options.setdefault( 'intfName1', iface )
                    cls( switch, 'alone', **options )                                
        
        for switch in self.missingDataPath:
            for s in self.switches:
                if str(s) == switch:
                    iface = self.missingDataPath[switch]
                    cls = None
                    options = dict(  )
                    options.setdefault( 'intfName1', iface )
                    cls = self.link if cls is None else cls
                    cls( s, 'alone', **options )                
        #import pdb; pdb.set_trace()
        if self.ifaceConfigured == True:
            for sta in self.stations:
                for wlan in range(0, sta.nWlans):
                    iface = str(sta)+'-wlan%s' % wlan
                    wifiParameters.getWiFiParameters(sta, wlan, iface)
                    if sta.params['position'] != (0,0,0) and sta.func[wlan] == 'adhoc':
                        channelParameters(sta, None, wlan, 0, self.stations, 0 )
		    elif sta.params['position'] != (0,0,0) and sta.func[wlan] == 'mesh':
			channelParameters(sta, None, wlan, 0, self.wifiNodes, 0)
                    else:
                        if sta.params['position'] != (0,0,0) and sta.associatedAp[wlan] != 'NoAssociated':
                            dist = channelParameters.getDistance(sta, sta.associatedAp[wlan])
                            channelParameters(sta, sta.associatedAp[wlan], wlan, dist, self.stations, 0 )
            
            for node in self.missingStations:
                for wlan in range(0, node.nWlans):
                    cls = None
                    options = dict(  )
                    iface = str(node)+'-wlan%s' % wlan
                    wifiParameters.getWiFiParameters(node, wlan, iface)                    
                    # Set default MAC - this should probably be in Link
                    options.setdefault( 'use_tbf', True )
                    options.setdefault( 'addr1', self.randMac() )
                    cls = self.link if cls is None else cls
                    cls( node, 'alone', **options )
                    if sta.params['position'] != (0,0,0) and sta.associatedAp[wlan] != 'NoAssociated':   
                        mobility.nodeParameter(node, wlan)
        
        if self.topo:
            self.buildFromTopo( self.topo )
        if self.firstAssociation:
            self.configureWifiNodes()
        if self.inNamespace:
            self.configureControlNetwork()
            info( '*** Configuring hosts\n' )       
        self.configHosts()
        if self.xterms:
            self.startTerms()
        if self.autoStaticArp:
            self.staticArp()
        self.built = True

    def startTerms( self ):
        "Start a terminal for each node."
        if 'DISPLAY' not in os.environ:
            error( "Error starting terms: Cannot connect to display\n" )
            return
        info( "*** Running terms on %s\n" % os.environ[ 'DISPLAY' ] )
        cleanUpScreens()
        self.terms += makeTerms( self.controllers, 'controller' )
        self.terms += makeTerms( self.switches, 'switch' )
        self.terms += makeTerms( self.hosts, 'host' )

    def stopXterms( self ):
        "Kill each xterm."
        for term in self.terms:
            os.kill( term.pid, signal.SIGKILL )
        cleanUpScreens()

    def staticArp( self ):
        "Add all-pairs ARP entries to remove the need to handle broadcast."
        for src in self.hosts:
            for dst in self.hosts:
                if src != dst:
                    src.setARP( ip=dst.IP(), mac=dst.MAC() )

    def start( self ):
        association.isCode = False
        "Start controller and switches."
        if not self.built:
            self.build()
        info( '*** Starting controller(s)\n' )
        for controller in self.controllers:
            info( controller.name + ' ')
            controller.start()
        info( '\n' )
        
        info( '*** Starting switches and access points\n' )
        for switch in self.switches:
            info( switch.name + ' ')
            switch.start( self.controllers )
            if switch.type == 'accessPoint':
                os.system('ovs-vsctl add-br %s' % switch.name)
          
        started = {}
        for swclass, switches in groupby(
                sorted( self.switches, key=type ), type ):
            switches = tuple( switches )
            if hasattr( swclass, 'batchStartup' ):
                success = swclass.batchStartup( switches )
                started.update( { s: s for s in success } )
                
        #It is necessary to create a bridge between ap and wlan interface
        for switch in self.switches:
            if switch.type == 'accessPoint':  
                for iface in range(0, switch.nWlans):
                    accessPoint.apBridge(switch, iface)
        
        info( '\n' )
        if self.waitConn:
            self.waitConnected()

    def seed( self, seed ):
        "Seed"
        self.set_seed = seed
        
    def roads( self, nroads ):
        "Seed"
        self.nroads = nroads

    def stop( self ):
        "Stop the controller(s), switches and hosts"
        info( '*** Stopping %i controllers\n' % len( self.controllers ) )
        for controller in self.controllers:
            info( controller.name + ' ' )
            controller.stop()
        info( '\n' )
        if self.terms:
            info( '*** Stopping %i terms\n' % len( self.terms ) )
            self.stopXterms()
        info( '*** Stopping %i links\n' % len( self.links ) )
        for link in self.links:
            info( '.' )
            link.stop()
        info( '\n' )
        info( '*** Stopping switches and access points\n' )
        stopped = {}
        for swclass, switches in groupby(
                sorted( self.switches, key=type ), type ):
            switches = tuple( switches )
            if hasattr( swclass, 'batchShutdown' ):
                success = swclass.batchShutdown( switches )
                stopped.update( { s: s for s in success } )
        for switch in self.switches:
            info( switch.name + ' ' )
            if switch not in stopped:
                switch.stop()
            switch.terminate()
        info( '\n' )
        info( '*** Stopping hosts and stations\n' )
        for host in self.hosts:
            info( host.name + ' ' )
            host.terminate()
        info( '\n' )
        if(self.isWiFi):
            "Stop plotting"
            mobility.DRAW = False
            mobility.continue_ = False
            try:
                plot.closePlot()
                sleep( 2 )
            except:
                pass        
            module.stop() #Stopping WiFi Module        
        info( '\n*** Done\n' )

    def run( self, test, *args, **kwargs ):
        "Perform a complete start/test/stop cycle."
        self.start()
        info( '*** Running test\n' )
        result = test( *args, **kwargs )
        self.stop()
        return result

    def monitor( self, hosts=None, timeoutms=-1 ):
        """Monitor a set of hosts (or all hosts by default),
           and return their output, a line at a time.
           hosts: (optional) set of hosts to monitor
           timeoutms: (optional) timeout value in ms
           returns: iterator which returns host, line"""
        if hosts is None:
            hosts = self.hosts
        poller = select.poll()
        h1 = hosts[ 0 ]  # so we can call class method fdToNode
        for host in hosts:
            poller.register( host.stdout )
        while True:
            ready = poller.poll( timeoutms )
            for fd, event in ready:
                host = h1.fdToNode( fd )
                if event & select.POLLIN:
                    line = host.readline()
                    if line is not None:
                        yield host, line
            # Return if non-blocking
            if not ready and timeoutms >= 0:
                yield None, None

    # XXX These test methods should be moved out of this class.
    # Probably we should create a tests.py for them

    @staticmethod
    def _parsePing( pingOutput ):
        "Parse ping output and return packets sent, received."
        # Check for downed link
        if 'connect: Network is unreachable' in pingOutput:
            return 1, 0
        r = r'(\d+) packets transmitted, (\d+) received'
        m = re.search( r, pingOutput )
        if m is None:
            error( '*** Error: could not parse ping output: %s\n' %
                   pingOutput )
            return 1, 0
        sent, received = int( m.group( 1 ) ), int( m.group( 2 ) )
        return sent, received

    def ping( self, hosts=None, timeout=None, manualdestip=None ):
        """Ping between all specified hosts.
           hosts: list of hosts
           timeout: time to wait for a response, as string
           manualdestip: sends pings from each h in hosts to manualdestip
           returns: ploss packet loss percentage"""
        # should we check if running?
        packets = 0
        lost = 0
        ploss = None
        if not hosts:
            hosts = self.hosts
            output( '*** Ping: testing ping reachability\n' )
        for node in hosts:
            output( '%s -> ' % node.name )
            if manualdestip is not None:
                opts = ''
                if timeout:
                    opts = '-W %s' % timeout
                result = node.cmd( 'ping -c1 %s %s' %
                                   (opts, manualdestip) )
                sent, received = self._parsePing( result )
                packets += sent
                if received > sent:
                    error( '*** Error: received too many packets' )
                    error( '%s' % result )
                    node.cmdPrint( 'route' )
                    exit( 1 )
                lost += sent - received
                output( ( '%s ' % manualdestip ) if received else 'X ' )
            else:
                for dest in hosts:
                    if node != dest:
                        opts = ''
                        if timeout:
                            opts = '-W %s' % timeout
                        if dest.intfs:
                            result = node.cmd( 'ping -c1 %s %s' %
                                               (opts, dest.IP()) )
                            sent, received = self._parsePing( result )
                        else:
                            sent, received = 0, 0
                        packets += sent
                        if received > sent:
                            error( '*** Error: received too many packets' )
                            error( '%s' % result )
                            node.cmdPrint( 'route' )
                            exit( 1 )
                        lost += sent - received
                        output( ( '%s ' % dest.name ) if received else 'X ' )
            output( '\n' )
        if packets > 0:
            ploss = 100.0 * lost / packets
            received = packets - lost
            output( "*** Results: %i%% dropped (%d/%d received)\n" %
                    ( ploss, received, packets ) )
        else:
            ploss = 0
            output( "*** Warning: No packets sent\n" )
        return ploss

    @staticmethod
    def _parsePingFull( pingOutput ):
        "Parse ping output and return all data."
        errorTuple = (1, 0, 0, 0, 0, 0)
        # Check for downed link
        r = r'[uU]nreachable'
        m = re.search( r, pingOutput )
        if m is not None:
            return errorTuple
        r = r'(\d+) packets transmitted, (\d+) received'
        m = re.search( r, pingOutput )
        if m is None:
            error( '*** Error: could not parse ping output: %s\n' %
                   pingOutput )
            return errorTuple
        sent, received = int( m.group( 1 ) ), int( m.group( 2 ) )
        r = r'rtt min/avg/max/mdev = '
        r += r'(\d+\.\d+)/(\d+\.\d+)/(\d+\.\d+)/(\d+\.\d+) ms'
        m = re.search( r, pingOutput )
        if m is None:
            if received == 0:
                return errorTuple
            error( '*** Error: could not parse ping output: %s\n' %
                   pingOutput )
            return errorTuple
        rttmin = float( m.group( 1 ) )
        rttavg = float( m.group( 2 ) )
        rttmax = float( m.group( 3 ) )
        rttdev = float( m.group( 4 ) )
        return sent, received, rttmin, rttavg, rttmax, rttdev

    def pingFull( self, hosts=None, timeout=None, manualdestip=None, times=1 ):
        """Ping between all specified hosts and return all data.
           hosts: list of hosts
           timeout: time to wait for a response, as string
           returns: all ping data; see function body."""
        # should we check if running?
        # Each value is a tuple: (src, dsd, [all ping outputs])
        all_outputs = []
        if not hosts:
            hosts = self.hosts
            output( '*** Ping: testing ping reachability\n' )
        for node in hosts:
            output( '%s -> ' % node.name )
            if manualdestip is not None:
                opts = ''
                if timeout:
                    opts = '-W %s' % timeout
		if type(manualdestip) is Docker:
	                result = node.cmd( 'ping -c%d %s %s' % (times, opts, manualdestip.IP()) )
		else:
	                result = node.cmd( 'ping -c%d %s %s' % (times, opts, manualdestip) )
                outputs = self._parsePingFull( result )
                sent, received, rttmin, rttavg, rttmax, rttdev = outputs
                all_outputs.append( (node, manualdestip, outputs) )
                output( ( '%s ' % manualdestip ) if received else 'X ' )
                output( '\n' )
            else:
                for dest in hosts:
                    if node != dest:
                        opts = ''
                        if timeout:
                            opts = '-W %s' % timeout
                        result = node.cmd( 'ping -c%d %s %s' % (times, opts, dest.IP()) )
                        outputs = self._parsePingFull( result )
                        sent, received, rttmin, rttavg, rttmax, rttdev = outputs
                        all_outputs.append( (node, dest, outputs) )
                        output( ( '%s ' % dest.name ) if received else 'X ' )
                output( '\n' )
        output( "*** Results: \n" )
        for outputs in all_outputs:
            src, dest, ping_outputs = outputs
            sent, received, rttmin, rttavg, rttmax, rttdev = ping_outputs
            output( " %s->%s: %s/%s, " % (src, dest, sent, received ) )
            output( "rtt min/avg/max/mdev %0.3f/%0.3f/%0.3f/%0.3f ms\n" %
                    (rttmin, rttavg, rttmax, rttdev) )
        return all_outputs

    def pingAll( self, timeout=None ):
        """Ping between all hosts.
           returns: ploss packet loss percentage"""
        return self.ping( timeout=timeout )

    def pingPair( self ):
        """Ping between first two hosts, useful for testing.
           returns: ploss packet loss percentage"""
        hosts = [ self.hosts[ 0 ], self.hosts[ 1 ] ]
        return self.ping( hosts=hosts )

    def pingAllFull( self ):
        """Ping between all hosts.
           returns: ploss packet loss percentage"""
        return self.pingFull()

    def pingPairFull( self ):
        """Ping between first two hosts, useful for testing.
           returns: ploss packet loss percentage"""
        hosts = [ self.hosts[ 0 ], self.hosts[ 1 ] ]
        return self.pingFull( hosts=hosts )

    @staticmethod
    def _parseIperf( iperfOutput ):
        """Parse iperf output and return bandwidth.
           iperfOutput: string
           returns: result string"""
        r = r'([\d\.]+ \w+/sec)'
        m = re.findall( r, iperfOutput )
        if m:
            return m[-1]
        else:
            # was: raise Exception(...)
            error( 'could not parse iperf output: ' + iperfOutput )
            return ''

    # XXX This should be cleaned up

    def iperf( self, hosts=None, l4Type='TCP', udpBw='10M', fmt=None,
               seconds=5, port=5001):
        """Run iperf between two hosts.
           hosts: list of hosts; if None, uses first and last hosts
           l4Type: string, one of [ TCP, UDP ]
           udpBw: bandwidth target for UDP test
           fmt: iperf format argument if any
           seconds: iperf time to transmit
           port: iperf port
           returns: two-element array of [ server, client ] speeds
           note: send() is buffered, so client rate can be much higher than
           the actual transmission rate; on an unloaded system, server
           rate should be much closer to the actual receive rate"""
        hosts = hosts or [ self.hosts[ 0 ], self.hosts[ -1 ] ]
        assert len( hosts ) == 2
        client, server = hosts
        output( '*** Iperf: testing', l4Type, 'bandwidth between',
                client, 'and', server, '\n' )
        server.cmd( 'killall -9 iperf' )
        iperfArgs = 'iperf -p %d ' % port
        bwArgs = ''
        if l4Type == 'UDP':
            iperfArgs += '-u '
            bwArgs = '-b ' + udpBw + ' '
        elif l4Type != 'TCP':
            raise Exception( 'Unexpected l4 type: %s' % l4Type )
        if fmt:
            iperfArgs += '-f %s ' % fmt
        server.sendCmd( iperfArgs + '-s' )
        if l4Type == 'TCP':
            if not waitListening( client, server.IP(), port ):
                raise Exception( 'Could not connect to iperf on port %d'
                                 % port )
        cliout = client.cmd( iperfArgs + '-t %d -c ' % seconds +
                             server.IP() + ' ' + bwArgs )
        debug( 'Client output: %s\n' % cliout )
        servout = ''
        # We want the last *b/sec from the iperf server output
        # for TCP, there are two fo them because of waitListening
        count = 2 if l4Type == 'TCP' else 1
        while len( re.findall( '/sec', servout ) ) < count:
            servout += server.monitor( timeoutms=5000 )
        server.sendInt()
        servout += server.waitOutput()
        debug( 'Server output: %s\n' % servout )
        result = [ self._parseIperf( servout ), self._parseIperf( cliout ) ]
        if l4Type == 'UDP':
            result.insert( 0, udpBw )
        output( '*** Results: %s\n' % result )
        return result

    def runCpuLimitTest( self, cpu, duration=5 ):
        """run CPU limit test with 'while true' processes.
        cpu: desired CPU fraction of each host
        duration: test duration in seconds (integer)
        returns a single list of measured CPU fractions as floats.
        """
        cores = int( quietRun( 'nproc' ) )
        pct = cpu * 100
        info( '*** Testing CPU %.0f%% bandwidth limit\n' % pct )
        hosts = self.hosts
        cores = int( quietRun( 'nproc' ) )
        # number of processes to run a while loop on per host
        num_procs = int( ceil( cores * cpu ) )
        pids = {}
        for h in hosts:
            pids[ h ] = []
            for _core in range( num_procs ):
                h.cmd( 'while true; do a=1; done &' )
                pids[ h ].append( h.cmd( 'echo $!' ).strip() )
        outputs = {}
        time = {}
        # get the initial cpu time for each host
        for host in hosts:
            outputs[ host ] = []
            with open( '/sys/fs/cgroup/cpuacct/%s/cpuacct.usage' %
                       host, 'r' ) as f:
                time[ host ] = float( f.read() )
        for _ in range( duration ):
            sleep( 1 )
            for host in hosts:
                with open( '/sys/fs/cgroup/cpuacct/%s/cpuacct.usage' %
                           host, 'r' ) as f:
                    readTime = float( f.read() )
                outputs[ host ].append( ( ( readTime - time[ host ] )
                                        / 1000000000 ) / cores * 100 )
                time[ host ] = readTime
        for h, pids in pids.items():
            for pid in pids:
                h.cmd( 'kill -9 %s' % pid )
        cpu_fractions = []
        for _host, outputs in outputs.items():
            for pct in outputs:
                cpu_fractions.append( pct )
        output( '*** Results: %s\n' % cpu_fractions )
        return cpu_fractions
         
    def mobility(self, *args, **kwargs):
        """ Mobility Parameters """
        self.node = args[0]
        self.stage = args[1]

        for n in self.stations:
            if self.node == str(n):
                sta = n            
       
        if 'position' in kwargs:
            if(self.stage == 'stop'):
                finalPosition = kwargs['position']
                self.finalPosition[sta] = finalPosition.split(',')
            if(self.stage == 'start'):
                initialPosition = kwargs['position']
                self.initialPosition[sta] = initialPosition.split(',')
                self.staMov.append(sta)
        
        if 'time' in kwargs:
            self.time = kwargs['time']
                    
        if(self.stage == 'start'):
            sta.startTime = self.time        
        elif(self.stage == 'stop'):
            sta.endTime = self.time 
            diffTime = sta.endTime - sta.startTime
            mobility.moveFactor(sta, diffTime, self.initialPosition[sta], self.finalPosition[sta])
        
    def startMobility(self, **kwargs):
        """ Starting Mobility """
        self.mobilityModel = ''
        mobilityparam = dict() 
        if 'model' in kwargs:
            mobilityparam.setdefault( 'model', kwargs['model'] )
            self.mobilityModel = kwargs['model']
            
        if self.mobilityModel != '' or self.isVanet:      
            if 'max_x' in kwargs:
                mobilityparam.setdefault( 'max_x', kwargs['max_x'] )
            if 'max_y' in kwargs:
                mobilityparam.setdefault( 'max_y', kwargs['max_y'] )
            if 'min_v' in kwargs:
                mobilityparam.setdefault( 'min_v', kwargs['min_v'] )
            if 'max_v' in kwargs:
                mobilityparam.setdefault( 'max_v', kwargs['max_v'] )
            if 'startTime' in kwargs:
                self.start_time = kwargs['startTime']
           
            mobilityparam.setdefault( 'seed', self.set_seed )
            mobilityparam.setdefault( 'nodes', self.wifiNodes )
        
            for sta in self.stations:
                if sta not in self.fixedPosition:
                    self.staMov.append(sta)  
            mobilityparam.setdefault( 'staMov', self.staMov )
            
            if self.isVanet == False:
                self.thread = threading.Thread(name='mobilityModel', target=mobility.models, kwargs=dict(mobilityparam,))
                self.thread.daemon = True
                self.thread.start()
            else:
                self.thread = threading.Thread(name='vanet', target=vanet, args=(self.stations, self.accessPoints, self.nroads, mobility.MAX_X, mobility.MAX_Y))
                self.thread.daemon = True
                self.thread.start()
            self.setWifiParameters()            
        print "Mobility started at %s second(s)" % kwargs['startTime']
        
    def stopMobility(self, **kwargs):
        """ Stop Mobility """
        if 'stopTime' in kwargs:
            stop_time = kwargs['stopTime']
        
        for node in self.wifiNodes:
            for wlan in range(0, node.nWlans):
                iface = str(node)+'-wlan%s' % wlan
                wifiParameters.getWiFiParameters(node, wlan, iface)
        
        debug( 'Starting mobility thread...\n' )
        self.thread = threading.Thread(name='mobility', target=mobility.mobilityPositionDefined, args=(self.start_time, stop_time, self.staMov))
        self.thread.daemon = True
        self.thread.start()
        
    def setWifiParameters(self):
        self.thread = threading.Thread(name='wifiParameters', target=mobility.parameters)
        #self.thread.daemon = True
        self.thread.start()
        
    def useExternalProgram(self, program, **params):
        config_file = ("%s" % params.pop('config_file', {}))
        if program == 'sumo' or program == 'sumo-gui':
            self.thread = threading.Thread(name='vanet', target=sumo, args=(self.stations,program, config_file))
            self.thread.daemon = True
            self.thread.start()
            self.setWifiParameters()
            
    def meshRouting(self, routing):
        if routing != '':
            meshRouting.routing = routing
                   
    def printDistance(self, src, dst):
        """ Print the distance between two points """
        dist = channelParameters.getDistance(src, dst)
        print ("The distance between %s and %s is %.2f meters\n" % (src, dst, float(dist)))
        
    def report_(self, node, d ):
        for host in self.wifiNodes:
            if node == str(host):
                report(host, d)
                   
    def plotGraph(self, **kwargs):
        """ Plot Graph """
        if 'max_x' in kwargs:
            mobility.MAX_X = kwargs['max_x']
        if 'max_y' in kwargs:
            mobility.MAX_Y = kwargs['max_y']
        mobility.DRAW = True
        #if self.isVanet == False:
        #if self.ifaceConfigured == False:
        for node in self.wifiNodes:
            plot.instantiateGraph(mobility.MAX_X, mobility.MAX_Y)
            plot.instantiateNode(node, mobility.MAX_X, mobility.MAX_Y)
            plot.instantiateAnnotate(node)
            plot.instantiateCircle(node)
            plot.graphUpdate(node)                
        
    def getCurrentPosition(self, node):
        """ Get Current Position """ 
        try:
            for host in self.wifiNodes:
                if node == str(host):
                    self.printPosition(host)
        except:
            print ("Position was not defined")            
            
    def printPosition(self, node):
        """ Print position of STAs and APs """
	#import pdb; pdb.set_trace()
        self.pos_x = node.params['position'][0]
        self.pos_y = node.params['position'][1]
        self.pos_z = node.params['position'][2]   
        print "----------------\nPosition of %s\n---------------- \
        \nPosition X: %.2f \
        \nPosition Y: %.2f \
        \nPosition Z: %.2f\n" % (str(node), float(self.pos_x), float(self.pos_y), float(self.pos_z))
                        
    def propagationModel(self, model, exp=2, sl=1):
        propagationModel_.model = model
        propagationModel_.exp = exp
        propagationModel_.sl = sl
        
    def associationControl(self, ac):
        mobility.associationControlMethod = ac        
    
    def deviceInfo(self, device):
        """ Devices Info """         
        try:
            for sta in self.stations:
                if device == str(sta):
                    device = sta      
            for ap in self.accessPoints:
                if device == str(ap):
                    device = ap  
            if device.type == 'station':
                for wlan in range(device.nWlans):
                    print "--------------------------------"                
                    print "Interface: %s-wlan%s" % (device, wlan)
                    try: # it is important when not infra
                        if 'ap' in str(device.associatedAp[wlan]):
                            print "Associated To: %s" % device.associatedAp[wlan]
                        else:
                            print "Associated To: %s" % None
                    except:
                        print "Associated To: %s" % None
                    print "Frequency: %s GHz" % device.params['frequency'][wlan]
                    if device.params['rssi'][wlan] != 0:
                        print "Signal level: %.2f dbm" % device.params['rssi'][wlan]
                    else:
                        print "Signal level: No Signal"
                    print "Tx-Power: %s dBm" % device.params['txpower'][wlan]
            else:
                print "Tx-Power: %s dBm" % device.params['txpower'][0]
                print "SSID: %s" % device.params['rssi'][0]
                print "Number of Associated Stations: %s" % device.nAssociatedStations
        except:
            pass
                               
    def getCurrentDistance(self, src, dst):
        """ Get current Distance """ 
        try:
            for host1 in self.wifiNodes:
                if src == str(host1):
                    src = host1
                    for host2 in self.wifiNodes:
                        if dst == str(host2):
                            dst = host2
                            self.printDistance(src, dst)
        except:
            print ("node %s or/and node %s does not exist or there is no position defined" % (dst, src))        
        
    # BL: I think this can be rewritten now that we have
    # a real link class.
    def configLinkStatus( self, src, dst, status ):
        """Change status of src <-> dst links.
           src: node name
           dst: node name
           status: string {up, down}"""
        if src not in self.nameToNode:
            error( 'src not in network: %s\n' % src )
        elif dst not in self.nameToNode:
            error( 'dst not in network: %s\n' % dst )
        else:
            if isinstance( src, basestring ):
                src = self.nameToNode[ src ]
            if isinstance( dst, basestring ):
                dst = self.nameToNode[ dst ]
            connections = src.connectionsTo( dst )
            if len( connections ) == 0:
                error( 'src and dst not connected: %s %s\n' % ( src, dst) )
            for srcIntf, dstIntf in connections:
                result = srcIntf.ifconfig( status )
                if result:
                    error( 'link src status change failed: %s\n' % result )
                result = dstIntf.ifconfig( status )
                if result:
                    error( 'link dst status change failed: %s\n' % result )

    def interact( self ):
        "Start network and run our simple CLI."
        self.start()
        result = CLI( self )
        self.stop()
        return result

    inited = False

    @classmethod
    def init( cls ):
        "Initialize Mininet"
        if cls.inited:
            return
        ensureRoot()
        fixLimits()
        cls.inited = True


class Containernet( Mininet ):
    """
    A Mininet with Docker related methods.
    Inherits Mininet.
    This class is not more than API beautification.
    """

    def __init__(self, **params):
        # call original Mininet.__init__
        Mininet.__init__(self, **params)

    def addDocker( self, name, cls=Docker, **params ):
        """
        Wrapper for addStation method that adds a
        Docker container as a host.
        """
        return self.addStation( name, cls=cls, **params)

    def addDockerBS( self, name, cls=Docker, **params ):
	"""
	Wrapper for addBaseStation method that
	adds a Docker container as a BaseStation
	"""
	return self.addBaseStation( name, cls=cls, **params)

    def removeDocker( self, name, **params):
        """
        Wrapper for removeHost. Just to be complete.
        """
        return self.removeHost(name, **params)


class MininetWithControlNet( Mininet ):

    """Control network support:

       Create an explicit control network. Currently this is only
       used/usable with the user datapath.

       Notes:

       1. If the controller and switches are in the same (e.g. root)
          namespace, they can just use the loopback connection.

       2. If we can get unix domain sockets to work, we can use them
          instead of an explicit control network.

       3. Instead of routing, we could bridge or use 'in-band' control.

       4. Even if we dispense with this in general, it could still be
          useful for people who wish to simulate a separate control
          network (since real networks may need one!)

       5. Basically nobody ever used this code, so it has been moved
          into its own class.

       6. Ultimately we may wish to extend this to allow us to create a
          control network which every node's control interface is
          attached to."""

    def configureControlNetwork( self ):
        "Configure control network."
        self.configureRoutedControlNetwork()

    # We still need to figure out the right way to pass
    # in the control network location.

    def configureRoutedControlNetwork( self, ip='192.168.123.1',
                                       prefixLen=16 ):
        """Configure a routed control network on controller and switches.
           For use with the user datapath only right now."""
        controller = self.controllers[ 0 ]
        info( controller.name + ' <->' )
        cip = ip
        snum = ipParse( ip )
        for switch in self.switches:
            info( ' ' + switch.name )
            link = self.link( switch, controller, port1=0 )
            sintf, cintf = link.intf1, link.intf2
            switch.controlIntf = sintf
            snum += 1
            while snum & 0xff in [ 0, 255 ]:
                snum += 1
            sip = ipStr( snum )
            cintf.setIP( cip, prefixLen )
            sintf.setIP( sip, prefixLen )
            controller.setHostRoute( sip, cintf )
            switch.setHostRoute( cip, sintf )
        info( '\n' )
        info( '*** Testing control network\n' )
        while not cintf.isUp():
            info( '*** Waiting for', cintf, 'to come up\n' )
            sleep( 1 )
        for switch in self.switches:
            while not sintf.isUp():
                info( '*** Waiting for', sintf, 'to come up\n' )
                sleep( 1 )
            if self.ping( hosts=[ switch, controller ] ) != 0:
                error( '*** Error: control network test failed\n' )
                exit( 1 )
        info( '\n' )

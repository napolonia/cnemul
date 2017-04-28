#!/usr/bin/python

"""
This example shows how to create a simple network and
how to create docker containers (based on existing images)
to it.
"""

from mininet.net import Containernet
from mininet.node import Controller, Docker, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink, Link
from mininet.wifiMeshRouting import meshRouting

import pdb
import sys
import time
from random import randint

num_hosts=30
max_x=10
max_y=10
max_z=50
max_r=100

def positions(N=30):
	## This will create a list of positions
	# max_positions * number_of_nodes = square_of_placement
	list=[]
	i=0

	while i <= N:
		t = ""
		while not t:
			b = [randint(0, max_x * N), randint(0, max_y * N), randint(0, max_z), randint(max_r*N / 2, max_r*N)]
			t = addList(list, b)
		i+=1
	return list

def prepareGraph(num=30):
	## This will generate a random geograph
	## New method instead of old one
	from graph_tool.generation import geometric_graph as geograph

	list= (randint(0, max_x*num) * 2, randint(0, max_z)) * num
	rlist= (randint(max_r / 2, max_r) * 2) * num
	g , pos = geograph(list, max_r, rlist)
	
	gt.graph_draw(g, pos=pos, output_size=(max_x, max_y))

## Add to the list a element	
def addList(list, b):
	if b in list:
		return ""
	else:
		list.append(b)
		return list	

## Get element from list and removes it
def getPosition(list):
	if not list:
		return None
	return list.pop()

## Get information of services SERF+Monitor related
def see_pub(list, out=None):
	for i in list:
		info=i.cmd("/bin/bash /home/config-serf.sh getinfo")
		memb=i.cmd("/bin/bash /home/config-serf.sh getmembers")
		if out is None:
			print("**********************")		
			print("** Node %s: %s" % (str(i), info))
			print("**** %s " % (memb))
			print("**********************")
		else:
			out.write("*** NODE " + str(i) + "|\n")
			out.write(info + "\n")
			out.write("\n***\n")
			out.write(memb + "\n")
			out.write("\n***\n")
			out.write("\n***\n")
			out.flush()

## Shows the topology and related information
def printTopo(cli, out=None, num=10):
	if out is None:
		print("********** Reachability ************")
		cli.pingAllFull()
		print("**********************")
		print("********** WireLessConf ************")
		for i in cli.hosts:
			cli.deviceInfo(i)
		print("**********************")
		print("**********   Topology    ************")
		cli.plotGraph(max_x=max_x*num, max_y=max_y*num)
		for i in cli.wifiNodes:
			cli.printPosition(i)
		print("**********************")
	########## Logging to file needs to be through logging class
	#else:
	#	out.write("********** Reachability ************")
	#	cli.pingAllFull()
	#	out.write("**********************")
	#	out.write("********** WireLessConf ************")
	#	for i in cli.hosts:
	#		cli.deviceInfo(i)
	#	out.write("**********************")
	#	out.write("**********   Topology    ************")
	#	cli.plotGraph(max_x=100*num, max_y=100*num)
	#	for i in cli.wifiNodes:
	#		cli.printPosition(i)
	#	out.write("**********************")

## Starts the network and hosts
def topology(num=100):
    info("Creating a network with docker containers acting as hosts and wireless mesh network environment.\n")

    net = Containernet(controller=Controller)

    info('*** Adding docker containers\n')
    ## In automated way will create Hosts
    dh = []
    
    listPos = positions(num)
    prepareGraph(num)
    sys.exit()
    print("** Creating %d Station(s) " % (num))

    for x in range(0, num):
	ip = (254 - x)
	posx,posy,posz,r = getPosition(listPos)
	## This will create the hosts with image ubuntu:trusty, position and range of the device
	## other information can be added later
	dh.append(net.addDocker('d' + str(x), cls=Docker, ip='10.0.0.' + str(ip), dimage="ubuntu:trusty", position=str(posx) + ',' + str(posy) + ',' + str(posz), range=r))
	d = dh[x]
	sys.stdout.write(str(d) + " ")
	sys.stdout.flush()


    info("\n** Adding nodes to Mesh\n")
    for x in dh:
	net.addMesh(x, ssid='meshNet')
    #pdb.set_trace()
    meshr=net.meshRouting("mesh")
    info("** Routing nodes through mesh\n")
    for x in dh:
    	meshRouting.customMeshRouting(x, 0, net.wifiNodes)
	sys.stdout.write(str(x) + " ")
	sys.stdout.flush()

    info('\n*** Starting network\n')
    net.build() ## Build should do the same as start but it will interconnect hosts
    #net.start()

    seed_node = "10.0.0.254:5001" ## seed will be always the first container!
    info("** Configuring node(s)\n")
    for d in dh:
	sys.stdout.write(str(d) + " - ")
	sys.stdout.flush()
	port = 5001
	dev=str(d) + "-mp0"
	## Calling inside script to configure each container
	nn=d.cmd("/bin/bash /home/config-serf.sh config rpc=127.0.0.1:7373 port=" + str(port) + " dev=" + str(dev) + " seed=" + str(seed_node))
	if nn:
		print("Configured for 10.0.0.%s:%d in device %s " % (str(ip),port, dev))
		print("> %s " % (nn))
	else:
		print("Error in configuring %s " % (str(d)) )

    info('*** Starting our simulation\n')

    slpv=10 * num / 4 ### SLEEP VARIABLE!!!!
    #This will start our simulation of SERF+monitor
    #Calling our inside script to start the processes
    st=time.time()
    with open('/home/simul.' + str(num) + '-' + str(int(time.time())) + '.txt', "a+") as myfile:
    	for d in range(0, num):
		dh[d].sendCmd("/bin/bash /home/config-serf.sh test " + str(slpv) + " 2>&1 /dev/null &")
		see_pub(dh, out=myfile)
		#dh[d+1].cmd("/bin/bash /home/config-serf.sh test 50")
		time.sleep( 1 ) ## So that each will start after each other

    	info("** All nodes have published services.\n")
    	info("** waiting for them to end.")
    	et=0
	while ((st + slpv) - et ) >= 0: ## while within the time frame
    	#for i in range(0,slpv):
		sys.stdout.write(".")
		sys.stdout.flush()
		see_pub(dh, out=myfile)
		#time.sleep(1)
	    	et=time.time()
	sys.stdout.flush()
	myfile.flush()
    	print("\n")
	
    printTopo(net,num=num)
    info("*** Simulation has ended (?)\n")

    info('*** Running CLI\n')
    CLI(net)

    info('*** Stopping network')
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    ## Starting with num of hosts
    topology(num=50)

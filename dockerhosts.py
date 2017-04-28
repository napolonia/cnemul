#!/usr/bin/python

"""
This example shows how to create a simple network and
how to create docker containers (based on existing images)
to it.
"""
#import matplotlib
#matplotlib.use('GTK')

from mininet.net import Containernet
from mininet.node import Controller, Docker, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink, Link
from mininet.wifiMeshRouting import meshRouting
from mininet.clean import Cleanup

import pdb
import sys, getopt, os
import time
from random import randint
import numpy
""" 
### CONFIGURATION:
 num_hosts = number of hosts
 max_x = maximum on x axis
 max_y = maximum on y axis
 max_z = maximum on z axis
 max_r = maximum of range of the host
 mode_ap = mode of the device one of "abgn"
"""
num_hosts=20
max_x=10
max_y=10
max_z=10
### Using mode n == max_r = 70 
### mode g == max_r = 33
max_r=100
emodel="DI524" ## device model
mode_ap="n"
experiment=None
plot_graph=False
pingO=False
serf_conf=False
sleep_test=-1
new_met=False
save_to="/home/simul/"
docker_image="ubuntu:trusty"
save_topo=False
save_topo_file=save_to + 'topology.tdh'
load_topo=None
constraint=True


class LNode:
	''' Node loaded and saved from to file '''
	node_num=None
	position=None
	docker_image="ubuntu:trusty"
	equip_model="DI524"
	range=100
	mode="n"
	ip=None
	
	def __init__(self):
		self.node_num=-1

	def get_node_num(self):
		return int(self.node_num)
	def set_node_num(self, num):
		self.node_num=num

	def get_position(self):
		return self.position
	def get_position2(self):
		x,y,z = self.position
		return str(x) + "," + str(y) + "," + str(z)
	def set_position(self, x, y='', z=''):
		if y:
			self.position=(x,y,z)
		else:
			self.position=x

	def get_docker_image(self):
		return str(self.docker_image)
	def set_docker_image(self, image):
		self.docker_image=image

	def get_equip_model(self):
		return str(self.equip_model)
	def set_equip_model(self, em):
		self.equip_model=em
	
	def get_rangei(self):
		return int(self.range)
	def get_ranges(self):
		return str(self.range)
	def get_range(self):
		return self.get_ranges()
	def set_range(self, r):
		self.range=int(r)


	def get_mode(self):
		return str(self.mode)
	def set_mode(self, mode):
		self.mode=mode

	def get_ip(self):
		return str(self.ip)
	def set_ip(self, ip):
		self.ip=ip

	def set(self, vv):
		var=vv.split("=")[0]
		value=vv.split("=")[1]
		if var == 'node_num':
			self.set_node_num(int(value))
		elif var == 'position':
			self.set_position(eval(value))
		elif var == 'docker_image':
			self.set_docker_image(str(value))
		elif var == 'equip_model':
			self.set_equip_model(str(value))
		elif var == 'range':
			self.set_range(int(value))
		elif var == 'mode':
			self.set_mode(str(value))
		elif var == 'ip':
			self.set_ip(str(value))

## Old way to get random positions
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

def SmallWorldGraph(num=30, max_r=100):
	##This will generate a SmallWorld geograph
	# with preferential attachment model
	import random
	import numpy as np
	import matplotlib.pyplot as plt
	import networkx as nx

	def create_rand(x0,y0,dist):
		r = dist/111300
		u=np.random.uniform(1,max_r/2)
		v=np.random.uniform(1,max_r/2)
		w = r * np.sqrt(u)
		t = 2 * np.pi * v
		x = w * np.cos(t)
		x1 = x / np.cos(y0)
		y = w * np.sin(t)
		return (x0+x1, y0+y)

	#fig = plt.figure()
	plt.ion()
	plt.figure()
	G=nx.Graph()
	G.add_nodes_from(range(num))
	
	for i in range(0, num):
		x0 = randint(0,max_r)
		y0 = randint(0,max_r)
		x,y = create_rand(x0,y0, max_r)
		plt.plot(x,y)
		G.node[i]['pos']=[x,y]
		#print("%d %d" % (x,y))
	#sys.exit(0)
	nodes = G.nodes(data=True)
	while nodes:
		u,du = nodes.pop()
		pu = du['pos']
		for v,dv in nodes:
			pv = dv['pos']
			d = sum(((int(a)-int(b))**2 for a,b in zip(pu,pv)))**(0.5)
			if int(d) <= int(max_r/2): ## so that they will not be at the same position
				G.add_edge(u,v)
	nx.draw(G, pos=nx.get_node_attributes(G,'pos'))
	plt.show(block=False)

	return G

## New way to get random graph positions
def prepareGraph(num=30, max_r=100):
	## This will generate a random geograph
	from graph_tool.generation import geometric_graph
	from graph_tool.draw import graph_draw
	import networkx as nx
	list1 = []

	G=nx.Graph()
	G.add_nodes_from(range(num))
	for n in G:
		G.node[n]['pos']=[randint(0, max_x*max_r) for i in range(0,2)]
		#print G.node[n]['pos']
	nodes = G.nodes(data=True)
	while nodes:
		u,du = nodes.pop()
		pu = du['pos']
		for v,dv in nodes:
			pv = dv['pos']
			d = sum(((int(a)-int(b))**2 for a,b in zip(pu,pv)))**(0.5)
			if int(d) <= int(max_r) and int(d) > 5: ## so that they will not be at the same position
				G.add_edge(u,v)
	G=processGraph(G, nx, num, max_r)
	## Try again to make sure it is correct
	

	## Check all nodes again to make sure groups are connected
	nodes = G.nodes(data=True)
	total = 0
	#G=nx.random_geometric_graph(num,max_r,dim=2)
	pos=nx.get_node_attributes(G,'pos')

	for t in pos:
		x,y=pos[t]
		list1.append([int(x),int(y)])
		#print("[%d %d]" % (x,y))
	rlist = [(max_r/2,max_r),(max_r/2,max_r)]
	return list1, G


## Making sure each node is connected!
def processGraph(G, nx, num, max_r):
	nnei=[]
	nei=[]
	for i in nx.non_neighbors(G, 0):
		nnei.append(i)

	tobrk = False
	while nnei:
		for l in range(0,num):
			if tobrk: tobrk=False; break
			nodes=G.nodes(data=True)
			for i in nx.all_neighbors(G, l):
				nei.append(i) #neighbors of l
			for i in nx.non_neighbors(G, l):
				nnei.append(i) # non-neighbors of l

			for t in nei:
				for i in nx.all_neighbors(G,t):
					nei.append(i)
					nei=list(set(nei))
			nnei=list(set(nnei)-set(nei)) ## these are unconnected
		##Generate random positions and calculate them again
			for i in nnei:
				for e in G.edges():
					if i in e:
						G.remove_edge(*e)
				G.add_node(i, {'pos':[randint(0, max_x*max_r) for l in range(0,2)]})
				nodes=G.nodes(data=True)
				u, du = nodes[i]
				pu = du['pos']
				for v,dv in nodes:
					pv = dv['pos']
					d = sum(((int(a)-int(b))**2 for a,b in zip(pu,pv)))**(0.5)
					if int(d) <= int(max_r) and int(d) > 5: ## to not be on the same position
						G.add_edge(u,v)
			tobrk=True
			##should break to the while so it will revise the network	
	return G

## Euclidean Distance
def distance(v1,v2): 
    return sum([(x-y)**2 for (x,y) in zip(v1,v2)])**(0.5)

## Add to the list an element
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
## The new method will save info on container
## and get the entire file out at the end
def see_pubnew(list, out=None, get_f=False):
	#info("** Using new Method of saving information: \n")
	import os.path
	if not get_f:
		for i in list:
			if out is None:
			##
				info("New method not done yet!")
			else:
				#info("%s " % i)
				# sendcmd will be faster but will be queued on container
				info2=i.cmd("/bin/bash /home/config-serf.sh getinfo save")
				memb=i.cmd("/bin/bash /home/config-serf.sh getmembers save")
				#i.sendCmd("sshpass -p 'mininet' scp -o 'StrictHostKeyChecking no' /home/pub_info.txt mininet@172.17.0.1:/home/simul/pub_info_%s.txt" % (i))
				#i.sendCmd("sshpass -p 'mininet' scp -o 'StrictHostKeyChecking no' /home/pub_members.txt mininet@172.17.0.1:/home/simul/pub_members_%s.txt" % (i))
	else:
		for i in list:
			sys.stdout.write("%s " % (i))
			sys.stdout.flush()
			while not os.path.exists("%spub_info_%s.txt" % (save_to, i)):
				i.cmd("sshpass -p 'mininet' scp -o 'StrictHostKeyChecking no' /home/pub_info.txt mininet@172.17.0.1:%spub_info_%s.txt" % (save_to, i))				
			#	time.sleep(1) ## making sure file is in place
				
			while not os.path.exists("/%spub_members_%s.txt" % (save_to, i)):
				i.cmd("sshpass -p 'mininet' scp -o 'StrictHostKeyChecking no' /home/pub_members.txt mininet@172.17.0.1:%spub_members_%s.txt" % (save_to, i))
			#	time.sleep(1) ## making sure file is in place
			
			with open("%spub_info_%s.txt" % (save_to, i)) as pinfo, open("%spub_members_%s.txt" % (save_to, i)) as pmemb:
				pci = pinfo.readlines()
				pcm = pmemb.readlines()
				out.write("*** NODE " + str(i) + " |\n")
				for t in pci:
					out.write(t)
				out.write("\n***\n")
				for t in pcm:
					if t != '\n': # dont write empty
						out.write(t)
				out.write("\n***\n")
				out.write("***\n")
				out.flush()
			#pdb.set_trace()
			os.remove("%spub_info_%s.txt" % (save_to, i))
			os.remove("%spub_members_%s.txt" % (save_to, i))
		info("\n")
		
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

def getMaxCoord(nodes, list="", xy=False):
	max_x = 0
	max_y = 0
#	pdb.set_trace()
	if list:
		for n in list:
#			print("MAX x %d - %d y %d - %d" % (n[0], max_x, n[1], max_y))
			if int(n[0]) > max_x:
				max_x = int(n[0]) 
			if int(n[1]) > max_y:
				max_y = int(n[1])
		if int(max_x) < int(max_y):
			max_x = int(max_y)
		return max_x

	for n in nodes:
		if int(n.params['position'][0]) > max_x:
			max_x = int(n.params['position'][0]) 
		if int(n.params['position'][1]) > max_y:
			max_y = int(n.params['position'][1])
	if not xy:
		if int(max_x) < int(max_y):
			max_x = int(max_y)

	return int(max_x), int(max_y)

def getMinCoord(nodes, list="", xy=False):
	min_x = 1000
	min_y = 1000

	if list:
		for n in list:
#			print("MIN x %d - %d y %d - %d" % (n[0], min_x, n[1], min_y))
			if int(n[0]) < min_x:
				min_x = int(n[0]) 
			if int(n[1]) < min_y:
				min_y = int(n[1])
	
		if int(min_x) > int(min_y):
			min_x = int(min_y)

		return min_x

	for n in nodes:
		if int(n.params['position'][0]) < min_x:
			min_x = int(n.params['position'][0]) 
		if int(n.params['position'][1]) < min_y:
			min_y = int(n.params['position'][1])
	if not xy:
		if int(min_x) > int(min_y):
			min_x = int(min_y)

	return int(min_x), int(min_y)

## Shows the topology and related information
def printTopo(cli, out=None, num=10, plotgrp=False, ping=False):
	timeout=None
	if out is None:
		print("**********   Topology    ************")
		pmax_x, pmax_y = getMaxCoord(cli.hosts)
		pmin_x, pmin_y = getMinCoord(cli.hosts)
		if plotgrp:
			cli.plotGraph(max_x=pmax_x + 10, max_y=pmax_x + 10, min_x=pmin_x - 10, min_y=pmin_y - 10)
		for i in cli.wifiNodes:
			cli.printPosition(i)
		print("**********************")
		print("********** WireLessConf ************")
		for i in cli.hosts:
			cli.deviceInfo(i)
		print("**********************")

		if ping:
			print("********** Reachability ************")
		## Foreach node do ping to others
		## do traceroute to others
		## Parse through the parser already made in net.py
			for n in cli.wifiNodes:
				for t in cli.wifiNodes:
					if n != t:
						info("*** For node ")
						#cli.ping(hosts=[n], manualdestip=t,times=1) ## Just to clean up a bit
						cli.pingFull(hosts=[n], manualdestip=t, times=1)
			print("**********************")
	########## TODO: Logging to file, for now just copy paste from CLI command line
	else:
		print("*** Saving to File Topology")
		## Need to flush all output from nodes.cmd
		out.write("**********   Topology    ************\n")
		for i in cli.wifiNodes:
			out.write("--- Position of %s --- \
			\nPosition X: %.2f \
			\nPosition Y: %.2f \
			\nPosition Z: %.2f \
			\nIP: %s\n" % (str(i), float(i.params['position'][0]), float(i.params['position'][1]), float(i.params['position'][2]), str(i.IP())) )
			out.flush()
		out.write("**********************\n")
		print("*** Saving to File Wireless configuration")
		out.write("********** WireLessConf  ************\n")
		for i in cli.wifiNodes:
			out.write("--- Host %s ---\n" % (str(i)))
			for wlan in range(i.nWlans):
				out.write("Interface %s-mp%s\n" % (i, wlan))
				out.write("TO BE ADDED!\n")
			out.flush()
		out.write("**********************\n")

		if ping:
			print("*** Saving to File Network stats")
			times = 3
			out.write("********** Reachability ************\n")
			for n in cli.wifiNodes:
				sys.stdout.write("%s " % (n))
				sys.stdout.flush()
				for t in cli.wifiNodes:
					if n != t:
						out.write("** For node ")
						out.write(" %s -> " % (n))
						### Ping and output to out
                                                i.cmd("/bin/bash /home/config-serf.sh ping %s %d" % (t.IP(), times))
                                                i.cmd("sshpass -p 'mininet' scp -o 'StrictHostKeyChecking no' /home/ping.txt mininet@172.17.0.1:%s" % save_to)
						while not os.path.exists("%sping.txt" % save_to):
							time.sleep(1) ## making sure file is in place
                                                with open("%sping.txt" % save_to) as f:
                                                        contents = f.readlines()
							fc = ''
							for ss in contents:
								fc += ss
                                                        ots = cli._parsePingFull(fc)
                                                        sent,received,rttmin,rttavg,rttmax,rttdev = ots
							out.write("%s - s/r %s/%s - rtt min/avg/max/mdev %0.3f/%0.3f/%0.3f/%0.3f ms\n" % (t, sent, received, rttmin, rttavg, rttmax, rttdev))
						os.remove("%sping.txt" % save_to)
					out.flush()
		out.write("**********************")
		sys.stdout.write("\n")
		print("*** Done saving")

def load_positions(net):
    info("*** Loading Nodes from file\n")
    numofhosts=0
    nodes=[]
    with open(load_topo,"r") as ln:
	## For each node found we are going to add it to the network as it was
	lines=ln.readlines()
	stnd=False
	for line in lines:
		if not line.startswith("#"):
			## maybe found other global properties
			if line.startswith("NumOfHosts"):
				numofhosts = int(line.split("=")[1].split(";")[0])
			elif line.startswith("["):
				node=LNode() ## start node empty then add properties
				stnd = True
			elif line.startswith("]"):
				## End of node
				nodes.append(node)
				node = None
				stnd = False
			elif stnd: ## inside a node
				node.set(line.split(";")[0])
				#node.append(line.split(";")[0])
    dh=[]
    for ntmp in nodes:
	#this is a node to load
	info("* Loading node %d at position %s with IP %s\n" % (ntmp.get_node_num(), ntmp.get_position(), ntmp.get_ip()))
	xn=net.addDocker('d' + str(ntmp.get_node_num()), 
		cls=Docker, ip=str(ntmp.get_ip()), dimage=ntmp.get_docker_image(), 
		position=ntmp.get_position2(), range=ntmp.get_rangei(), mode=ntmp.get_mode(), 
		equipmentModel=ntmp.get_equip_model())
	container_constraint(node=xn)

	dh.append(xn)    


	#Do mesh routing (?)
    info("\n* Adding nodes to Mesh\n")
    for xn in dh:
    	hlinks = []
	hlinks.append(net.addMesh(xn, ssid='meshNet'))
	xn.verifyingNodes(xn)

    ## Mesh routing is not doing a mesh, only 1 to nearby
    info("\n* Routing nodes through mesh\n")
    meshr=net.meshRouting("custom")
    for xn in dh:
    	meshRouting.customMeshRouting(xn, 0, net.wifiNodes)
    	sys.stdout.write(str(xn) + " ")
    	sys.stdout.flush()

    info("** %d Nodes have been loaded\n" % numofhosts)
    return net, dh, numofhosts


def load_G_from_file(file, show=False):
    nodes = []
    edges = []

    with open(file, "r") as f:
	lines = f.readlines()
	for line in lines:
		if line.startswith("nodes"):
			nodes = line.split("=")[1].strip()
		if line.startswith("edges"):
			edges = line.split("=")[1].strip()
	#print edges
	#import random
	#import numpy as np
	import matplotlib.pyplot as plt
	import networkx as nx

	G = nx.Graph()
	for n in eval(nodes): G.add_node(int(n[0]),pos=(n[1]['pos']))

	for l in eval(edges):
		G.add_edge(l[0],l[1])

	if show:
		plt.ion()
		plt.figure()
		nx.draw(G, pos=nx.get_node_attributes(G,'pos'))
		plt.show(block=False)
	return G

def time_dist(type):
    if type == 'long':
	## distribution along a big timeframe
	return 2600
    elif type == 'short':
	## distribution along a short timeframe
	return 600

def allocate_source(G, num, time, d_max=100):
    s = []
    l = []
    import numpy as np
    # Who is given as source?
    # from all nodes, we will choose sources following a uniform random distribution
    # with x = num / 3 << Num_nodes

    def linked_(u,v,p):
	#is u and v linked?
	if (np.random.pareto(1.,size=num)[p] +1) * 2. > 5.: ## calculation may be wrong
		return True

	return False
    ru = np.random.uniform(0, 1, size=num) ## random uniform is too much!
    pos = -1
    tmpl = []
    for u in ru: 
	pos += 1
	if u > (1. - ((num / 6)/100.)): ## to skew a little bit more the number of sources
		s.append(pos)
    return s


def allocate_peers(G, sources, num, time):
    s = G.nodes()
    l = G.edges()
    p = []
    import numpy as np

    #as uniform random for all nodes
    #For each source
    for tmps in sources:
    	map = np.random.uniform(0, 1, size=num) > 0.8 #in a 80/20 rule

    	tmpp = []

    	for tp in range(0, num -1):
		if map[tp]:
			if not tp in sources: tmpp.append(tp) ## its a peer
	if len(tmpp) > 0: p.append([tmps,tmpp])

    return p

def allocate_links(G, sources, peers, num, time):
    l = set()
    #From the edges already created (physical)

    for i in sources: l.add(i)

    for i in peers:
	for j in i[1]:
		l.add(j)

    sg = G.subgraph(l)
    return sg.edges(), sg

def create_workload(G, type, show=False):
    wl = []
    
    #Given a Graph G(n,v) and type
    #where type in [long, short]
    timetype = time_dist(type)

    # allocate sources for given service
    sources = allocate_source(G, len(G.nodes()), timetype)
    #print sources

    # allocate peers for a given service
    peers = allocate_peers(G, sources, len(G.nodes()), timetype)
    #print peers

    # allocate links between peers and sources
    links, sg = allocate_links(G, sources, peers, len(G.nodes()), timetype)

    ## Now we have Graph, sources, peers for each source
    import matplotlib.pyplot as plt
    import networkx as nx
    #positions for each source
    sPos = []
    pPos = []
    spPos = []
    tmpPos = []
    #stmp = set()

    for i in sources: sPos.append(G.nodes(data=True)[i])
    #pdb.set_trace()
    
    for i in peers:
	tmpPos = [] 
	for j in i[1]:
		tmpPos.append(G.nodes(data=True)[j])
		pPos.append(G.nodes(data=True)[j])
	spPos.append([i[0], tmpPos])
    
    plt.ion()
    fig = plt.figure()
    #nx.draw(G, pos=nx.get_node_attributes(G,'pos'))
    #fig.add_axes([0,500])
    import networkx as nx; nx.draw_networkx_edges(sg, pos=nx.get_node_attributes(G,'pos'))
    for tmp in sPos: 
	plt.scatter(tmp[1]['pos'][0], tmp[1]['pos'][1], s=100, marker='o', color='blue')
	plt.annotate("S%d" % tmp[0], (tmp[1]['pos'][0], tmp[1]['pos'][1]), fontsize=15, fontweight='bold', color='red')
    for tmp in pPos: 
	plt.scatter(tmp[1]['pos'][0], tmp[1]['pos'][1], s=100, marker='x', color='black')
	plt.annotate("P%d" % tmp[0], (tmp[1]['pos'][0], tmp[1]['pos'][1]), fontsize=15, fontweight='bold', color='green')
    plt.show(block=show)

    
    #allocate_links
    # PUT IT TO RUN on sim!

    return sPos,spPos, links

def start_network(net):
    info('\n*** Starting network\n')
    net.build() ## Build should do the same as start but it will interconnect hosts
    #net.start()
    return net

def config_nodes(seed_node, dh):
    if serf_conf:
    	info("** Configuring node(s)\n")
    	for d in dh:
		ip = (254 - int(str(d).split("d")[1]))
		sys.stdout.write(str(d) + " - ")
		sys.stdout.flush()
		port = 5001
		dev=str(d) + "-mp0"
	## Calling inside script to configure each container
		nn=d.cmd("/bin/bash /home/config-serf.sh config rpc=127.0.0.1:7373 port=" + str(port) + " dev=" + str(dev) + " seed=" + str(seed_node))
		n1=d.cmd("/bin/bash /home/config-serf.sh createMon") #maybe just for one
		if nn and n1:
			print("Configured for 10.0.0.%s:%d in device %s " % (str(ip),port, dev))
			print("> %s " % (nn))
			print("> %s " % (n1))
		else:
			print("** Error in configuring %s " % (str(d)) )

def container_constraint(node=None, dh=None):
    quota={'cpu_quota': -1, 'cpu_period': -1, 'cpu_shares': -1, 'mem_limit': -1}
    if constraint:
	info("* Constraining docker container cpu and memory usage (per default)\n")
	quota['cpu_quota']=50000
	quota['cpu_period']=50000
	quota['cpu_shares']=-1
	quota['mem_limit']="2g" # Not working correctly
	
	## ContainerNet uses updateCpuLimit and updateMemoryLimit on the docker nodes
	if node:
		node.updateCpuLimit(cpu_quota=50000, cpu_period=50000) ## just to check	
	else:
		for d in dh:
			d.updateCpuLimit(cpu_quota=50000, cpu_period=50000) ## just to check

		## or i need to go through net
	


## Starts the network and hosts
def topology(num=100, max_r=100, mode="g", xp=None, plot=False, ping=False, serf_conf=False, devmodel=None, sleep_test=-1, new_met=False):
    info("Creating a network with docker containers acting as hosts and wireless mesh network environment.\n")

    net = Containernet(controller=Controller)

    #info('*** Adding docker containers\n')
    ## In automated way will create Hosts
    dh = []
    
    if load_topo:
	net,dh,num=load_positions(net)
	net=start_network(net)
	seed_node = "10.0.0.254:5001" ## seed will be always the first container!
	config_nodes(seed_node, dh)
	printTopo(net, num=num, plotgrp=plot, ping=ping)
	if not xp: info("> Not running automatic experience!\n")
	else: #TODO: for now there is only one!!!!!
		experiment1(net, dh, num=num, sleep_test=sleep_test, new_met=new_met)
	info('*** Running CLI\n')
	CLI(net)
	info('*** Stopping network')
	net.stop()
	sys.exit() ## save(?) and exit

    #Using the new method to calculate positions
    info("*** Creating positions for nodes\n")
    listPos, G=prepareGraph(num, max_r)
    print("* Nodes positions created!")

    print("** Creating %d Station(s) " % (num))

    if save_topo:
	    with open(save_topo_file, "w+") as tdh:
		#start writing things
		#NumOfHosts;[(posx,posy,posz),..];docker_image;device_model;range;ip?;other info
		tdh.write("### Topology for %d hosts\n" % (num))
		tdh.write("#NumOfHosts;[(posx,posy,posz);docker_image;device_model;range;ip?];other info\n")
		tdh.write("NumOfHosts=%d;\n" % num)
		tdh.flush()

    for x in range(0, num):
	ip = (254 - x)
	posx,posy = getPosition(listPos)
	posz = 10
	r=max_r
	position=str(posx) + ',' + str(posy) + ',' + str(posz)
	## This will create the hosts with image ubuntu:trusty, position and range of the device
	## other information can be added later
	#dh.append("null")
	dh.append(net.addDocker('d' + str(x), cls=Docker, ip='10.0.0.' + str(ip), dimage=docker_image, position=position, range=r, mode=mode, equipmentModel=devmodel))
	d = dh[x]
	sys.stdout.write(str(d) + " ")
	sys.stdout.flush()
	if save_topo:
		with open(save_topo_file,"a+") as tdh:
			tdh.write("[\nnode_num=%d;\nposition=(%s);\ndocker_image=%s;\nequip_model=%s;\nrange=%d;\nmode=%s;\nip=10.0.0.%d;\n]\n" % (x,position,docker_image,devmodel,r,mode,ip))
			tdh.flush()

    container_constraint(dh=dh)

    info("\n** Adding nodes to Mesh\n")
    hlinks = []
    for x in dh:
	hlinks.append(net.addMesh(x, ssid='meshNet'))
	x.verifyingNodes(x)
    
    ## Mesh routing is not doing a mesh, only 1 to nearby
    meshr=net.meshRouting("custom")
    info("** Routing nodes through mesh\n")
    for x in dh:
    	meshRouting.customMeshRouting(x, 0, net.wifiNodes)
    	sys.stdout.write(str(x) + " ")
    	sys.stdout.flush()

    start_network(net)

    seed_node = "10.0.0.254:5001" ## seed will be always the first container!
    config_nodes(seed_node, dh)

    # This will print the topology and network configuration of the
    # random created network
    printTopo(net, num=num, plotgrp=plot, ping=ping)
    
    # The simulation selected will start:
    if not xp: info("> Not running automatic experiment!\n")
    elif xp == "None": info("> Not running automatic experiment\n")
    elif xp == 'dataset':
	exp_dataset(net)
    else: #TODO: for now there is only one!!!!!
   	experiment1(net, dh, num=num, sleep_test=sleep_test, new_met=new_met)

    info('*** Running CLI\n')
    CLI(net)

    info('*** Stopping network')
    net.stop()

## service type has its own distribution should be studied more throughly
service_dict = {'storage': numpy.random.normal(loc=num_hosts/2, scale=num_hosts/2), 
		'video': (numpy.random.pareto(6., num_hosts) +1) * 2., 
		'random': randint(1, num_hosts), 
		'none': 0}

def create_source(nodes, node, ns, prob=None):
	## If ns == 0 then it is peer
	s = False
	if not ns:
		return nodes, ns, s

	## with some probability node can be a source
	if not prob:
		prob = numpy.random.normal(loc=0, scale=num_hosts)
	if prob > 0:
		nodes[str(node)] = 'source'
		ns = ns - 1
		s = True

	return nodes, ns, s

def get_probs(service, size=num_hosts):
	if service == 'storage': ## normal dist
		return numpy.random.normal(loc=0, scale=((num_hosts/2)/3)+1, size=size)
	elif service == 'video': ## pareto needs to see the actual values
		return numpy.random.pareto(2., size=size)
	elif service == 'random':
		return numpy.random.randint(1, num_hosts, size=size)
	elif service == 'none':
		return 0

def dataset_populate(net, service):
	nodes = {}
	ntmp = None
	num = 0
	listn = []
	#timeframe = numpy.random.normal(loc=3600, scale=3000.0, size=num_hosts) ## centered in 1h, and for each minute
	type = service_dict[service] ## distribution used for service
	#p1 = numpy.random.pareto(6., num_hosts) *2 ## ?

	nsource = numpy.random.randint(1, (num_hosts/3) +1) ## [1, n/3] number of sources
	map = {}

	for n in net.wifiNodes:
		## with probability P1>1 is server
		s = False
		nodes, nsource, s  = create_source(nodes, n, nsource) #, probs=p1)
		
		## For each source of a service
		if s:
			pdb.set_trace()
			## we need to link to other nodes (either source or peer)
			plink = get_probs(service, size=[num_hosts, num_hosts])
			numpy.random.shuffle(plink) ## shuffling
			numpy.fill_diagonal(plink, 0) ## diag = 0


			if service == 'storage':
				plink = plink.clip(0) ## 0's disconnected
			elif service == 'video':
				plink = plink.clip(0.02) - 0.02 ## take out more than 20% (in 80-20 rule)
			plink = plink.round().astype(int) ## 0.0e dont count as 0's

		## for each link create a random timeframe (in a triangle)
			# some nice manipulation of matrix
			# normal distribution where major should be arounc LOC
			tmpp = numpy.random.normal(loc=1200, scale=300, size=numpy.count_nonzero(plink))
			if len(tmpp[tmpp < 0]) > 0:
				tmpp[tmpp < 0] = numpy.random.normal(loc=1200, scale=300, size=len(tmpp[tmpp < 0])) # no negative
			plink[plink > 0] = tmpp #numpy.random.normal(loc=1800, scale=600, size=numpy.count_nonzero(plink))
			
			plink = plink.round().astype(int)
			plink = plink + numpy.transpose(plink) ## make sure triang up and down is the same

			#uplink = numpy.triu(plink) ## only need this one the other part should be assumed equal?
			
			#timeframe = numpy.random.normal(loc=1800, scale=600) # timeframe of the service itself if necessary (perhaps should be longest on source)
			timeframe = get_longest_fs(plink, str(n))

			if timeframe == -1:
				## ERROR: something is wrong with the matrix
				print "Error in matrix creation, row and col should be equal"

			ntmp = (str(n), int(round(timeframe)), service, plink, nodes.get(str(n),'source')) 
			num +=1
			listn.append(ntmp)
	return listn

def get_longest_fs(map, node):
	## from node to int
	import re
	n = int(re.findall('\d+', node)[0])	
	col = map[:,n]
	row = map[n]
	# col and row should be the same

	if max(col) != max(row):
		return -1 ## ERROR!!!!

	return max(col)

def exp_dataset(net):
    pdb.set_trace()
    ## This will start the dataset experiment
    ds = dataset_populate(net, "video")

    print_ds(ds)
	
    net.stop()
    sys.exit(0)


def print_ds(ds, how=None): ## we are going to print the dataset
	sources = len(ds)

	for s in ds:
		print "Source %s with service %s uptime %d and peers as: " % (s[0], s[2], s[1])
		print s[3]

	#if not how: ## in cmd line
			

## Class for experiments:
class Experiments ( ):
	net = None
	hosts = []
	num = 0
	experiment = None #Default()
	name = None

#	names = {'dataset': exp_dataset(), 'experiment1': experiment1(net, hosts, num=num), '1': experiment1(net, hosts, num=num), None: None}

	def __init__(experiment, net, hosts, num):
		""" Creating a base class for experiments """

		self.net = net
		self.hosts = hosts
		self.num = num
		self.experiment = names[experiment]
#		self.name = experiment

	def name():
		return name

	def run():
		return experiment


#### SHOULD BE DONE AS A CLASS AND CALLED ONLY 1
def experiment1(net, dh, num=30, sleep_test=-1, new_met=False):
    info('*** Starting our simulation\n')
    if sleep_test < 0:
    	slpv=10 * num / 4 ### SLEEP VARIABLE!!!!
    else:
    	slpv=sleep_test +60 ## given by argument
	## +60 just to make sure every node gets information
	## after the test is completed

    #This will start our simulation of SERF+monitor
    #Calling our inside script to start the processes
    st=time.time()
    file_to='%ssimul' % save_to
    file_to+= '-' + str(docker_image) + '-' + str(num) + '-' + str(int(time.time())) + '.txt'
    with open(file_to, "a+") as myfile:
    	for d in range(0, num):
		slp_t= slpv - 30 # service needs to unpublish before test ends
		dh[d].sendCmd("/bin/bash /home/config-serf.sh test " + str(slp_t) + " 2>&1 /dev/null &")
		info("> %s node test running\n" % (dh[d]))
		if new_met: 
			see_pubnew(dh, out=myfile)
		else:
			see_pub(dh, out=myfile)
	#dh[d+1].cmd("/bin/bash /home/config-serf.sh test 50")
		#time.sleep( 1 ) ## So that each will start after each other
	ft = time.time() # the last Host to be launched
    	
	info("** All nodes have published services.\n")
   	info("** waiting for all nodes to end.")
   	et=0
	spaces=32
	while ((ft + slpv) - et ) >= 0: ## while within the time frame
		if spaces > 50:
			sys.stdout.write("\n")
			spaces = 0
			sys.stdout.flush()
		sys.stdout.write(".")
		sys.stdout.flush()
		spaces+=1
		if new_met: 
			see_pubnew(dh, out=myfile)
		else:
			see_pub(dh, out=myfile)
		#time.sleep(2)
	    	et=time.time()
	sys.stdout.flush()
	myfile.flush()
    	print("\n")
    	if new_met:
		info("*** Saving Information for each node (new method)\n")
		info("* -> ")
		see_pubnew(dh, out=myfile, get_f=True)
		for i in dh: ## because its not removing
			if os.path.exists("%spub_members_%s.txt" % (save_to, i)):
				os.remove("%spub_members_%s.txt" % (save_to, i))
    	printTopo(net, out=myfile, num=num, plotgrp=False, ping=False)

    data = ''
    ## Because we are getting some strange stuff in the buffers
    # workaround is to scp from inside container

    db_dir = save_to
    if serf_conf:
    	info("*** Saving SERF-monitor databases to %s\n" % db_dir)
	info("* -> ")
    	for d in dh:
		sys.stdout.write("%s " % d)
		sys.stdout.flush()
    		d.cmd("sshpass -p 'mininet' scp -r -o 'StrictHostKeyChecking no' /home/db/* mininet@172.17.0.1:%s%s.db.bz2" % (save_to, d))
	info("\n")

    info("*** Simulation has ended (?)\n")

def removeLost():
    import os
    cmd1 = "sudo docker rm -f $(sudo docker ps -a | grep mn | awk '{print $1}')"
    cmd2 = "sudo mn --wifi"
    cmd3 = "sudo docker stop -t 15 $(sudo docker ps -a | grep mn | awk '{print $1}')"

    info("Using mininet cleanup\n")
    Cleanup.cleanup()

    info("Stopping containers\n")
    os.system(cmd3)
    info("Removing containers\n")
    os.system(cmd1)
    info("IF cleanup was not sucessful. Reboot Machine!\n")
    #print("****>>> Do interrupt (CTRL+C) to start cleaning leftover wireless stuff ")
    #os.system(cmd2)
    #print("do this to clean up things: %s" % cmd2)

def showGraph(G, list, net, num):
    import matplotlib.patches as patches
    import matplotlib.pyplot as plt
    pmax_x = getMaxCoord(None,list=list)
    pmin_x = getMinCoord(None,list=list)
    max_r=60

    ax = None
    
    plt.ion()
    plt.title("Graph")
    ax = plt.subplot(111)
    ax.set_xlabel('meters')
    ax.set_ylabel('meters')
    ax.set_xlim([pmin_x - 10, pmax_x + 10])
    ax.set_ylim([pmin_x - 10, pmax_x + 10])
    ax.grid(True)

    print(">> min %d  max %d num %d" % (pmin_x, pmax_x, num))
    ## For each node draw it
    nodes = G.nodes(data=True)
    #pdb.set_trace()
    for n, dn in nodes:
    	color = 'g'
	max_x, max_y = dn['pos']
    	p, =ax.plot(range(pmax_x + num), range(pmax_x + num), \
			linestyle='', marker='.', ms=10, mfc=color)
	p.set_data(max_x, max_y)
    	c=ax.add_patch(
		patches.Circle((0,0),
		max_r, fill=True, alpha=0.1, color=color
		)
	)
	c.set_radius(max_r/2)
	c.center = max_x, max_y
	t=ax.annotate(n, xy=(0,0))
	if hasattr(t, 'xyann'):
		t.xyann=(max_x, max_y)
	else: t.xytext=(max_x, max_y,)

    plt.draw()

def save_workload(sPos, pPos, wl, path, file='workload_save.wss'):
	file = path + file

	with open(file, "w+") as wf:
		#nodes = swg.nodes(data=True) ## nodes data
		#edges = swg.edges(data=True) ## edges for each node
		## Saving to file Nodes and edges
		wf.write("sources = %s\n" % sPos)
		wf.write("peers = %s\n" % pPos)
		wf.write("links = %s\n" % wl)
		wf.flush()
		

def str2bool(v):
	return v.lower() in ("yes", "true", "t", "1", "y","quit","q")

if __name__ == '__main__':
    setLogLevel('info')
    ## Starting with num of hosts
#    removeLost()
    if sys.argv > 1:
    	try:
    		opts, args = getopt.getopt(sys.argv[1:],"y:z:m:c:d:hgpas:t:oun:e:r:l:f:q",["test=","device-model=","nhosts=", "range=", "experiment=", "clear=", "docker-image=", "save-to="])
    	except getopt.GetoptError:
    		print 'Error on getting arguments'
    		sys.exit(2)

    for opt, arg in opts:
    	if opt in ('-n', '--nhosts'):
		num_hosts=int(arg)
    		print "The number of hosts will be %d" % (num_hosts)
	if opt in ('--test'):
		#SmallWorldGraph(30, 100)
		net = Containernet(controller=Controller)
		CLI(net)
		sys.exit(0)
    	if opt in ('-m', '--device-model'):
		emodel=str(arg)
    		print "The device model used is %s" % (emodel)
	if opt in ('-r', '--range'):
		max_r=int(arg)
		print "The hosts will have %d as maximum range" % (max_r)
	if opt in ('-e', '--experiment'):
		experiment=str(arg) # or None for no experiment creation
		print "We will run experiment %s after creating the random network" % (experiment)
	if opt == '-p':
		plot_graph=True
		print "A Plot will be shown of the network graph"
	if opt == '-o':
		pingO=True
		print "In topology ping will be done to all nodes"
	if opt == '-a':
		serf_conf=True
		print "Auto configuring nodes with SERF"
	if opt == '-l':
		sleep_test=int(arg)
		print "Sleep time for each node will be %d " % sleep_test
	if opt == '-u':
		new_met=True
		print "Using new method to save experiment information"
	if opt in ('-t','--docker-image'):
		docker_image=str(arg)
	if opt in ('-f','--save-to'):
		save_to=str(arg)
		## create dir if not yet
		import os.path
		#import os.makedirs
		if os.path.isfile(save_to):
			print ("Please I need a folder!")
			os.exit(-1)
		if not os.path.exists(save_to):
			os.makedirs(save_to)
		from subprocess import Popen, PIPE
		#making sure everyone can see folder
		Popen(['/bin/bash', '-c', 'sudo chmod 777 %s' % save_to], stdout=PIPE).communicate()[ 0 ]
		
		print "Saving files to %s " % save_to
	if opt == '-s':
		#will be saved to -f
		save_topo_file=save_to + str(arg) # 'topology.tdh'
		save_topo=True
		print "Saving topology to %s" % save_topo_file
	if opt == '-d':
		#this will make it load topology from file instead of creating
		load_topo=save_to + str(arg)
	if opt == '-q':
		#this will make default constrains to docker containers
		constraint=True

	if opt == '-z':
		print "Creating dataset for network as a SmallWorld network"
		num = int(arg.split(",")[0])
		mr = int(arg.split(",")[1])
		if len(arg.split(",")) >= 3:
			sets = int(arg.split(",")[2]) 
		else: sets = 0
		## We have a graph
		## now we are going to save it to file
		for i in range(0, sets):
			#import pdb; pdb.set_trace()
			swg = SmallWorldGraph(num, mr)
			print "Saving to file: dataset_%d.dss" % i
			file = "dataset_%d.dss" % i
			with open(save_to + str(file), "w+") as f:
				nodes = swg.nodes(data=True) ## nodes data
				edges = swg.edges(data=True) ## edges for each node
				## Saving to file Nodes and edges
				f.write("nodes = %s\n" % nodes)
				f.write("edges = %s\n" % edges)
				f.flush()
		sys.exit()
	if opt == '-y':
		print "Creating workloads for network"
		file = str(arg.split(",")[0])
		type = str(arg.split(",")[1])
		num_w = int(arg.split(",")[2])
		files = []
		if os.path.isdir(file): ### many at once
			for f in os.listdir(file): 
				if f.endswith(".dss"): 
					files.append(f)

		if len(files):
			for f in files:
				swg = load_G_from_file(save_to + f, show=True)
				sPos,pPos,wl = create_workload(swg, type)
				save_workload(sPos,pPos,wl, save_to, file=f)
			print files
			print "Not implemented yet"
			sys.exit()
			#LoadFILES
		
		swg = load_G_from_file(save_to + file, show=True) ## SHOW only for debug
		# do num_w times
		sPos,pPos,wl = create_workload(swg, type, show=True)
		save_workload(sPos,pPos,wl, save_to)

		sys.exit()
 
   	if opt == '-h':
		print "Usage %s -<n|r|p|o|e> <argument> -<h|c|g>" % sys.argv[0]
		print "n|r|p|o|e|s|u should always come first"
		print "***********************"
		print "** These are the Commands available: "
		print "-n X = number of nodes"
		print "-r X = range of device" 
		print "-e <str> = experiment to run"
		print "-p = plot graph" 
		print "-g = only plot a graph (testing purposes)"
		print "-t <image> = Change docker image to be used by the virtual nodes"
		print "-c <q>= Clean up the last status and quit if with argument or continue without" 
		print "-o = Do ping all on topology"
		print "-a = Auto configuration of SERF in the nodes"
		print "-m <model> = The device model it will use"
		print "-l <num_milisecs> = Time for test to run (in milisecs)"
		print "-u = Use new method to save information (new uses scp to get files from containers, old uses mininet cmd)"
		print "-f = Save files to folder"
		print "-s X = Save topology to X file on same folder as specified in -f, later can be loaded with -d"
		print "-d X = Load topology from X file"
		print "-q = Constrain the nodes with default values (CPU 50%, memory 2G)"
		print "-z = Create Dataset of network (do -z num_nodes,max_radius,num_sets )"
		print "-y = Create Workload for network (do -y file/folder,type_of_service,num_workloads)"
		print "************************"

    		print "Go help yourself!"
    		sys.exit()
	elif opt == '-c':
		print "Cleaning up things..."
		removeLost()
		if arg and str2bool(arg):
			sys.exit()
    	elif opt == '-g':
    		print "Creating graph: "
    		net = Containernet(controller=Controller)
    		listPos, G=prepareGraph(num_hosts, max_r/2)
		showGraph(G, listPos, net, num_hosts)
    		#net.plotGraph(max_x=pmax_x + max_x, max_y=pmax_x + max_y, min_x=pmin_x - max_x, min_y=pmin_x - max_y)
		CLI(net)
		sys.exit()

    topology(num=num_hosts, max_r=max_r, mode=mode_ap, xp=experiment, plot=plot_graph, ping=pingO, sleep_test=sleep_test, serf_conf=serf_conf, devmodel=emodel, new_met=new_met)

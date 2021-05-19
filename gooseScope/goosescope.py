#!/usr/bin/env python3

import os,sys
import ctypes
import time
from gooseScope import lib61850
import json
from datetime import datetime
import types

from flask import Flask, Response, render_template, request

import socket
from struct import *
import threading
import binascii

application = Flask(__name__)


control_data_d = {}
control_data_d_update = True
streamFilter = None
streamList = []
streamListingThread = threading.Thread()

subscribers_list = []
subscribers_refs = {}
receiver = None

goose_data = {}

control_data_d['streamSelect_items'] = [] # list of streams
control_data_d['streamSelect'] = { "streamValue": [] } # selected stream


# duration can be > 0 to set a timeout, 0 for immediate and -1 for infinite
def getGOOSEStreams(interface, duration):
    global streamList
    #Convert a string of 6 characters of ethernet address into a dash separated hex string
    def eth_addr (a) :
        b = "%.2x:%.2x:%.2x:%.2x:%.2x:%.2x" % ((a[0]) , (a[1]) , (a[2]), (a[3]), (a[4]) , (a[5]))
        return b

    ret =  os.system("ifconfig %s promisc" % interface)
    if ret != 0:
        print("error setting promiscuous mode on %s" % sys.argv[1])
        sys.exit(-1)

    #create an INET, raw socket
    #define ETH_P_ALL    0x0003          /* Every packet (be careful!!!) */
    # SMV                0x88ba
    # GOOSE              0x88b8
    s = socket.socket( socket.AF_PACKET , socket.SOCK_RAW , socket.ntohs(0x88b8))
    #s.setsockopt(socket.SOL_SOCKET, 25, str(interface + '\0').encode('utf-8'))
    s.bind((interface,0))

    streams = []

    # handle duration
    if duration == 0:
        s.settimeout(0)
        s.setblocking(0)
    if duration > 0:
        s.settimeout(1)
        deadline = time.perf_counter() + duration

    while True:
        if duration > 0 and time.perf_counter() > deadline:
            break
        try:
            packet = s.recvfrom(65565)
        except:
            continue

        #packet string from tuple
        packet = packet[0]
        #parse ethernet header
        eth_length = 14
        dst = eth_addr(packet[0:6])
        src = eth_addr(packet[6:12])
        # parse GOOSE streams, and make a list of them (record appid, MAC, gocbRef, )
        # when an element is chosen, the subscriber can be initialised
        # when a different element is chosen, re-init subscriber with new gocbRef    
        appid = unpack('!H' , packet[eth_length:eth_length+2] )[0]
        gocbRef_length = 25
        gocbRef_size = int(packet[gocbRef_length + 1])
        gocbRef = packet[gocbRef_length + 2 : gocbRef_length + 2 + gocbRef_size].decode("utf-8")
        #print("mac: %s, appid: %i, gocbRef: %s, gocbRef_size: %i" % (dst, appid, gocbRef, gocbRef_size))

        item = "%s %i %s" % (dst,appid,gocbRef)
        if item not in streams:
            streams.append(item)
        if duration == 0:
            break
        if duration < 0:
            streamList = streams

    s.close()
    return streams


@application.route('/')
def index():
    control_data_d_update = True
    return render_template('index.html')


def update_setting(subject, control, value):
    if control == "streamValue":
        global control_data_d
        global control_data_d_update
        global streamList
        global subscribers_list
        global subscribers_refs
        global receiver
        global goose_data

        dif_off = set(subscribers_list) - set(value)
        dif_on = set(value) - set(subscribers_list)
        print(dif_off)
        print(dif_on)
        for item in dif_off:
            unsubscribe(receiver, subscribers_refs[item], start = False)
            print("INFO: GOOSE item %s unsubscribed" % item)
        for item in dif_on:
            if item not in goose_data:
                goose_data[item] = [] # ensure we initialised the dataset

            stream = streamList[int(item)-1].split() # gocbref from itemlist
            dst_mac = binascii.unhexlify(stream[0].replace(':', ''))
            subscribers_refs[item] =  subscribe(receiver, dst_mac, int(stream[1]), stream[2], int(item), start = False)
        # differences have been processed, value is the actual state
        subscribers_list = value

        lib61850.GooseReceiver_start(receiver)
        if lib61850.GooseReceiver_isRunning(receiver) == False:
            print("ERROR: Failed to enable GOOSE subscriber")
        else:# set control-data in the client control if succesfull
            control_data_d[subject][control] = value 
        # update the control now
        control_data_d_update = True
        return True
    return False


@application.route('/control-setting', methods=['POST'])
def control_setting(): # post requests with data from client-side javascript events
    global control_data_d
    content = request.get_json(silent=True)
    for subject in control_data_d:
        if isinstance(control_data_d[subject], dict):    
            for item in control_data_d[subject]:
                if item == content['id']:
                    if update_setting(subject, content['id'],content['value']) != True: # update the setting
                        print("ERROR: could not update setting: " + content['id'])

    return json.dumps({'success':True}), 200, {'ContentType':'application/json'} 


def control_data_g():
    global control_data_d
    global control_data_d_update
    global streamFilter
    global streamList
    streamList_Length = 0
    while True:
        time.sleep(0.1) # check for changes every 0.1 seconds, and if so send update to client

        # update the stream list, if a new entry is found
        if len(streamList) > streamList_Length:
            control_data_d['streamSelect_items'] = []
            for stream in streamList:
                control_data_d['streamSelect_items'].append(stream)
            streamList_Length = len(streamList)
            if streamFilter == None:
                streamFilter = control_data_d['streamSelect_items'][0]
            control_data_d_update = True

        # update the controls when a control is updated
        if control_data_d_update == True:
            control_data_d_update = False
            json_data = json.dumps(control_data_d)
            yield f"data:{json_data}\n\n"


@application.route('/control-data')
def control_data():
    return Response(control_data_g(), mimetype='text/event-stream')


def parse_dataset(dataset):
    time = dataset['time']
    data = dataset['data']
    # filter {} (make it a flat model)
    data = data.replace("{",",")
    data = data.replace("}",",")
    # filter whitespace
    data = data.replace(" ","")
    # convert to a list
    datalist = data.split(",")
    # remove empty items
    datalist = list(filter(None, datalist))

    print(datalist)
    result = []
    # parse items that can be represented in a graph (bools and numerical values)
    for item in datalist:
        # Bools are translated to 0' and 1's in float notation
        # BOOLEAN       true|false
        if item == "true":
            result.append(1.0)
        elif item == "false":
            result.append(0.0)
        # We parse all values as float, as to attempt to normalise it
        # FLOAT         %f
        # INTEDER       %lld
        # UNSIGNED      %u
        else:
            try:
                val = float(item)
                result.append(val)
            except:
                print("INFO: item: '%s' ignored" % item)
            # Not parsed:
            # BIT_STRING    00111011
            # OCTED_STRING  0a0c0d0e
            # STRING        abcd
            # BUG: a bitstring of 1010 may be parsed as a number, but if it changes to 0101 it may not, resulting in a smaller list-size
            # mmsvalue_printtobuffer output does not distinguish enough to infer this
    return {'time':time , 'values': result}


# send the graph data
def stream_data_g():
    global goose_data
    global subscribers_list
    curlen = {}
    while True:
        #print("round")
        time.sleep(0.1)
        stream_update = False
        data = {}
        for stream in subscribers_list:
            if stream not in curlen:
                curlen[stream] = 0

            if stream not in data:
                data[stream] = []

            while len(goose_data[stream]) > curlen[stream]:
                stream_update = True
                #print(goose_data[stream][curlen[stream]])
                dataset = parse_dataset(goose_data[stream][curlen[stream]])
                data[stream].append(dataset)
                curlen[stream] = curlen[stream] + 1
        
        # update the controls when a control is updated
        if stream_update  == True:
            stream_update = False
            json_data = json.dumps(data)
            yield f"data:{json_data}\n\n"


@application.route('/stream-data')
def stream_data():
    return Response(stream_data_g(), mimetype='text/event-stream')

def gooseListener_cb(subscriber, parameter):
    global goose_data
    print("GOOSE event: (parameter: %s)" % parameter)
    #print("  stNum: %u sqNum: %u" % ( lib61850.GooseSubscriber_getStNum(subscriber), lib61850.GooseSubscriber_getSqNum(subscriber) ) )
    #print("  timeToLive: %u" % lib61850.GooseSubscriber_getTimeAllowedToLive(subscriber) )
    timestamp = lib61850.GooseSubscriber_getTimestamp(subscriber)
    #print("  timestamp: %u.%u" % ( (timestamp / 1000), (timestamp % 1000) ) )

    values = lib61850.GooseSubscriber_getDataSetValues(subscriber)
    buf = ""
    buf2 = lib61850.MmsValue_printToBuffer(values, buf, 1024)

    goose_data[str(parameter)].append({'time': int(time.time() * 1000), 'data': buf2.decode("utf-8") })
    # print("%s" % buf2)


# make the callback pointer global to prevent cleanup
gooseListener = lib61850.GooseListener(gooseListener_cb)


def subscribe(receiver, mac, appid, gocbref, param, start = True):
    global gooseListener
    if lib61850.GooseReceiver_isRunning(receiver):
        lib61850.GooseReceiver_stop(receiver)

    subscriber = lib61850.GooseSubscriber_create(gocbref, None)

    if mac != None:
        dstMac_p = (ctypes.c_uint8 * int(6))(*mac)
        lib61850.GooseSubscriber_setDstMac(subscriber, dstMac_p)

    if appid != None:
        lib61850.GooseSubscriber_setAppId(subscriber, appid)
    else:
        appid = -1

    lib61850.GooseSubscriber_setListener(subscriber, gooseListener, param)

    lib61850.GooseReceiver_addSubscriber(receiver, subscriber)

    if start == True:
        lib61850.GooseReceiver_start(receiver)
        if lib61850.GooseReceiver_isRunning(receiver) == False:
            print("Failed to start GOOSE subscriber. Reason can be that the Ethernet interface doesn't exist or root permission are required.")
            sys.exit(-1)
    print("INFO: GOOSE subscribed with: %s %i %s (param: %s)" % (mac, appid, gocbref, param))
    return subscriber


def unsubscribe(receiver, subscriber, start = True):
    if lib61850.GooseReceiver_isRunning(receiver):
        lib61850.GooseReceiver_stop(receiver)

    lib61850.GooseReceiver_removeSubscriber(receiver, subscriber)

    if start == True:
        lib61850.GooseReceiver_start(receiver)
        if lib61850.GooseReceiver_isRunning(receiver) == False:
            print("Failed to start GOOSE subscriber. Reason can be that the Ethernet interface doesn't exist or root permission are required.")
            sys.exit(-1)
    print("INFO: GOOSE unsubscribed")

def determine_path():
    """Borrowed from wxglade.py"""
    try:
        root = __file__
        if os.path.islink (root):
            root = os.path.realpath (root)
        return os.path.dirname (os.path.abspath (root))
    except:
        print("ERROR: __file__ variable missing")
        sys.exit ()
        

def start ():
    global receiver
    path = determine_path()
    print( "path:" + path )
    print("Data files path:")

    files = [f for f in os.listdir(path + "/templates")]
    print("\n" + path + "/templates")
    print(files)

    print("\n" + path + "/static")
    files = [f for f in os.listdir(path + "/static")]
    print(files)
    print("\n")


    receiver = lib61850.GooseReceiver_create()

    if len(sys.argv) > 1:
        print("Set interface id: %s" % sys.argv[1])
        lib61850.GooseReceiver_setInterfaceId(receiver, sys.argv[1])
    else:
        print("Using interface eth0")
        lib61850.GooseReceiver_setInterfaceId(receiver, "eth0")

    # general stream listener thread to catch all streams(subscribed and unsubscribed)
    streamListingThread = threading.Thread(target=getGOOSEStreams, args=(sys.argv[1],-1))
    streamListingThread.start()
    #subs = subscribe(receiver, None, None, "simpleIOGenericIO/LLN0$GO$gcbAnalogValues",str(1))

    application.run(host="0.0.0.0", debug=False, threaded=True) # debug=true will start 2 subscriber threads

    lib61850.GooseReceiver_stop(receiver)

    lib61850.GooseReceiver_destroy(receiver)


if __name__ == "__main__":
    start()




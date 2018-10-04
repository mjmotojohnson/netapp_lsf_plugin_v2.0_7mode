#===============================================================#
#                                                               #
# $ID$                                                          #
#                                                               #
# ontapmon.py - Python script that would collect the following  #
#               counter statistics for the storage system being #
#               managed by OnCommand (DFM) at certain specified #
#               intervals:                                      #
#                       - volume avg_latency                    #
#                       - max disk busy within an aggregate     #
#                       - max domain busy for each non exempt   #
#                         domain                                #
#                                                               #
#               The counter data output is placed in an xml     #
#               file which is named after the storage system IP #
#               Error logs are placed in ontapmon_error.log     #
#                                                               #
#               Usage: ontapmon.py <config_file>                #
#                                                               #
#               where config_file contains user specified       #
#               configuration parameters which include:         #
#                                                               #
#               [env_params]                                    #
#               NMDKDIR = directory location of                 #
#                         netapp-manageability-sdk-5.0          #
#               [dfm_param]                                     #
#               HOST = dfm host                                 #
#               USER = dfm admin or root                        #
#               PASSWD = dfm password                           #
#               [mon_param]                                     #
#               INTERVAL = interval of samples                  #
#               DIRLOC = dir location of where to place xml     #
#                        file and error logs                    #
#               NTHREADS = number of threads to create to run   #
#                        performance monitoring.                #
#               REFRESH = number of times to run with current   #
#                       filer list before refreshing list       #
#                                                               #
# Copyright (c) 2012 NetApp, Inc. All rights reserved.          #
# Specifications subject to change without notice.              #
#                                                               #
#===============================================================#

import time
import signal
import sys
import xml.dom.minidom
from xml.dom.minidom import Document
from ConfigParser import SafeConfigParser
import os
import threading, Queue
import logging, logging.handlers

#
# Usage Error Message
#
def usage():
    print ("Usage:\n")
    print ("ontapmon.py <config_file>\n")
    sys.exit (1)
#
# Gets the list of filers being managed by DFM
# @returns array of hostnames
#
def flist_get(server):
    # creating a input element
    input_element = NaElement("host-list-info-iter-start")
    xi = NaElement("host-types")
    input_element.child_add(xi)
    xi.child_add_string("host-type", "filer")

    # invoking the api and capturing the ouput
    try :
        output = server.invoke_elem(input_element)
    except:
        logger.error("flist_get():Exception getting filer list.", exc_info=1)
        return -1
    else:
        if (output.results_status() == "failed") :
            logger.error("flist_get(): Failed " + output.results_reason() )
            return -1

        # Extracting the record and tag values and printing them
        records = output.child_get_string("records")
        if(int(records) == 0):
            logger.error("flist_get():No datasets to display for host-types" )
            return -1

        tag = output.child_get_string("tag")

        # Iterating through each record
        # Extracting records one at a time
        try:
            record = server.invoke( "host-list-info-iter-next", "maximum", records, "tag", tag )
        except:
            logger.error("flist_get():Exception getting filer list.", exc_info=1)
            return -1
        else:
            if (record.results_status() == "failed") :
                logger.error("flist_get(): Failed " + record.results_reason())
                return -1
    
            # Navigating to the datasets child element
            if(not record):
                logger.error ("flist_get(): no records for datasets")
                return -1
            else:
                stat = record.child_get("hosts")
    
            # Navigating to the dataset-info child element
            if(not stat):
                logger.error("flist_get(): no stat for hosts")
                return -1

            else:
                info = stat.children_get()

            flist = []
            # Iterating through each record
            
            for i in info:
                fname = i.child_get_string("host-name")
                if (fname == None) :
                    continue
                # extracting the dataset name 
                flist.append(fname)

            # invoking the iter-end zapi
            try :
                end = server.invoke( "host-list-info-iter-end", "tag", tag )
            except:
                logger.error("flist_get():Exception getting filer list.", exc_info=1)
                return -1
            else:

                if (end.results_status() == "failed") :
                    logger.error("flist_get(): Failed " + end.results_reason())
                    return -1
                return(flist)
#
# Gets the ip addresses of each filers being managed by DFM
# @returns array of IP addresses of filers
#
def ipaddr_get(server, filer):
    # creating a input element
    input_element = NaElement("netif-ip-interface-list-info")
    input_element.child_add_string("hostname", filer)

    # invoking the api and capturing the ouput
    try :
        output = server.invoke_elem(input_element)
    except:
        logger.error("ipaddr_get():Exception getting filer list.", exc_info=1)
        return -1
    else:
        if (output.results_status() == "failed") :
            logger.error("ipaddr_get(): Failed " + filer + ":" + output.results_reason())
            return -1

        interfaces = output.child_get("interfaces")
        if (interfaces == None) :
            logger.error("ipaddr_get():No interfaces found for object:  " + filer +"" )
            return -1

        netif = interfaces.children_get()
    
        if(netif == None) or (len(netif) == 0):
            logger.error("ipaddr_get():No instances found for object:  " + filer +"" )
            return -1

        # if there are items in ip addr list, delete it.
        if (len(filerDataDict[filer].ipAddr) != 0) :
            del filerDataDict[filer].ipAddr[:]

        for rec in netif :
            iplist = rec.child_get("ip-addresses")

            if (iplist == None) :
                return -1
            ipaddrs = iplist.children_get()

            # There is no provisions to get content of self in NaElement
            # Using the element array of NaElement to get info.
            for rec1 in ipaddrs :
                filerDataDict[filer].ipAddr.append(rec1.element["content"])

#
# Gets the list of aggregates within a filer
# @return list of aggregates
#

def aggrlist_get(filer, server) :
    # creating a input element
    input_element = NaElement("aggregate-list-info-iter-start")
    input_element.child_add_string("object-name-or-id", filer)

    # invoking the api and capturing the ouput
    try :
        output = server.invoke_elem(input_element)
    except:
        # Add trace to logger
        logger.error("aggrlist_get():Exception getting aggr list for " + filer, exc_info=1)
        return -1
    else:
        if (output.results_status() == "failed") :
            logger.error("aggrlist_get(): Failed " + filer + ":" +  output.results_reason())
            return -1

        # Extracting the record and tag values and printing them
        records = output.child_get_string("records")

        if(int(records) == 0) or (records == None):
            logger.error("aggrlist_get(): No datasets to display for " + filer)
            return -1

        tag = output.child_get_string("tag")
        
        if (tag == None) :
            logger.error("aggrlist_get():No tag for filer " + filer)
            return -1

        # Iterating through each record
        # Extracting records one at a time
        try: 
            record = server.invoke( "aggregate-list-info-iter-next", "maximum", records, "tag", tag )
        except:
            logger.error("aggrlist_get():Exception getting aggr list for " + filer, exc_info=1)
            return -1
        else:
            if (record.results_status() == "failed") :
                logger.error("aggrlist_get(): Failed " + filer + ":" + record.results_reason())
                return -1
    
            # Navigating to the datasets child element
            if (record == None) or (not record):
                logger.error("aggrlist_get():No records for " + filer)
                return -1

            else:
                stat = record.child_get("aggregates")
    
            # Navigating to the dataset-info child element
            if (stat == None) or (not stat):
                logger.error("aggrlist_get():No stat for " + filer)
                return -1

            else:
                info = stat.children_get()
        
            if (info == None) :
                logger.error("aggrlist_get():No aggregates for " + filer)
                return -1

            slist = []
            # Iterating through each record
            for info in info:
                aname = info.child_get_string("aggregate-name")
                if (aname == None) :
                    continue
                slist.append(aname)

            # invoking the iter-end zapi
            try :
                end = server.invoke( "aggregate-list-info-iter-end", "tag", tag )
            except:
                logger.error("aggrlist_get():Exception getting aggr list for " + filer, exc_info=1)
                return -1
            else :
                if (end.results_status() == "failed") :
                    logger.error("aggrlist_get(): Failed " + filer + ":" + end.results_reason())
                    return -1
                return(slist)
#
# Gets the volume specific information directly from filer via api-proxy
#
def vollist_get(server, filer) :

    proxyElem = NaElement("api-proxy")
    proxyElem.child_add_string("target", filer)
    apiRequest = NaElement("request")
    apiRequest.child_add_string("name", "volume-list-info-iter-start")

    proxyElem.child_add(apiRequest)
    try :
        out = server.invoke_elem(proxyElem)
    except:
        # Add trace to logger
        logger.error("vollist_get(1): Exception getting vollist info for " + filer, exc_info=1)
        return -1
    else:
        if(out.results_status() == 'failed') :
            logger.error("vollist_get(2): " + filer + ":" + out.results_reason() + "\n")
            return -1

        dfmResponse = out.child_get('response')

        if (dfmResponse.child_get_string('status') == 'failed') :
            logger.error("vollist_get(3): " + filer + ":" + dfmResponse.child_get_string("reason") + "\n")
            return -1

        ontapiResponse = dfmResponse.child_get('results')

        if (ontapiResponse.results_status() == 'failed'):
            logger.error("vollist_get(4): " + filer + ":" + ontapiResponse.results_reason() + "\n")
            return -1

        iter_tag = ontapiResponse.child_get_string('tag')
        records = ontapiResponse.child_get_string('records')


        num_records = 1
        max_records = 10

        while(int(num_records) != 0):
            proxyElem = NaElement("api-proxy")
            proxyElem.child_add_string("target", filer)
            apiRequest = NaElement("request")
            apiRequest.child_add_string("name", "volume-list-info-iter-next")
            apiargs = NaElement("args")
            apiargs.child_add_string("tag", iter_tag)
            apiargs.child_add_string("maximum", max_records)
            apiRequest.child_add(apiargs)
            proxyElem.child_add(apiRequest)
            try :
                out = server.invoke_elem(proxyElem)
            except:
                logger.error("vollist_get(5):Exception from " + filer, exc_info=1)
                return -1
            else: 
                if(out.results_status() == 'failed') :
                    logger.error("vollist_get(6): " +filer + ":" + out.results_reason() + "\n")
                    return -1

                dfmResponse = out.child_get('response')

                if (dfmResponse.child_get_string('status') == 'failed') :
                    logger.error("vollist_get(7):  " + filer + ":"  + dfmResponse.child_get_string("reason") + "\n")
                    return -1

                ontapiResponse = dfmResponse.child_get('results')

                if (ontapiResponse.results_status() == 'failed'):
                    logger.error("vollist_get(8) " + filer + ":" + ontapiResponse.results_reason() + "\n")
                    return -1

                num_records = ontapiResponse.child_get_int("records")

                if (num_records == None) :
                    return -1;
                if(num_records > 0) :
                    instances_list = ontapiResponse.child_get("volumes")   
                    instances = instances_list.children_get()

                    for inst in instances:
                        inst_name = inst.child_get_string("name")
                        if (inst_name == None) :
                            logger.error("vollist_get(9): Got NoneType for inst_name for filer " + filer + "\n")
                            return -1
                        state = inst.child_get_string("state")
                        # Only record volumes that are online
                        if (state != "online") :
                            continue

                        vtype = inst.child_get_string("type")
                        ssize = inst.child_get_string("size-available")
                        fu = inst.child_get_string("files-used")
                        fT = inst.child_get_string("files-total")
                        # Sometimes the XML is corrupt so need to check for None
                        if ( (ssize == None) or (fu == None) or (fT == None) or (vtype == None) ) :
                            logger.error("vollist_get(10): Got None Type for values for " + inst_name)
                            return -1
                        # Convert values to int
                        asize = int(ssize)
                        filesUsed = int(fu)
                        filesTotal = int(fT)
                        if (vtype == "flex") :
                            aggrName = inst.child_get_string("containing-aggregate")
                            if (aggrName == None) :
                                return -1
                        # For traditional volumes, aggr name is vol name
                        else :
                            aggrName = inst_name
                            
                        try: 
                            filerDataDict[filer].aggrDataDict[aggrName].volumeDataDict[inst_name].availSize = asize
                            filerDataDict[filer].aggrDataDict[aggrName].volumeDataDict[inst_name].availInodes = filesTotal - filesUsed
                        except:
                            logger.error("vollist_get(11):Exception in vollist_get: filerDataDict setting of asize and availInodes")
                            logger.error("looking up: Filer = %s, Aggr = %s, Volume = %s" %(filer, aggrName, inst_name))
                            logger.error("Filer Keys %s" %(filerDataDict.keys()))
                            # Check for existence of aggrName and inst_name
                            # before printing it out.
                            if (aggrName in filerDataDict[filer].aggrDataDict) :
                                logger.error("Aggr Keys %s" %(filerDataDict[filer].aggrDataDict.keys()))
                            if (inst_name in filerDataDict[filer].aggrDataDict[aggrName].volumeDataDict) :
                                logger.error("Volume Keys %s" %(filerDataDict[filer].aggrDataDict[aggrName].volumeDataDict.keys()))
                            return -1

        apiRequest.child_add_string("name", "volume-list-info-iter-end")
        apiargs = NaElement("args")
        apiargs.child_add_string("tag", iter_tag)
        apiRequest.child_add(apiargs)
        proxyElem.child_add(apiRequest)
        try:
            out = server.invoke_elem(proxyElem)
        except:
            logger.error("vollist_get(12):Exception vollist_get() from " + filer, exc_info=1)
            return -1
        else:
            if(out.results_status() == 'failed') :
                logger.error("vollist_get(13):Exception getting vollist_get():" + filer + ":" + out.results_reason() + "\n")
                return -1
            dfmResponse = out.child_get('response')

            if (dfmResponse.child_get_string('status') == 'failed') :
                logger.error("vollist_get(14): " + filer + ":" + dfmResponse.child_get_string("reason") + "\n")
                return -1

            ontapiResponse = dfmResponse.child_get('results')
            if (ontapiResponse.results_status() == 'failed'):
                logger.error("vollist_get(15) " + filer + ":" + ontapiResponse.results_reason() + "\n")
                return -1
        return 0

#
# Gets the performance counters, domain_busy, for non-exempt domains
# directly from DFM.
# @returns array of performance data for domain

def domainperf_get(obj_name, server) :
    # Create API request
    perf_in = NaElement("perf-get-counter-data")

    perf_in.child_add_string("number-samples", 1)        
        
    instance_info = NaElement("instance-counter-info")
    counter_info = NaElement("counter-info")
    instance_info.child_add_string("object-name-or-id", obj_name)

    perf_obj_ctr1 = NaElement("perf-object-counter")
    perf_obj_ctr1.child_add_string("object-type", "processor")
    perf_obj_ctr1.child_add_string("counter-name", "domain_busy")
    perf_obj_ctr1.child_add_string("label-names", "kahuna")
        
    perf_obj_ctr3 = NaElement("perf-object-counter")
    perf_obj_ctr3.child_add_string("object-type", "processor")
    perf_obj_ctr3.child_add_string("counter-name", "domain_busy")
    perf_obj_ctr3.child_add_string("label-names", "storage")
    
    perf_obj_ctr4 = NaElement("perf-object-counter")
    perf_obj_ctr4.child_add_string("object-type", "processor")
    perf_obj_ctr4.child_add_string("counter-name", "domain_busy")
    perf_obj_ctr4.child_add_string("label-names", "raid")
        
    perf_obj_ctr5 = NaElement("perf-object-counter")
    perf_obj_ctr5.child_add_string("object-type", "processor")
    perf_obj_ctr5.child_add_string("counter-name", "domain_busy")
    perf_obj_ctr5.child_add_string("label-names", "target")
    
    perf_obj_ctr6 = NaElement("perf-object-counter")
    perf_obj_ctr6.child_add_string("object-type", "processor")
    perf_obj_ctr6.child_add_string("counter-name", "domain_busy")
    perf_obj_ctr6.child_add_string("label-names", "cifs")
        
    perf_obj_ctr7 = NaElement("perf-object-counter")
    perf_obj_ctr7.child_add_string("object-type", "processor")
    perf_obj_ctr7.child_add_string("counter-name", "domain_busy")
    perf_obj_ctr7.child_add_string("label-names", "nwk_legacy")

    counter_info.child_add(perf_obj_ctr1)            
    counter_info.child_add(perf_obj_ctr3)
    counter_info.child_add(perf_obj_ctr4)
    counter_info.child_add(perf_obj_ctr5)
    counter_info.child_add(perf_obj_ctr6)
    counter_info.child_add(perf_obj_ctr7)

    instance_info.child_add(counter_info)
    perf_in.child_add(instance_info)
    try:
        perf_out = server.invoke_elem(perf_in)
    except:
        logger.error("domainperf_get():Exception getting domain counters for " + obj_name, exc_info=1)
        return -1
    else:
        if(perf_out.results_status() == "failed") :
            logger.error("domainperf_get(): Failed " + obj_name + ":" + perf_out.results_reason())
            return -1
	
        return perf_out

#
# Gets the performance counters, avg_latency and disk_busy, for aggregate
# directly from DFM.
# @returns array of performance data for aggregate
def aggrperf_get(obj_name, server) :
    # Create API request
    perf_in = NaElement("perf-get-counter-data")
    
    perf_in.child_add_string("number-samples", 1)        

    instance_info = NaElement("instance-counter-info")
    counter_info = NaElement("counter-info")
    instance_info.child_add_string("object-name-or-id", obj_name)
        
    perf_obj_ctr1 = NaElement("perf-object-counter")
    perf_obj_ctr1.child_add_string("object-type", "volume")
    perf_obj_ctr1.child_add_string("counter-name", "avg_latency")
        
    perf_obj_ctr2 = NaElement("perf-object-counter")
    perf_obj_ctr2.child_add_string("object-type", "disk")
    perf_obj_ctr2.child_add_string("counter-name", "disk_busy")

    counter_info.child_add(perf_obj_ctr1)
    counter_info.child_add(perf_obj_ctr2)
    instance_info.child_add(counter_info)

    perf_in.child_add(instance_info)
    try: 
        perf_out = server.invoke_elem(perf_in)
    except:
        logger.error("aggrperf_get():Exception getting aggregate counters for " + obj_name, exc_info=1)
        return -1
    else :
        if(perf_out.results_status() == "failed") :
            logger.error("aggrperf_get(): Failed " + obj_name + ":" + perf_out.results_reason())
            return -1

        return perf_out


#
# Extracts the performance counter data from the instances
# @return 0 for success, -1 for error
#
def extract_aggr_counter_data(perf_out, objname) :


    # Get filer name and aggregate name
    str_arr = objname.split(':')
    fname = str_arr[0]
    aname = str_arr[1]

    instance = perf_out.child_get("perf-instances")

    # Allocate space for aggregate in dictionary
    if (aname not in filerDataDict[fname].aggrDataDict) :
        filerDataDict[fname].aggrDataDict[aname] = AggrData()

    # Initialize maxdisk busy value
    filerDataDict[fname].aggrDataDict[aname].maxdiskb = 0.0

    if (instance == None) :
            logger.error(":No instance found for object:  " + objname +"" )
            return -1

    instances = instance.children_get()

    if (instances == None) or (len(instances) == 0):
            logger.error("extract_aggr_counter_data():No instances found for object:  " + objname +"" )
            return -1
    
    for rec in instances :
        inst_name = rec.child_get_string("instance-name")
        obj_id = rec.child_get_string("object-id")

        counters = rec.child_get("counters")

        if(counters == None) :
            logger.error("extract_aggr_counter_data():No counter data found for object:  " + objname +"" )
            return -1

        perf_cnt_data = counters.children_get()

        if(perf_cnt_data == None) or (len(perf_cnt_data) == 0):
            logger.error("extract_aggr_counter_data():No counter data found for object:  " + objname +"" )
            return -1

        for rec1 in perf_cnt_data :
            counter_name = rec1.child_get_string("counter-name")
            counter_str = rec1.child_get_string("counter-data")
            if (counter_str == None) or (len(counter_str) == 0) :
                logger.error("extract_aggr_counter_data():No records found for counter-name :  " + objname +"" )
                
                continue
                        
            counter_arr = counter_str.split (',')

            if(counter_name == "avg_latency") :
                for time_val in counter_arr :
                    time_val_arr = [float(s) for s in time_val.split(':')]
                    if (inst_name not in filerDataDict[fname].aggrDataDict[aname].volumeDataDict) :
                        filerDataDict[fname].aggrDataDict[aname].volumeDataDict[inst_name] = VolumeData()
		     # Avglatency is returned in microseconds from DFM.  
		     # Want values to be in milliseconds
                    filerDataDict[fname].aggrDataDict[aname].volumeDataDict[inst_name].avglatency = time_val_arr[1]/1000.0
            elif(counter_name == "disk_busy") :
                for time_val in counter_arr :
                    time_val_arr = [float(s) for s in time_val.split(':')]
                    
                    if (time_val_arr[1] > filerDataDict[fname].aggrDataDict[aname].maxdiskb):
                        filerDataDict[fname].aggrDataDict[aname].maxdiskb = time_val_arr[1]
	
    return 0
#
# Extracts the domain performance counter data from the instances
# @returns 0 for sucess, -1 for error
#
def extract_domain_counter_data(perf_out, objname) :
    instance = perf_out.child_get("perf-instances")

    if (instance == None) :
        logger.error("extract_domain_counter_data():No instance found for object:  " + objname +"" )
        return -1

    instances = instance.children_get()
    
    if(instances == None) or (len(instances) == 0):
        logger.error("extract_domain_counter_data():No instances found for object:  " + objname +"" )
        return -1
    
    for rec in instances :
        inst_name = rec.child_get_string("instance-name")
        obj_id = rec.child_get_string("object-id")
        counters = rec.child_get("counters")

        if(counters == None) :
            logger.error("extract_domain_counter_data():No counter data found for object:  " + objname +"" )
            return -1

        perf_cnt_data = counters.children_get()

        if(perf_cnt_data == None) or (len(perf_cnt_data) == 0):
            logger.error("extract_domain_counter_data():No counter data found for object:  " + objname +"" )
            return -1

        for rec1 in perf_cnt_data :
            counter_name = rec1.child_get_string("counter-name")
            counter_str = rec1.child_get_string("counter-data")
            lname = rec1.child_get_string("label-names")
            # None type can be returned for label name.  Thus use None as 
            # name for now and continue
            if (lname == None) :
                return -1
            if (lname not in filerDataDict[objname].domainDataDict) :
                filerDataDict[objname].domainDataDict[lname] = DomainData()

            if (counter_str == None) or (len(counter_str) == 0) :
                logger.error("extract_domain_counter_data():No records found for counter-name :  " + objname +"" )
                return -1

            counter_arr = counter_str.split (',')

            for time_val in counter_arr :
                time_val_arr = [float(s) for s in time_val.split(':')]
                if (time_val_arr[1] > filerDataDict[objname].domainDataDict[lname].dvalue) :
                    filerDataDict[objname].domainDataDict[lname].dvalue = time_val_arr[1]

    return 0
#
# Collects aggregate and domain counters and outputs to XML document
#
def perf_mon (filer, server) :
    
    # Get list of aggregates for specific filer
    alist = aggrlist_get(filer, server)
    if (alist == -1) :
        return -1

    # Traverse thru list of aggregates to get aggr counter information
    # if error return -1
    for a in alist :

        perf_out = aggrperf_get(a, server)
        if (perf_out == -1) :
            return -1

        res = extract_aggr_counter_data(perf_out,a)
        if (res == -1) :
            return -1

    # Get domain counters separately, would only need it once.
    # If error, return -1
    perf_out = domainperf_get(filer, server)
    if (perf_out == -1) :
        return -1

    res = extract_domain_counter_data(perf_out, filer)
    if (res == -1) :
        return -1

    res = vollist_get(server, filer)
    if (res == -1) :
        return -1
    
    printToXML(filer)
    return 0

#
# Used only for debugging purposes
#
def printOut() :
    print("**** Filer Data PRINT OUT ****")
    for f in filerDataDict :
        print("FILER: " + f)
        for d in filerDataDict[f].domainDataDict :
            print("Domain:" + d)

            print(filerDataDict[f].domainDataDict[d].dvalue)
        for a in filerDataDict[f].aggrDataDict :
            print("Aggregate:" + a)
            for v in filerDataDict[f].aggrDataDict[a].volumeDataDict :
                print(v)
                print(filerDataDict[f].aggrDataDict[a].volumeDataDict[v].avglatency)

#
# Function that removed dependency on PyXML. Prints out XML file in
# pretty format. 
# @return text_node_fixed_output - pretty XML format
#
def to_pretty_xml(xml_doc):
    original_pretty_xml = xml_doc.toprettyxml(indent=' '*2)

    # Apply a regex fix to format text nodes on one line instead of having
    # the text data on a separate line.
    text_re = re.compile('>\n\s+([^<>\s].*?)\n\s+</', re.DOTALL)
    text_node_fixed_output = text_re.sub('>\g<1></', original_pretty_xml)

    return text_node_fixed_output


#
# Creates XML document based on data collected.
#
def printToXML(f):

    # Set up xml document
    doc = Document()
    pxml = doc.createElement("performance")
    doc.appendChild(pxml)
    ftag = doc.createElement("filer")
    ftag.appendChild(doc.createTextNode(f))
    pxml.appendChild(ftag)
        
    timetag = doc.createElement("lastUpdated")
    timetag.appendChild(doc.createTextNode(time.asctime()))
    pxml.appendChild(timetag)

    # Print out data into doc xml format
    # Print accordingly for ipaddresses
    ipstag = doc.createElement("ipaddresses")
            
    for ip in filerDataDict[f].ipAddr :
        intag = doc.createElement("ipaddress")
        intag.appendChild(doc.createTextNode(ip))
        ipstag.appendChild(intag)
                   
    pxml.appendChild(ipstag)


    aggrstag = doc.createElement("aggregates")
    pxml.appendChild(aggrstag)

    for a in filerDataDict[f].aggrDataDict :
        # Print out data into doc xml format
        # Print accordingly for domain and aggr counters
        atag = doc.createElement("aggr")
        anametag = doc.createElement("name")
        anametag.appendChild(doc.createTextNode(a))
        atag.appendChild(anametag)
        disktag = doc.createElement("maxdiskb")
        disktag.appendChild(doc.createTextNode("%0.5f" %(filerDataDict[f].aggrDataDict[a].maxdiskb)))
        atag.appendChild(disktag)

        volstag = doc.createElement("volumes")
        for v in filerDataDict[f].aggrDataDict[a].volumeDataDict:
            vtag = doc.createElement("volume")
            vnametag = doc.createElement("name")
            vnametag.appendChild(doc.createTextNode(v))
            vtag.appendChild(vnametag)
            avgltag = doc.createElement("avglatency")
            avgltag.appendChild(doc.createTextNode("%0.5f" %(filerDataDict[f].aggrDataDict[a].volumeDataDict[v].avglatency)))
            vtag.appendChild(avgltag)
            asizetag = doc.createElement("availsize")
            asizetag.appendChild(doc.createTextNode("%d" %(filerDataDict[f].aggrDataDict[a].volumeDataDict[v].availSize)))
            vtag.appendChild(asizetag)
            ainodetag = doc.createElement("availinodes")
            ainodetag.appendChild(doc.createTextNode("%d" %(filerDataDict[f].aggrDataDict[a].volumeDataDict[v].availInodes)))
            vtag.appendChild(ainodetag)
            volstag.appendChild(vtag)
        atag.appendChild(volstag)
        aggrstag.appendChild(atag)

    # Print out data into doc xml format
    # Print accordingly for domain counters
    dstag = doc.createElement("domains")
            
    for d in filerDataDict[f].domainDataDict :
        dtag = doc.createElement("domain")
        dntag = doc.createElement("name")
        dntag.appendChild(doc.createTextNode(d))
        dvaluetag = doc.createElement("value")
        dvaluetag.appendChild(doc.createTextNode("%0.5f" %(filerDataDict[f].domainDataDict[d].dvalue)))
        dtag.appendChild(dntag)
        dtag.appendChild(dvaluetag)
        dstag.appendChild(dtag)
                   
    pxml.appendChild(dstag)



    # Open file to write xml data to
    # There should be one file per filer created
    fname = dirloc + "/" + f + ".xml"
    try :
        fp = open(fname, "w")
        fp.write(to_pretty_xml(doc))
    except:
        logger.error("Error in opening file " + fname, exc_info=1)
        return -1
    else:
        fp.close()

#
# Signal handler for SIGTERM
#
def signal_handler_term(signal, frame) :
    print("Caught SIGTERM signal")
    sys.exit(0)

#
# Worker Thread definition. As long as there are items in the queue.
#
class WorkerThread(threading.Thread):
    def __init__(self, workq, resultq, dfm_hostname, username, password):
        super(WorkerThread, self).__init__()
        self.workq = workq
        self.resultq = resultq
        self.dfm_hostname = dfm_hostname
        self.username = username
        self.password = password

    def run(self):
        # Run this thread as long as the work queue is not empty.  
        # If empty, break out of thread
        while True :
            try:
                filer = self.workq.get(True, 0.05)
                # Construct a new NaServer object for each call to perf_mon()
                # to avoid threading issues in NaServer.parse_xml().
                server = construct_server(self.dfm_hostname, self.username, self.password)
                err = perf_mon(filer, server)
                self.resultq.put((err, filer))
            except Queue.Empty:
                break;

#
# Class definitions Filer Information
#

class FilerData(object):
    def __init__(self) :
        self.ipAddr = []
        self.aggrDataDict = {}
        self.domainDataDict = {}

class AggrData(object) :
    def __init__(self) :
        self.volumeDataDict = {}
        self.maxdiskb = 0.0

class VolumeData(object):
    def __init__(self):
        self.avglatency = 0.0
        self.availSize = 0
        self.availInodes = 0

class DomainData(object):
    def __init__(self):
        self.dvalue = 0


        
def construct_server(hostname, username, password):
    server = NaServer(hostname, 1, 0 )
    server.set_style('LOGIN')
    server.set_transport_type('HTTP')
    server.set_server_type('DFM')
    server.set_port(8088)
    server.set_admin_user(username, password)
    return server


#
# MAIN 
#


# get args
args = len(sys.argv) - 1
if(args < 1):
    usage()

# Read config.ini file
parser = SafeConfigParser()
parser.read(sys.argv[1])
nmdkpath = parser.get('env_params', 'NMDKDIR')
sys.path.append(nmdkpath + "/lib/python/NetApp")
from NaServer import *

# Get the parameters from config.ini
dfmserver = parser.get('dfm_param', 'HOST')
dfmuser = parser.get('dfm_param', 'USER')
dfmpw = parser.get('dfm_param', 'PASSWD')
interval = float(parser.get('mon_param', 'INTERVAL'))
dirloc = parser.get('mon_param', 'DIRLOC')
nthreads = int(parser.get('mon_param', 'NTHREADS'))
refresh = int(parser.get('mon_param', 'REFRESH'))

# Set up logger file for errors
logname = dirloc + "/ontapmon_error.log"
logger = logging.getLogger('ontap_monitoring_agent')
handler = logging.handlers.TimedRotatingFileHandler(logname, when='midnight', interval=1, backupCount=7)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

# Set up signal handler
signal.signal(signal.SIGTERM, signal_handler_term)

# Creating a server object and setting appropriate attributes
server_ctx = construct_server(dfmserver, dfmuser, dfmpw)

#Define the Filer Data Dictionary to hold filer/volume data
filerDataDict = {}

# Create work threads to get counters for filers
while True : 
    
    # get list of filers
    flist_arr = flist_get(server_ctx)

    # If unable to get list of filers or there is no filers being
    # managed by DFM, sleep for specified interval and recheck after
    if (flist_arr == -1) or (flist_arr == None) :
        logger.error("No filers to process")
        time.sleep(interval)
        continue
    
    for f in flist_arr :
        if (f not in filerDataDict) :
            filerDataDict[f] = FilerData()
        res = ipaddr_get(server_ctx, f)
        if (res == -1) :
            logger.error("main(): ipaddr_get() unable to get ip for filer " + f)

    workq = Queue.Queue()
    resultq = Queue.Queue()
    ntimes = 0
    nwork = len(flist_arr)
    nthr = nthreads
    # Initialize workq with filers to process
    for f in flist_arr:
        workq.put(f)

    # Work on current list of filers for specified number of times
    # After ntimes, refresh list of filers
    while (ntimes < refresh):
        # Do not create more threads then there are number of filers on workq
        if (nwork < nthreads) : 
            nthr = nwork
        pool = [WorkerThread(workq=workq, resultq=resultq, dfm_hostname=dfmserver, username=dfmuser, password=dfmpw) for i in range(nthr)]
        # Start the threads
        for t in pool :
            t.start()
            
        # Wait for the threads to process all the items in workq
        for t in pool :
            t.join()

        ntimes = ntimes + 1
        succ = 0
        while nwork > 0 : 
            result = resultq.get()
            # If no errors and able to get information 
            # from filers, add to workq else skip it
            if (result[0] == 0) :
                workq.put(result[1])
                succ = succ + 1
            nwork = nwork - 1
        
        # reset number of work to do
        nwork = succ

        # sleep for specified number of seconds
        time.sleep(interval)

     

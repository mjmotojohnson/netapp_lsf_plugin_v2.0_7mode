
NetApp Filer-aware Plugin Installation and Configuration
--------------------------------------------------------

o) Overview

  This package contains the source and supporting files for an LSF
  scheduler plugin that dispatches jobs to run based on the "load" on
  a set of Netapp filers. LSF jobs indicate which mount points (filer:/vol)
  volumes they use, and the plugin will determine whether the filer serving the
  mount point is overloaded or not, based on the filer's cpu busy for 
  non-exempt domains, maximum disk busy, volume average latency. It will
  keep jobs pending in the LSF queue if it's determined that these 
  criteria will not be met, thus avoiding the condition where a filer 
  becomes a bottleneck in running jobs.
   

o) Pre-requisites

  In order to successfully install and configure the plugin, the 
  following pre-requisites should be true:

  . LSF must be installed and running properly. 

  . A compiler must be available on a machine that is of the 
    same architecture as the LSF master host(s).

  . Data Fabric Manager (DFM) must be installed and configured properly 
    to manage the filers that are exporting the volumes that need to be 
    monitored for load.  It is important that http be enabled on the filers
    in order to communicate with the filer via DFM and NetApp API (NMSDK). On
    filer check http by doing "options http".  The options httpd.admin.enable
    and httpd.enable should be set to "on". One can test this by doing 
    "dfm diag <IP or filername>".  The HTTP test should not fail and 
    should indicate an output like below for HTTP:
        HTTP                   Passed (1 ms)  

  . Download and install the latest NetApp Manageability Software Development 
    Kit (NMSDK) from NetApp developer community:
    	https://communities.netapp.com/docs/DOC-1152

  . Python version 2.6.6 or later should be installed.

o) Components.   

  The package consists of the following components:

  . schmod_netapp.so - the scheduling plugin implementing 
    the job scheduling policy. Provided as a set of C source
    files that must be compiled.

  . ntapplugin.conf - the plugin configuration file. This file 
    must be edited by the LSF administrator to configure storagemaps,
    and filers to be monitored as well as thresholds and directoy locations.

  . ontapmon.py - this is the NetApp provided script that retrieves filer
    and volume load information from DFM.  

  . config.ini - configuration file for the ontapmon.py perl script. This
    file must be edited by the LSF administrator to configure DFM (host,
    root, passwd, etc) information needed by the ontapmon.py.

o) Building the plugin. 

   . The plugin must be built on a machine of the same LSF
     host type as the LSF master (e.g. build on the LSF master).

   . Change to the directory containing the plugin source distribution.

   . Edit the Makefile and modify the CFLAGS variable so it points 
     to where the LSF include files are:

       CFLAGS = ... -I/path/to/lsf/8.0/include/lsf ...
   
     leaving the other elements of CFLAGS untouched.

   . Run 'make'. This will build the plugin library schmod_netapp.so.


o) Configure the system. 

   First configure LSF to enable the plugin:

   . Make sure you are in the plugin source directory where you 
     built the plugin in the previous steps. 

   . Source the LSF configuration scripts profile.lsf or cshrc.lsf
     from a root shell on the LSF master.

      bash> . /path/to/lsf/conf/profile.lsf        [sh or bash]
      
      tcsh$ source /path/to/lsf/conf/cshrc.lsf     [csh or tcsh]

   . Copy schmod_netapp.so to $LSF_LIBDIR

   . Edit the $LSF_ENVDIR/lsf.conf file and add the following line
     to the end of the file:

       LSF_ENABLE_EXTSCHEDULER=y 

   . Edit the $LSF_ENVDIR/lsbatch/<your clustername>/configdir/lsb.modules 
     and tell LSF to load the plugin by adding 'schmod_netapp' to the 
     end of the list of modules:
       
     Being PluginModule
       ...
       schmod_netapp      ()      ()
     End PluginModule

   Then configure the plugin itself:

   . Copy the ntapplugin.conf file from the 'misc' directory 
     to $LSF_ENVDIR, which is where the plugin will look for it.

   . Determine a plugin working directory where the log files and 
     the plugin's counter XML files are kept. The Work_Dir directory 
     can be anywhere accessible by the LSF master, including on NFS. 
     The Counter_Dir should be the same location specified in DIRLOC in
     the config.ini file that is used by the (ontapmon.py) ONTAP monitoring
     python script.  Edit the ntapplugin.conf file and define the 
     working directory, counter directory, 
     XML_Reread and debug level in the Begin/End Parameters section:

     Begin Parameters
       Debug yes
       Work_Dir /some/path/netapp-log
       Counter_Dir  /same/path/as/DIRLOC
       XML_Reread 5
       DryRunMode yes
     End Parameters
   
     Descriptions of these parameters are as follows:
	. Debug can be set to 'yes' or 'no' to enable and disable debug msgs.
	. Work_Dir is location of where the log file is placed in.  
	  NOTE: Work_Dir needs to exist and the LSF admin (lsfadmin) should 
	  have write permission to this directory.  If the directory does not
	  exist, the log file (ntappluging.log) is created in /tmp.
	. Counter_Dir is location of the counter XML files (filername.xml).  
	  Should be the same location defined in config.ini file. Directory 
	  needs to exist.
	. XMLReread indicates the number in seconds of when to re-read the 
	  counter XML files to refresh the XML data-cache in schmod_netapp.so.
	. DryRunMode can be set to 'yes' or 'no' to enable and disable dry
	  run mode.

   . Create the Work_Dir from the previous step, 
     and make sure it is owned by the LSF admin user 
     (e.g. chown lsfadmin /some/path/netapp-work).

   . Create the Counter_Dir from the previous step, 
     and make sure it is owned by the root.
     (e.g. chown root/same/path/as/DIRLOC).

   . Edit the $LSF_ENVDIR/ntapplugin.conf and add your filers and volume
     info in the Begin/End ExportNames section and the policy thresholds
     in the Begin/End PluginPolicy section and teh filer and volume specific
     thresholds in Begin/End FilerPolicy. Follow the format shown in the
     following examples.  
     
     The format for the Begin/End ExportNames is
     as follows:
          Begin ExportNames
     	  test1	fas6280c-svl11:/vol/volTest,fas6280c-svl11:/vol/lsfvol
	  test2 fas6280-svl12:/vol/nfsDS	
	  End ExportNames

     NOTE: Multiple filer volumes can be specified and must be separated by ","
     Also, IP Addresses of filers are not allowed only host filer names.

     There are three ways to specify the thresholds policies: volume specific, 
     filer specific or global.  To specify global thresholds define them in 
     the following format:
     
	 Begin PluginPolicy
	 Max_DiskBusy  =	50
	 Max_NEDomain	=	55
	 Max_AvgVolLatency =	30
	 Min_AvailFiles	=	1000
	 Min_AvailSize =	1000
	 End PluginPolicy

     For Filer and Volume Specific policies define them in the following format:
     	 Begin FilerPolicy
	 fas6280c-svl11:/vol/volTest	Min_AvailFiles = 1000
	 fas6280c-svl11:/vol/nfsDS	Min_AvailSize =	 1000
	 fas6280c-svl11:/vol/nfsDS	Max_AvgVolLatency = 10
	 fas6280c-svl11			Max_DiskBusy = 50
	 End FilerPolicy

     For global, volume, and filer threshold policies the following can 
     be defined:
     	 Max_Disk_Busy - maximum % disk busy 
	 Max_NEDomain -  maximum % non exempt domain busy (raid, target,
	 	      kahuna, storage, nwk_legacy, cifs)
	 Max_AvgVolLatency - maximum average volume latency (ms)
	 Min_AvailFiles - mininum available files required to run job.
	 Min_AvailSize - minimum available size required to run job in MB. 

     Policies that are not defined, will not be checked.  The order of 
     precedence of checking are as follows:  
     	 1) volume specific
	 2) filer specific  
	 3) global

     For instance, if volume specific policies are defined, then it will
     compare values with volume specific threshold policies and ignore other
     policies defined. 
	 
   . Edit the config.ini file from the 'misc' and set the parameters
     corresponding to your DFM configuration.  Description of these parameters
     are as follows:
     	 . NMDKDIR - location of where netapp-manageability-sdk-5.0 or later is 
	   installed.
	 . HOST - IP or name of host running DFM.
	 . USER - user (usually root) who can log on to DFM - dfm admin or root
	 . PASSWD - DFM password
	 . INTERVAL - interval (sample rate) to collect filer 
	   information being managed by DFM in seconds.
	 . DIRLOC - location of where to place XML and error logs.
	 . NTHREADS - number of threads to create to run performance 
	   monitoring.
	 . REFRESH - indicates the number of times to run with current 
	   filer list before refreshing list.

o) Reconfigure LSF from the master host.

   . lsadmin limrestart
   . badmin mbdrestart

o) Verify that all Plugin is working

   . Check the error logs for errors.  Correct errors if necessary.
      <lsfinstalldir>/share/lsf/log/mbschd.log.<lsfhostname> 
   . Check for errors or inconsistencies in the ntapplugin.conf file which 
     will be logged in ntapplugin.log file specified in the Work_Dir.
     With debug turned on, ntapplugin will contain messages about
     scheduling decisions (i.e. a job is kept pending, or is dispatched).

o) Usage.

   The ontapmon.py script should be run first to generate the XML files
   in specified directory defined by DIRLOC (or Counter_Dir) prior to submitting
   job that is using the NetApp plugin. This script collects information
   relating to each of the filers managed by the DFM and stores counter 
   of these filers in XML files.  As ROOT, start the script and run in 
   the background. 
   
     python ontapmon.py config.ini &
   
   NOTE: To stop the ontapmon.py script, please use the kill command. 
   For example, grep for python and then do a kill -9 process:
   # ps -ef | grep python
   root   10174 62231  7 16:59 pts/3    00:00:00 python ontapmon.py config.ini
   # kill -9 10174
   
   To check if the script is working properly, check for the
   existence of *.xml files and the script log file (ontapmon_error.log) 
   in the DIRLOC specified in config.ini.  It is expected that the filers 
   being monitoried by DFM will have an associated XML file in this directory.

   The plugin is activated for a job by using the bsub '-extsched' 
   command-line option with the following syntax:

     bsub -extsched "filer[test1 test2 ...]" ...

   where test1, test2, etc are the storage maps (list of filers:vols defined
   in ExportNames in ntapplugin.conf file) that will be used by this job. 
   At least one mount point must be listed,
   with multiple mount points being separated by spaces within the brackets.

   A job will be kept pending if the cpu utilization, maximum disk busy, 
   average volume latency, etc of the filer:/vol goes above the 
   threshold defined in ntapplugin.conf. If multiple filer:vol 
   volumes are specified, then the job will pend if ANY of the filer:vol 
   cross the thresholds.

   One can specify a "-n" option to do a dryrun of job. With "-n" option, 
   one can simulate a test run of job to see if filer can handle the load 
   or not for specified job. To specify "-n" option, place within the ""
   as follows:

	bsub -extsched "-n filer[test1 ..]" ...

   OR, DryRunMode can be set in the ntapplugin.conf file to yes to enable.
   NOTE: Any changes to ntapplugin.conf would require a restart of the batch
   admin.  Thus, execute the following:

        badmin mbdrestart

*) Notes.

   . Errors or inconsistencies in the ntapplugin.conf file will be 
     logged in ntapplugin.log file in the Work_Dir.

   . With debug turned on, ntapplugin will contain messages about
     scheduling decisions (i.e. a job is kept pending, or is dispatched).

   . A simple way to disable the plugin without reversing all the 
     configuration described above would be to  edit the 
     $LSF_ENVDIR/lsbatch/<your clustername>/configdir/lsb.modules 
     comment out schmod_netapp by placing "#" in front of it.
       
     Being PluginModule
       ...
     #schmod_netapp      ()      ()
     End PluginModule

*) Known Issues
   
   . For ontapmon.py, NMSDK for DFM tends to return bogus XML information 
     at times, and thus there will be errors in the log file and no counter 
     information will be retrieved or processed.  Ignore these messages
     in the log.  The script will catch issue and self correct after REFRESH.

#!/usr/bin/python26

#################################################################
#                                                               #
# Copyright (c) 2013 NetApp, Inc. All rights reserved.          #
# Specifications subject to change without notice.              #
#                                                               #
# netapp_lsf_hot_job_detector.py - Python script that monitors	#
#		the ONTAP performance XML files written by the NetApp	#
#		ontapmon.py performance monitoring script. Performance	#
#		data in these files is compared against thresholds		#
#		set in this script's configuration file.				#
#																#
#		When a performance problem is found, this script will	#
#		search the LSF job report files written by the NetApp	#
#		LSF compute agent ELIM script to determine which LSF	#
#		jobs have performed the most recent operations against	#
#		the impacted controller and/or volume.					#
#																#
#		A report listing the performance problems and			#
#		associated LSF jobs is generated, and this report file	#
#		is passed as an	argument to a configurable command		#
#		this script will run. By default, a Python script is	#
#		provided that will send an email with the report data.	#
#																#
#		Reads a configuration file named						#
#		"netapp_lsf_hot_job_detector_agent.conf" from the same	#
#		directory as this script.								#
#                                                               #
#################################################################



import subprocess, re, logging, logging.handlers, sys, os, time, platform, socket, glob, time, operator
from ConfigParser import ConfigParser
from threading import Timer, Thread
from xml.etree import ElementTree

# Initialize the logger for this script. Outputs to the /var/log directory.
logger = logging.getLogger('netapp_lsf_hot_job_detector')
handler = logging.handlers.TimedRotatingFileHandler('/var/log/netapp_lsf_hot_job_detector.log', when='midnight', interval=1, backupCount=7)
#handler = logging.handlers.TimedRotatingFileHandler('netapp_lsf_hot_job_detector.log', when='midnight', interval=1, backupCount=7)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)




# Class to store thresholds for a specific target (global defaults,
# per-filer, or per-volume).
class Thresholds(object):
	def __init__(self):
		self.maxDiskBusy		= None
		self.maxNEDomain		= None
		self.maxAvgVolLatency	= None
		self.minAvailFiles		= None
		self.minAvailSize		= None



# Class to store the number of different types of NFS operations for a
# given process.
class OperationCounter(object):
	def __init__(self):
		self.operations = {}
		self.operations['RD'] = 0
		self.operations['WR'] = 0
		
	def getTotalOperations(self):
		total = 0
		for operation in self.operations:
			total += self.operations[operation]
		
		return total
		
	def addOperationCounter(self, operationCounterObject):
		if operationCounterObject is None:
			return self
		
		if not isinstance(operationCounterObject, OperationCounter):
			raise ValueError('Invalid object passed to addOperationCounter. Expected an instance of OperationCounter.')
		
		for operation in self.operations:
			self.operations[operation] += operationCounterObject.operations[operation]
			
		return self
		
	def __str__(self):
		return str(self.operations)
		
	def __repr__(self):
		return repr(self.operations)
		
	@staticmethod
	def compareTotalOperations(oc1, oc2):
		return oc1.getTotalOperations() - oc2.getTotalOperations()
		
		
		
# Class to store data for a parsed job report file, including a map of
# the NFS operations performed, LSF job number, and LSF cluster name of
# the job.
class JobReport(object):
	def __init__(self, jobNumber, lsfClusterName, operationData):
		self.jobNumber = jobNumber
		self.lsfClusterName = lsfClusterName
		self.operationData = operationData
		
	def __repr__(self):
		return ('Job number:  %s      Cluster:  %s' % (self.jobNumber, self.lsfClusterName))



# Stores data for a storage performance error object (filer, aggregate,
# or volume). Data includes a list of performance error messages for
# the object and a list of jobs that performed operations on the
# object.
class PerformanceErrorObjectData(object):
	def __init__(self):
		self.errorMessages = []
		self.affectingJobs = []
		self.sortedAffectingJobs = None
	
	def addErrorMessage(self, errorMessage):
		self.errorMessages.append(errorMessage)
		
	def addAffectingJob(self, job):
		self.affectingJobs.append(job)
		
	def getErrorMessages(self):
		return self.errorMessages
		
	def getAffectingJobs(self):
		return self.affectingJobs
		
	def getSortedAffectingJobs(self):
		return self.sortedAffectingJobs
		

# Stores information about filers with performance problems.
class PerformanceErrorDocument(object):
	def __init__(self, filerName):
		self.filerName = filerName
		
		# Filer-level performance problems (e.g. system average latency)
		self.filerErrorObject = PerformanceErrorObjectData()
		
		# Volume-level performance problems (e.g. volume latency)
		self.volumeErrorListMap = {}
		
		# Aggregate-level performance problems (e.g. disk busy)
		self.aggregateErrorListMap = {}
		
	def addFilerError(self, errorMessage):
		self.filerErrorObject.addErrorMessage(errorMessage)
		
	def addAggregateError(self, aggregate, errorMessage):
		if aggregate not in self.aggregateErrorListMap:
			self.aggregateErrorListMap[aggregate] = PerformanceErrorObjectData()
		
		self.aggregateErrorListMap[aggregate].addErrorMessage(errorMessage)
		
	def addVolumeError(self, volume, errorMessage):
		if volume not in self.volumeErrorListMap:
			self.volumeErrorListMap[volume] = PerformanceErrorObjectData()
		
		self.volumeErrorListMap[volume].addErrorMessage(errorMessage)
		
	def getErrorObjects(self):
		# Concatanate the filer, volume, and aggregate error messages into one list.
		allErrorObjects = []
		
		allErrorObjects.extend(self.filerErrorObject)
		allErrorObjects.extend(self.volumeErrorListMap.values())
		allErrorObjects.extend(self.aggregateErrorListMap.values())
		
		return allErrorObjects
		
	def getFilerLevelErrorObject(self):
		return self.filerErrorObject
		
	def getAggregateLevelErrorObjects(self):
		return self.aggregateErrorListMap.values()
		
	def getVolumeLevelErrorObjects(self):
		return self.volumeErrorListMap.values()
		
	def getAffectedAggregates(self):
		return self.aggregateErrorListMap.keys()
		
	def getAffectedVolumes(self):
		return self.volumeErrorListMap.keys()
		
	def getAggregateErrorObjectMap(self):
		return self.aggregateErrorListMap
		
	def getVolumeErrorObjectMap(self):
		return self.volumeErrorListMap
		
	def clear(self):
		self.filerErrorObject = PerformanceErrorObjectData()
		self.volumeErrorListMap.clear()
		self.aggregateErrorListMap.clear()
		

# Manages the list of filer error documents and provides an interface
# for logging performance error messages.
class PerformanceErrorDocumentManager(object):
	def __init__(self):
		self.errorDocuments = {}
		
	# Returns the current number of controllers with performance errors.
	def getNumFilersWithErrors(self):
		return len(self.errorDocuments)
	
	# Returns a list of the names of the controllers with performance errors.
	def getFilersWithErrors(self):
		return self.errorDocuments.keys()
		
	# Returns a list of the stored error documents.
	def getErrorDocuments(self):
		return self.errorDocuments.values()
		
	# Returns the error document object for a specific filer, or None
	# if no error document exists for the filer.
	def getErrorDocumentForFiler(self, filer):
		if filer in self.errorDocuments:
			return self.errorDocuments[filer]
		else:
			return None
		
	# Log a performance error message.
	def logError(self, filerName, errorMessage, volume=None, aggregate=None):
		# Create an empty error document object for this filer if this
		# is the first error message for it.
		if filerName not in self.errorDocuments:
			self.errorDocuments[filerName] = PerformanceErrorDocument(filerName)
		
		if volume is not None:
			self.errorDocuments[filerName].addVolumeError(volume, errorMessage)
		elif aggregate is not None:
			self.errorDocuments[filerName].addAggregateError(aggregate, errorMessage)
		else:
			self.errorDocuments[filerName].addFilerError(errorMessage)
		
	# Log a volume average latency exceeded error message.
	def logVolumeAverageLatencyError(self, filerName, volumeName, aggregateName, thresholdValue, actualValue):
		# Construct the error message.
		errorMessage = 'Volume %s in aggregate %s has exceeded the threshold for acceptable average volume latency. Threshold: %.2f, Value: %.2f.' \
			% (volumeName, aggregateName, thresholdValue, actualValue)

		self.logError(filerName, errorMessage, volume=volumeName)
		
	# Log a volume average latency exceeded error message.
	def logDiskBusyError(self, filerName, aggregateName, thresholdValue, actualValue):
		# Construct the error message.
		errorMessage = 'Aggregate %s has a disk that has exceeded the threshold for acceptable maximum disk busy. Threshold: %.2f, Value: %.2f.' \
			% (aggregateName, thresholdValue, actualValue)

		self.logError(filerName, errorMessage, aggregate=aggregateName)
		
	# Log a maximum non-exempt CPU domain utilization error message.
	def logNonExemptCPUDomainUtilizationError(self, filerName, domainName, thresholdValue, actualValue):
		# Construct the error message.
		errorMessage = 'Non-exempt CPU domain %s has exceeded the threshold for acceptable maximum non-exempt CPU domain utilization. Threshold: %.2f, Value: %.2f.' \
			% (domainName, thresholdValue, actualValue)

		self.logError(filerName, errorMessage)
		
	# Log a volume minimum available files error message.
	def logVolumeMinAvailFilesError(self, filerName, volumeName, aggregateName, thresholdValue, actualValue):
		# Construct the error message.
		errorMessage = 'Volume %s in aggregate %s has too few available files. Threshold: %d, Value: %d.' \
			% (volumeName, aggregateName, thresholdValue, actualValue)

		self.logError(filerName, errorMessage, volume=volumeName)
		
	# Log a volume minimum available size error message.
	def logVolumeMinAvailSizeError(self, filerName, volumeName, aggregateName, thresholdValue, actualValue):
		# Construct the error message.
		errorMessage = 'Volume %s in aggregate %s has too little available space. Threshold: %.2f MB, Value: %.2f MB.' \
			% (volumeName, aggregateName, thresholdValue, actualValue)

		self.logError(filerName, errorMessage, volume=volumeName)
	
	# Clears all stored error documents.
	def clear(self):
		self.errorDocuments.clear()



# Main class. Contains methods to monitor performance XML data and
# process results.
class HotJobDetector(object):
	def __init__(self):
		# Configuration file properties for this script.
		self.properties = {}
		
		# File modification time tracker to prevent unnecessary rereads
		# of an unchanged performance data file.
		self.filesLastModified = {}
		
		# Stores all of the performance errors and LSF jobs contributing
		# to the performance errors. Provides an interface for processing
		# them on a per-filer/volume/aggregate level.
		self.performanceErrorDocumentManager = PerformanceErrorDocumentManager()
		
		# Dictionary to keep track of the containing aggregate of volumes
		# as we read through the performance XML files. It is necessary
		# to know the aggregate in case there is an aggregate-level
		# performance problem (like max disk busy) so we can find the
		# jobs targetting the aggregate's volumes.
		self.volumeToContainingAggregateMap = {}
		
		# Dictionary to store the IP addresses of each filer. This is
		# necessary as LSF job data may be logged with an IP address
		# while performance data is usually logged with the filer name.
		self.filerIPToFilerNameMap = {}
		
		# Global thresholds object. These thresholds are read from the
		# configuration file and apply by default if no threshold is set
		# for the specific filer and volume being looked at.
		self.globalThresholds = Thresholds()
		
		# Dictionary to keep track of the per-filer and per-volume
		# thresholds read from the configuration file. These thresholds
		# have the highest precedence if one is set for the specific
		# filer or volume being looked at.
		self.targetThresholds = {}
		
		# Read the configuration file to set properties and thresholds
		# for this script.
		scriptDir = os.path.dirname(os.path.realpath(__file__))
		configurationFilePath = scriptDir + os.sep + 'netapp_lsf_hot_job_detector.conf'
		self.readConfigurationFile(configurationFilePath)
		
		
	# The main "run" method for this class. Begins periodically reading
	# performance XML files outputted by the ONTAP performance monitoring
	# script and invoking the alert system if a controller is overloaded.
	def run(self):
		self.monitorPerformanceData()
		
	
	def monitorPerformanceData(self):
		# Get the list of files in the directory containing the
		# performance data XML files.
		xmlDataDirectory = self.properties['ontap_xml_data_directory']
		if not xmlDataDirectory.endswith(os.sep):
			xmlDataDirectory += os.sep
		
		# Get the interval time (time to sleep between iterations).
		sleepTime = self.properties['file_check_interval']
		sleepTime = int(sleepTime)
			
		while True:
			# Get the list of files in the XML Data directory.
			files = os.listdir(xmlDataDirectory)
			
			filesToCheck = []
			filesUpToDateCount = 0
			
			# Clear out the performance manager object.
			self.performanceErrorDocumentManager = PerformanceErrorDocumentManager()
			
			for filename in files:
				if filename.endswith('.xml'):
					# Check to see if this file has been modified (updated)
					# since the last time this script read it.
					filepath = xmlDataDirectory + filename
					lastModifiedTime = os.path.getmtime(filepath)
					
					if filename in self.filesLastModified:
						modifiedTimeWhenLastRead = self.filesLastModified[filename]
						
						if lastModifiedTime != modifiedTimeWhenLastRead:
							# This file has been modified since the last
							# time it was read. Add it to the list of
							# files that need to be read.
							filesToCheck.append(filepath)
							self.filesLastModified[filename] = lastModifiedTime
						else:
							logger.debug('File %s has not been updated since last run. Skipping file.' % (filename))
							filesUpToDateCount += 1
					else:
						# This is the first time we're reading this XML file.
						filesToCheck.append(filepath)
						self.filesLastModified[filename] = lastModifiedTime
			
			# Make sure we found at least one XML file.
			if (len(filesToCheck) + filesUpToDateCount) < 1:
				logger.warning('No XML files found in directory %s. Cannot find performance problems.' % (xmlDataDirectory))
			else:
				logger.info('Reading %d files. Skipping %d up-to-date files.' % (len(filesToCheck), filesUpToDateCount))
				self.checkFiles(filesToCheck)
				
				if self.performanceErrorDocumentManager.getNumFilersWithErrors() > 0:
					filersWithErrors = self.performanceErrorDocumentManager.getFilersWithErrors()
					logger.info('Found performance problems on the following controllers: %s' % (', '.join(filersWithErrors)))
					
					# Read the LSF job report files to locate jobs that
					# are targetting the busy filer(s).
					errorDocuments = self.performanceErrorDocumentManager.getErrorDocuments()
					self.findAffectingJobs(errorDocuments)
					self.findTopJobs(errorDocuments)
					report = self.generateReport(errorDocuments)
					
					logger.info('Created performance report:\n%s' % (report))
					
					# Call the script that processes the report. By
					# default, this is an email script 
					self.processReport(report)
				else:
					logger.info('Found no performance problems.')
			
			logger.info('Done processing files. Sleeping for %d seconds.' % (sleepTime))
			
			time.sleep(sleepTime)
			
	
	
	# Prints the text report to a file and then calls a script, passing
	# the path to the report file as an argument. If the property is set,
	# this script will wait for the called script to complete and then
	# attempt to delete the file. Otherwise, the report file will be left
	# for either the called script or an administrator to store or delete.
	def processReport(self, report):
		if report is None or len(report) < 1:
			return
		
		# Read the properties for the script call operation.
		scriptToCallRaw = self.properties['command_to_run']
		scriptToCall = scriptToCallRaw.split()
		shouldDeleteFileRaw = self.properties['delete_report_after_command']
		shouldDeleteFile = shouldDeleteFileRaw in ['true', 'True', 'yes', 'Yes', '1']
		reportDirectory = self.properties['hot_job_report_directory']
		if not reportDirectory.endswith(os.sep):
			reportDirectory += os.sep
		
		# Write the report to a file.
		# Get a human-readable timestamp to name the file with.
		timestamp = time.strftime('%Y-%m-%d_%H.%M.%S', time.localtime())
		reportFileName = 'NetApp_LSF_Hot_Job_Detector_Report_-_%s.txt' % (timestamp)
		reportFilePath = reportDirectory + reportFileName
		
		controllerSeparator = '**********'
		
		try:
			f = open(reportFilePath, 'w')
			
			for controllerReport in report:
				f.write(controllerSeparator + '\n')
				f.write(controllerReport)
				f.write(controllerSeparator + '\n')
				f.write('\n\n\n')
		except IOError as e:
			logger.error('Encountered I/O error %d trying to write performance report file %s. Error was: %s' % (e.errno, reportFilePath, e.strerror))
			
		
		# Call the report-processing script.
		class ScriptCallThread(Thread):
			def __init__(self, scriptAndArguments, reportFilePath, deleteReportFile):
				super(ScriptCallThread, self).__init__()
				self.scriptAndArguments = scriptAndArguments
				self.reportFilePath = reportFilePath
				self.deleteReportFile = deleteReportFile
				
			def run(self):
				self.scriptAndArguments.append(self.reportFilePath)
				
				logger.info('Calling script: %s' % (' '.join(self.scriptAndArguments)))
				try:
					status = subprocess.check_call(self.scriptAndArguments)
					if status == 0:
						logger.info('Script completed successfully with status %d.' % (status))
					else:
						logger.warning('Script returned non-zero exit status %d.' % (status))
				except subprocess.CalledProcessError as e:
					logger.error('Encountered an error calling script: %s' % (str(e)))
				
				# Delete the report file after the script has completed,
				# if desired.
				if self.deleteReportFile:
					try:
						os.remove(self.reportFilePath)
						logger.info('Deleted report file %s.' % (self.reportFilePath))
					except OSError as e:
						# Check to see if the delete operation failed
						# because the report file doesn't exist. If
						# that's the case, the called script probably
						# handled the file and we can ignore the error.
						if e.errno != errno.ENOENT:
							logger.error('Failed to delete LSF report file %s: %s' % (self.reportfilePath, e.strerror))
							
			
		scriptCallThread = ScriptCallThread(scriptToCall, reportFilePath, shouldDeleteFile)
		scriptCallThread.start()
			
		
	
	# Iterates through each error object, reading the already-stored
	# list of jobs contributing to the error condition and storing
	# a list of jobs sorted by operation count in the error object so
	# that the top jobs can be processed later.
	def findTopJobs(self, errorDocuments):
		for errorDocument in errorDocuments:
			filerName = errorDocument.filerName
			
			# If there are any filer-level errors, find the jobs that
			# performed the most operations against that filer.
			filerLevelErrorObject = errorDocument.getFilerLevelErrorObject()
			affectingJobs = filerLevelErrorObject.getAffectingJobs()
			topFilerLevelJobs = self.sortTopJobs(affectingJobs, filerName)
			filerLevelErrorObject.sortedAffectingJobs = topFilerLevelJobs
			
			# If there are any volume-level errors, find the jobs that
			# performed the most operations against each volume.
			volumeLevelErrorMap = errorDocument.getVolumeErrorObjectMap()
			for volumeName in volumeLevelErrorMap:
				volumeLevelErrorObject = volumeLevelErrorMap[volumeName]
				affectingJobs = volumeLevelErrorObject.getAffectingJobs()
				topVolumeLevelJobs = self.sortTopJobs(affectingJobs, filerName, volumeName=volumeName)
				volumeLevelErrorObject.sortedAffectingJobs = topVolumeLevelJobs
				
			# If there are any agregate-level errors, find the jobs that
			# performed the most operations against each aggregate.
			aggregateLevelErrorMap = errorDocument.getAggregateErrorObjectMap()
			for aggregateName in aggregateLevelErrorMap:
				aggregateLevelErrorObject = aggregateLevelErrorMap[aggregateName]
				affectingJobs = aggregateLevelErrorObject.getAffectingJobs()
				topAggregateLevelJobs = self.sortTopJobs(affectingJobs, filerName, aggregateName=aggregateName)
				aggregateLevelErrorObject.sortedAffectingJobs = topAggregateLevelJobs
				
				
	# Iterates through the passed-in list of jobs to sort and find
	# those that performed the most operations against the passed-in
	# target (filer, volume, or aggregate). Returns a sorted list of
	# tuples of the form (JobReport, total_relevant_operations).
	def sortTopJobs(self, affectingJobs, filerName, volumeName=None, aggregateName=None):
		jobToOperationCountMap = {}
		
		errorDocument = self.performanceErrorDocumentManager.getErrorDocumentForFiler(filerName)
		
		if volumeName is None and aggregateName is None:
			# Filer-level search - count any operations that occurred
			# on the filer.
			for job in affectingJobs:
				operationData = job.operationData
				for controllerAndVolume in operationData:
					controller, volume = controllerAndVolume.split(':')
					if controller == errorDocument.filerName:
						operationCounterObject = operationData[controllerAndVolume]
						
						if job not in jobToOperationCountMap:
							jobToOperationCountMap[job] = OperationCounter()
						
						# Add the operations the running total for this job.
						jobToOperationCountMap[job].addOperationCounter(operationCounterObject)
						
		elif volumeName is not None:
			# Volume-level search - count any operations that occurred
			# on the specified volume.
			for job in affectingJobs:
				operationData = job.operationData
				for controllerAndVolume in operationData:
					controller, volume = controllerAndVolume.split(':')
					if controller == errorDocument.filerName and volume == volumeName:
						operationCounterObject = operationData[controllerAndVolume]
						
						if job not in jobToOperationCountMap:
							jobToOperationCountMap[job] = OperationCounter()
						
						# Add the operations the running total for this job.
						jobToOperationCountMap[job].addOperationCounter(operationCounterObject)
						
		elif aggregateName is not None:
			# Aggregate-level search - count any operations that occurred
			# on a volume contained in the specified aggregate.
			for job in affectingJobs:
				operationData = job.operationData
				
				for controllerAndVolume in operationData:
					# Look-up the contianing aggregate for this volume.
					if controllerAndVolume not in self.volumeToContainingAggregateMap:
						# A warning for being unable to look-up the
						# aggregate name is logged elsewhere. Just
						# skip this volume.
						continue
					
					containingAggregate = self.volumeToContainingAggregateMap[controllerAndVolume]
					controller, volume = controllerAndVolume.split(':')
					
					if controller == errorDocument.filerName and containingAggregate == aggregateName:
						operationCounterObject = operationData[controllerAndVolume]
						
						if job not in jobToOperationCountMap:
							jobToOperationCountMap[job] = OperationCounter()
						
						# Add the operations the running total for this job.
						jobToOperationCountMap[job].addOperationCounter(operationCounterObject)
						
		# Sort the job --> operation_count map by value to find
		# the top jobs.
		topAffectingJobs = sorted(jobToOperationCountMap.iteritems(), key=operator.itemgetter(1), cmp=OperationCounter.compareTotalOperations, reverse=True)
		return topAffectingJobs
		
		
	# Iterates through all of the detected performance problems and
	# finds LSF jobs that have recently performed operations on
	# the busy storage object. These busy jobs are stored in a
	# list with the performance object.
	def findAffectingJobs(self, errorDocuments):
		consolidatedJobReports = self.readAndConsolidateAllJobReports()
		
		logger.debug('Read job reports: %s' % (consolidatedJobReports))
				
		# Iterate through the objects (filers, aggregates, and volumes)
		# with performance problems, checking each consolidated job
		# report to see if that job performed operations on the
		# affected object.
		problemFilerToJobsMap = {}
		problemAggregateToJobsMap = {}
		problemVolumeToJobsMap = {}
		
		for jobReport in consolidatedJobReports:
			lsfJobNumber = jobReport.jobNumber
			lsfClusterName = jobReport.lsfClusterName
			operationData = jobReport.operationData
			
			# Check to see if this job performed operations on an
			# affected target (filer, aggregate, or volume). The
			# operation data is keyed by <filer:volume> and maps
			# to an OperationCounter object for that volume.
			for filerAndVolume in operationData:
				filerName, volume = filerAndVolume.split(':')
				
				logger.debug('Checking job report line on filer %s and volume %s.' % (filerName, volume))
				
				containingAggregate = None
				if filerAndVolume not in self.volumeToContainingAggregateMap:
					logger.warning('Unable to determine containing aggregate of volume %s.' % ((filerName + ':/vol/' + volume)))
				else:
					containingAggregate = self.volumeToContainingAggregateMap[filerAndVolume]
					
				# Check the error documents to see if this job has affected
				# any overloaded controllers, aggregates, or volumes.
				for errorDocument in errorDocuments:
					errorFilerName = errorDocument.filerName
					
					if filerName == errorFilerName:
						# This is a busy filer due to a filer, aggregate,
						# or volume-level threshold being exceeded. Check
						# to see if this job performed operations on the
						# actual busy object.
						
						# If there is a filer-level performance problem,
						# any operations performed on any volume contributed.
						# Flag this job if there are any filer-level problems.
						filerLevelErrorObject = errorDocument.getFilerLevelErrorObject()
						if len(filerLevelErrorObject.getErrorMessages()) > 0:
							filerLevelErrorObject.addAffectingJob(jobReport)
						
						if containingAggregate is not None:
							aggregateErrorObjectMap = errorDocument.getAggregateErrorObjectMap()
							if containingAggregate in aggregateErrorObjectMap:
								# This job performed operations on a volume
								# in a busy aggregate. Flag it.
								aggregateErrorObjectMap[containingAggregate].addAffectingJob(jobReport)
								
						volumeErrorObjectMap = errorDocument.getVolumeErrorObjectMap()
						logger.debug('Volume: %s         volumeErrorMap: %s' % (volume, volumeErrorObjectMap))
						if volume in volumeErrorObjectMap:
							# This job performed operations on a volume
							# in a busy aggregate. Flag it.
							volumeErrorObjectMap[volume].addAffectingJob(jobReport)
							logger.debug('Added affecting job: %s' % (jobReport))
	
	
	# Checks to see if two filers, given by either name or IP, are the
	# same filer. Looks up filer name from an IP address in the class
	# dictionary if necessary.
	def isSameFiler(self, filer1, filer2):
		if filer1 == filer2:
			return True
		else:
			filer1NameLookup = None
			filer2NameLookup = None
			if filer1 in self.filerIPToFilerNameMap:
				filer1NameLookup = self.filerIPToNameMap[filer1]
			if filer2 in self.filerIPToFilerNameMap:
				filer2NameLookup = self.filerIPToNameMap[filer2]
				
			if filer1NameLookup is not None and filer2NameLookup is not None:
				return filer1NameLookup == filer2NameLokup
			elif filer1NameLookup is not None:
				return filer1NameLookup == filer2
			elif filer2NameLookup is not None:
				return filer2NameLookup == filer1
			else:
				return False

	# Generates a textual report detailing the storage performance issues
	# and the top jobs affecting the busy storage. The report is returned
	# in the form of a list of strings, each containing a formatted
	# report.
	def generateReport(self, errorDocuments):
		numTopJobsToReport = int(self.properties['num_top_jobs_to_report'])
		reportGroups = []
		
		for errorDocument in errorDocuments:
			filerName = errorDocument.filerName
			errorReport = 'Controller: %s\n' % (filerName)
			
			# Print the controller-level error messages.
			filerLevelErrorObject = errorDocument.getFilerLevelErrorObject()
			filerLevelErrorMessages = filerLevelErrorObject.getErrorMessages()
			for errorMessage in filerLevelErrorMessages:
				errorReport += '\t-%s\n' % (errorMessage)
			
			# Print out the top jobs affecting the controller.
			sortedAffectingJobs = filerLevelErrorObject.sortedAffectingJobs
			if sortedAffectingJobs is not None and len(sortedAffectingJobs) > 0:
				errorReport += '\n\tTop jobs operating on controller %s:\n' % (filerName)
				
				for i in range(min(numTopJobsToReport, len(sortedAffectingJobs))):
					job, operationCounter = sortedAffectingJobs[i]
					jobNumber = job.jobNumber
					lsfClusterName = job.lsfClusterName
					
					totalOperations = operationCounter.getTotalOperations()
					
					# Create a string that lists the different operations
					# performed with their operation counts.
					operationStrings = []
					for operation, value in operationCounter.operations.items():
						operationStrings.append('%s = %d' % (operation, value))
						
					operationBreakdownString = ', '.join(operationStrings)
					
					errorReport += '\t\t-LSF job number %s on cluster %s has performed %d recent operations on target (%s).\n' % (jobNumber, lsfClusterName, totalOperations, operationBreakdownString)
					
				errorReport += '\n\n'
			
			
			# Print out the volume-level error messages.
			volumeLevelErrorMap = errorDocument.getVolumeErrorObjectMap()
			for volumeName in volumeLevelErrorMap:
				volumeLevelErrorObject = volumeLevelErrorMap[volumeName]
				volumeErrorMessages = volumeLevelErrorObject.getErrorMessages()
				
				for errorMessage in volumeErrorMessages:
					errorReport += '\t-%s\n' % (errorMessage)
				
				# Print out the top jobs affecting this volume.
				sortedAffectingJobs = volumeLevelErrorObject.sortedAffectingJobs
				if sortedAffectingJobs is not None and len(sortedAffectingJobs) > 0:
					errorReport += '\n\tTop jobs operating on volume %s:\n' % ((filerName + ':/vol/' + volumeName))
					
					for i in range(min(numTopJobsToReport, len(sortedAffectingJobs))):
						job, operationCounter = sortedAffectingJobs[i]
						jobNumber = job.jobNumber
						lsfClusterName = job.lsfClusterName
						
						totalOperations = operationCounter.getTotalOperations()
						
						# Create a string that lists the different operations
						# performed with their operation counts.
						operationStrings = []
						for operation, value in operationCounter.operations.items():
							operationStrings.append('%s = %d' % (operation, value))
							
						operationBreakdownString = ', '.join(operationStrings)
						
						errorReport += '\t\t-LSF job number %s on cluster %s has performed %d recent operations on target (%s).\n' % (jobNumber, lsfClusterName, totalOperations, operationBreakdownString)
					
				errorReport += '\n'
			errorReport += '\n'
			
			
			# Print out the aggregate-level error messages.
			aggregateLevelErrorMap = errorDocument.getAggregateErrorObjectMap()
			for aggregateName in aggregateLevelErrorMap:
				aggregateLevelErrorObject = aggregateLevelErrorMap[aggregateName]
				aggregateErrorMessages = aggregateLevelErrorObject.getErrorMessages()
				
				for errorMessage in aggregateErrorMessages:
					errorReport += '\t-%s\n' % (errorMessage)
				
				# Print out the top jobs affecting this aggregate.
				sortedAffectingJobs = aggregateLevelErrorObject.sortedAffectingJobs
				if sortedAffectingJobs is not None and len(sortedAffectingJobs) > 0:
					errorReport += '\n\tTop jobs operating on aggregate %s:\n' % ((filerName + ':' + aggregateName))
					
					for i in range(min(numTopJobsToReport, len(sortedAffectingJobs))):
						job, operationCounter = sortedAffectingJobs[i]
						jobNumber = job.jobNumber
						lsfClusterName = job.lsfClusterName
						
						totalOperations = operationCounter.getTotalOperations()
						
						# Create a string that lists the different operations
						# performed with their operation counts.
						operationStrings = []
						for operation, value in operationCounter.operations.items():
							operationStrings.append('%s = %d' % (operation, value))
							
						operationBreakdownString = ', '.join(operationStrings)
						
						errorReport += '\t\t-LSF job number %s on cluster %s has performed %d recent operations on target (%s).\n' % (jobNumber, lsfClusterName, totalOperations, operationBreakdownString)
					
				errorReport += '\n'
			
			# Add the constructed error report for the performance
			# problems on this controller to this list.
			reportGroups.append(errorReport)
			
		return reportGroups
	
		
	# Reads all job files in the LSF job report directory modified
	# recently. Consolidates the recent operations of all the
	# recently modified job reports and returns them in a list of
	# tuples in the form (LSF job number, LSF cluster name,
	# OperationCounter object).
	def readAndConsolidateAllJobReports(self):
		# List the files in the LSF job report directory. We need only
		# be concerned with job reports modified in the last several
		# minutes, as we're only looking for jobs that may have
		# contributed to the current performance problems.
		lsfJobReportDirectory = self.properties['lsf_job_report_directory']
		if not lsfJobReportDirectory.endswith(os.sep):
			lsfJobReportDirectory += os.sep
		jobReportFiles = filter(os.path.isfile, glob.glob(lsfJobReportDirectory + '*.txt'))
		
		logger.debug('Discovered text files in job report directory %s:  %s.' % (lsfJobReportDirectory, jobReportFiles))
		
		# Filter the list to only include job report files modified
		# recently.
		numSeconds = 120
		currentTime = time.time()
		recentlyModifiedJobReportFiles = []
		
		consolidatedJobReports = []
		
		for jobFile in jobReportFiles:
			mtime = os.path.getmtime(jobFile)
			# Compare the modified time against the current time.
			if currentTime - mtime < numSeconds:
				recentlyModifiedJobReportFiles.append(jobFile)
		
		# Read each recently modified job report file to see if
		# it is targetting a busy filer.
		for jobFile in recentlyModifiedJobReportFiles:
			# Retrieve the LSF job number and cluster name from the file name.
			fileName = os.path.basename(jobFile)
			regex = '^(\d+)-(.*)$'
			m = re.search(regex, fileName)
			if m is None:
				logger.info('File %s in LSF job report directory is not named in the expected format and will not be read.' % (jobFile))
				continue
			jobNumber = m.group(1)
			lsfClusterName = m.group(2)
			
			logger.info('Reading LSF job report file for job %s on cluster %s.' % (jobNumber, lsfClusterName))
			
			# Read the job report file and process its contents.
			with open(jobFile) as f:
				content = f.readlines()
				
				# The first line is a file header. Don't pass it in to be processed.
				consolidatedJobReport = self.consolidateJobReport(content[1:], since=(currentTime - numSeconds))
				
				# Store the consolidated job report with its job number and cluster name.
				consolidatedJobReports.append(JobReport(jobNumber, lsfClusterName, consolidatedJobReport))
				
		return consolidatedJobReports
				
	
	# Processes the contents of a job report file and consolidates it
	# into total number of operations. An optional argument "since"
	# may be specified. If it is, only operations after the since
	# time will be included and older operations will be ignored.
	def consolidateJobReport(self, jobReportContent, since=None):
		volumeToOperationsMap = {}
		
		# The format of the job report file looks like the following:
		#
		# 1350403871
		# fas3070rre2:/vol/vol_lsf1,0,32157
		# 1350403901
		# fas3070rre2:/vol/vol_lsf1,0,48807
		# 1350403931
		# fas3070rre2:/vol/vol_lsf1,0,48592
		#
		# With timestamps followed by one or more lines containing volumes
		# and operation counts:
		# <controller>:/vol/<volume>,<read_count>,<write_count>
		#
		# Job report files are appended to as more operations occur, so the
		# timestamps will increase (become more recent) as you move towards
		# the end of the file.
		currentTimestamp = None
		for line in jobReportContent:
			if re.match(r'^\d+\s*$', line) is not None:
				# This is a timestamp.
				currentTimestamp = int(line.strip())
			else:
				m = re.match(r'^(.+?):/vol/(\w+),(\d+),(\d+)(,\d+)*$', line)
				if m is None:
					raise Exception('Invalid job report format.')
				
				# This is a controller and volume operation line. Check to
				# see if the timestamp corresponding to this line is too
				# old to allow this line to be included in the operation
				# counts. This check could be moved before the regular
				# expression operation to save cycles at the cost of
				# potentially processing a file with an invalid format.
				if since is not None and since > currentTimestamp:
					continue
				
				controller = m.group(1)
				volume = m.group(2)
				readCount = int(m.group(3))
				writeCount = int(m.group(4))
				
				# The controller may be in the form of an IP address.
				# If so, look up its name in the dictionary and store
				# the job data by name instead.
				if controller in self.filerIPToFilerNameMap:
					controller = self.filerIPToFilerNameMap[controller]
				
				controllerAndVolume = controller + ':' + volume
				if controllerAndVolume not in volumeToOperationsMap:
					volumeToOperationsMap[controllerAndVolume] = OperationCounter()
				
				volumeToOperationsMap[controllerAndVolume].operations['RD'] += readCount
				volumeToOperationsMap[controllerAndVolume].operations['WR'] += writeCount
		
		return volumeToOperationsMap
				
			
	
	# Processes the XML files listed by file paths in the passed-in list.
	# Reads the files and then compares the performance data against the
	# acceptable performance thresholds specified in the configuration
	# file.
	def checkFiles(self, filesToCheck):
		# Check the performance data in the passed-in files against
		# the thresholds.
		for filepath in filesToCheck:
			logger.debug('Checking XML file %s.' % (filepath))
			
			# Read and parse the XML file.
			tree = ElementTree.parse(filepath)
			root = tree.getroot()
			
			if root.find('filer') is None:
				logger.warning('XML file %s is of an invalid format and does not appear to contain performance data.' % (filepath))
				continue
			
			filerName = root.find('filer').text
			lastUpdated = root.find('lastUpdated').text
			
			# Store the IP addresses for this filer in the dictionary.
			ipAddressNodes = root.findall('./ipaddresses/ipaddress')
			ipAddresses = []
			for ipAddressNode in ipAddressNodes:
				ipAddress = ipAddressNode.text
				self.filerIPToFilerNameMap[ipAddress] = filerName
			
			
			# Check the performance thresholds against the XML data. We
			# will store each performance threshold violation rather than
			# exiting after just one is found so that we can create a
			# report detailing all of the performance problems on a filer.
			
			aggregates = root.findall('./aggregates/aggr')
			for aggregate in aggregates:
				aggregateName = aggregate.find('name').text
				
				# We will check each volume for a disk busy error, but
				# since the volumes are all contained by the same
				# aggregate, we'll keep track if we've logged a disk
				# busy error so we log one error at most.
				diskBusyErrorLogged = False
				
				# Check all of the volume average latencies against the
				# maximum average volume latency threshold.
				volumes = aggregate.findall('./volumes/volume')
				for volume in volumes:
					volumeName = volume.find('name').text
					
					# Store this volume with its containing aggregate in
					# the map.
					filerAndVolume = filerName + ':' + volumeName
					self.volumeToContainingAggregateMap[filerAndVolume] = aggregateName
					
					# If a specific threshold is set for this volume,
					# use it. Otherwise, if a threshold is set for
					# this filer, use it. If no specific threshold
					# is set, use the default global threshold.
					maxAvgVolLatencyThreshold = self.globalThresholds.maxAvgVolLatency
					if filerAndVolume in self.targetThresholds and self.targetThresholds[filerAndVolume].maxAvgVolLatency is not None:
						maxAvgVolLatencyThreshold = self.targetThresholds[filerAndVolume].maxAvgVolLatency
					elif filerName in self.targetThresholds and self.targetThresholds[filerName].maxAvgVolLatency is not None:
						maxAvgVolLatencyThreshold = self.targetThresholds[filerName].maxAvgVolLatency
					
					# Compare the volume's average latency against the
					# threshold and log an error if necessary.
					averageLatency = float(volume.find('avglatency').text)
					
					if maxAvgVolLatencyThreshold != -1 and averageLatency > maxAvgVolLatencyThreshold:
						self.performanceErrorDocumentManager.logVolumeAverageLatencyError(filerName, volumeName, aggregateName, maxAvgVolLatencyThreshold, averageLatency)
						
						
					# Check the minimum available files threshold.
					minAvailFilesThreshold = self.globalThresholds.minAvailFiles
					if filerAndVolume in self.targetThresholds and self.targetThresholds[filerAndVolume].minAvailFiles is not None:
						minAvailFilesThreshold = self.targetThresholds[filerAndVolume].minAvailFiles
					elif filerName in self.targetThresholds and self.targetThresholds[filerName].minAvailFiles is not None:
						minAvailFilesThreshold = self.targetThresholds[filerName].minAvailFiles
					
					availFiles = float(volume.find('availinodes').text)
					
					if minAvailFilesThreshold != -1 and availFiles < minAvailFilesThreshold:
						self.performanceErrorDocumentManager.logVolumeMinAvailFilesError(filerName, volumeName, aggregateName, minAvailFilesThreshold, availFiles)
						
						
					
					# Check the minimum available size threshold.
					minAvailSizeThreshold = self.globalThresholds.minAvailSize
					if filerAndVolume in self.targetThresholds and self.targetThresholds[filerAndVolume].minAvailSize is not None:
						minAvailSizeThreshold = self.targetThresholds[filerAndVolume].minAvailSize
					elif filerName in self.targetThresholds and self.targetThresholds[filerName].minAvailSize is not None:
						minAvailSizeThreshold = self.targetThresholds[filerName].minAvailSize
					
					availSizeInBytes = float(volume.find('availsize').text)
					# Available size is read in bytes, but the threshold
					# is set in megabytes. Convert to megabytes.
					availSizeInMegabytes = availSizeInBytes / 1024.0
					
					if minAvailSizeThreshold != -1 and availSizeInMegabytes < minAvailSizeThreshold:
						self.performanceErrorDocumentManager.logVolumeMinAvailSizeError(filerName, volumeName, aggregateName, minAvailSizeThreshold, availSizeInMegabytes)
						
					
					
					# Although MaxDiskBusy is really an aggregate-level
					# threshold, thresholds are set at the volume level
					# in the configuration file. Thus we will check each
					# volume for a disk-busy error so long as we have not
					# already logged a disk-busy error for this aggregate.
					if not diskBusyErrorLogged:
						# If a specific threshold is set for this volume,
						# use it. Otherwise, if a threshold is set for
						# this filer, use it. If no specific threshold
						# is set, use the default global threshold.
						maxDiskBusyThreshold = self.globalThresholds.maxDiskBusy
						if filerAndVolume in self.targetThresholds and self.targetThresholds[filerAndVolume].maxDiskBusy is not None:
							maxDiskBusyThreshold = self.targetThresholds[filerAndVolume].maxDiskBusy
						elif filerName in self.targetThresholds and self.targetThresholds[filerName].maxDiskBusy is not None:
							maxDiskBusyThreshold = self.targetThresholds[filerName].maxDiskBusy
					
						# Check the busiest disk in the aggregate against the
						# maximum disk busy threshold.
						highestDiskBusy = float(aggregate.find('maxdiskb').text)
						if maxDiskBusyThreshold != -1 and highestDiskBusy > maxDiskBusyThreshold:
							self.performanceErrorDocumentManager.logDiskBusyError(filerName, aggregateName, maxDiskBusyThreshold, highestDiskBusy)
							diskBusyErrorLogged = True
						
			
			
			# Check the non-exempt CPU domain utilizations against the
			# maximum non-exempt CPU domain utilization threshold.
			# If a specific threshold is set for this filer,
			# use it. Otherwise, use the default global threshold.
			maxNEDomainThreshold = self.globalThresholds.maxNEDomain
			if filerName in self.targetThresholds and self.targetThresholds[filerName].maxNEDomain is not None:
				maxNEDomainThreshold = self.targetThresholds[filerName].maxNEDomain
			
			nonExemptCPUDomains = root.findall('./domains/domain')
			for domain in nonExemptCPUDomains:
				domainName = domain.find('name').text
				domainCPUUtilization = float(domain.find('value').text)
				
				if maxNEDomainThreshold != -1 and domainCPUUtilization > maxNEDomainThreshold:
					self.performanceErrorDocumentManager.logNonExemptCPUDomainUtilizationError(filerName, domainName, maxNEDomainThreshold, domainCPUUtilization)
			
		
	# Reads the configuration file for this script to load properties.
	def readConfigurationFile(self, configurationFilePath):
		logger.info('Reading configuration file at %s.' % (configurationFilePath))
		
		# Load the default values into the property map. These will be
		# overwritten when reading the config file.
		self.properties['ontap_xml_data_directory'] = '.'
		self.properties['lsf_job_report_directory'] = '.'
		self.properties['hot_job_report_directory'] = '.'
		self.properties['file_check_interval'] = '10'
		self.properties['command_to_run'] = 'python send_email_alert.py'
		self.properties['num_top_jobs_to_report'] = '3'
		self.properties['delete_report_after_command'] = 'false'
		
		# Set some default values for the global thresholds. These should
		# be overwritten when reading the config file.
		self.globalThresholds.Max_DiskBusy = 80.0
		self.globalThresholds.Max_NEDomain = 50.0
		self.globalThresholds.Max_AvgVolLatency = 100.0
		self.globalThresholds.Min_AvailFiles = 1000.0
		self.globalThresholds.Min_AvailSize = 1000.0
		
		
		# Create the ConfigParser object.
		config = ConfigParser()
		
		# We use colons in the config file for volume paths (e.g. fas3000:/vol1). Usually,
		# colons are treated as the equivalent of an equal sign in the configuration
		# format. We will overwrite the regular expression used by the ConfigParser class
		# so that colons won't be treated as a special character.
		OPTCRE = re.compile(
			r'(?P<option>[^=\s][^=]*)'          # very permissive!
			r'\s*(?P<vi>[=])\s*'                 # any number of space/tab,
												  # followed by separator
												  # (=), followed
												  # by any # space/tab
			r'(?P<value>.*)$'                     # everything up to eol
		)
		config._optcre = OPTCRE
		
		# By default, the ConfigParser module converts everything to lower case. We
		# need to preserve case. The following change to the ConfigParser object
		# enables that.
		config.optionxform = str
		
		try:
			config.read(configurationFilePath)
			
			# Read options in section MAIN. These set paths and variables
			# for this script.
			for option in config.options('MAIN'):
				try:
					optionValue = config.get('MAIN', option)
					self.properties[option] = optionValue
					logger.debug('Set property %s = %s.' % (option, optionValue))
				except:
					# Something went wrong reading this section. Log an error.
					logger.error('Encountered an error reading the MAIN section of the configuration file.')
					pass
			
			# Read the global thresholds, which will apply if no thresholds
			# for the specific filer and/or volume in question are set.
			for option in config.options('GLOBAL_THRESHOLDS'):
				try:
					optionValue = config.get('GLOBAL_THRESHOLDS', option)
					
					if option.lower() == 'max_diskbusy':
						self.globalThresholds.maxDiskBusy = float(optionValue)
					elif option.lower() == 'max_nedomain':
						self.globalThresholds.maxNEDomain = float(optionValue)
					elif option.lower() == 'max_avgvollatency':
						self.globalThresholds.maxAvgVolLatency = float(optionValue)
					elif option.lower() == 'min_availfiles':
						self.globalThresholds.minAvailFiles = float(optionValue)
					elif option.lower() == 'min_availsize':
						self.globalThresholds.minAvailSize = float(optionValue)
					else:
						logger.error('Unknown global threshold %s encoutnered in configuration file. Allowed values are: Max_DiskBusy, Max_NEDomain, Max_AvgVolLatency, Min_AvailFiles, and Min_AvailSize.' % (option))
						continue
						
					logger.debug('Set global default threshold %s = %s.' % (option, optionValue))
				except:
					# Something went wrong reading this section. Log an error.
					logger.error('Encountered an error reading the GLOBAL_THRESHOLDS section of the configuration file.')
					pass
					
			# Read the target thresholds, which apply to specific filers
			# and/or volumes. An example of a filer-level property:
			# fas6280c-svl11				Max_AvgVolLatency 	= 100
			# And an example of a volume-level property:
			# fas6280c-svl11:/volnfsDS	Max_AvgVolLatency	= 50
			for option in config.options('TARGET_THRESHOLDS'):
				try:
					optionValue = config.get('TARGET_THRESHOLDS', option)
					
					values = option.split()
					if len(values) != 2:
						logger.error('Target threshold "%s" is not a valid format. Expected format is: "%s".' % (option, 'fas6280c-svl11:/volnfsDS	Max_AvgVolLatency	= 50'))
						continue
					
					target, threshold = values
					target = target.replace(':/vol/', ':')
					# Store a Thresholds object with empty values if this
					# is the first time we've encountered this target.
					if target not in self.targetThresholds:
						self.targetThresholds[target] = Thresholds()
					
					if threshold.lower == 'max_diskbusy':
						self.targetThresholds[target].maxDiskBusy = float(optionValue)
					elif threshold.lower() == 'max_nedomain':
						self.targetThresholds[target].maxNEDomain = float(optionValue)
					elif threshold.lower() == 'max_avgvollatency':
						self.targetThresholds[target].maxAvgVolLatency = float(optionValue)
					elif threshold.lower() == 'min_availfiles':
						self.targetThresholds[target].minAvailFiles = float(optionValue)
					elif threshold.lower() == 'min_availsize':
						self.targetThresholds[target].minAvailSize = float(optionValue)
					else:
						logger.error('Unknown threshold %s encountered in configuration file for target %s. Allowed values are: Max_DiskBusy, Max_NEDomain, Max_AvgVolLatency, Min_AvailFiles, and Min_AvailSize.' % (threshold, target))
						continue
						
					logger.debug('Set threshold %s = %s for target %s.' % (threshold, optionValue, target))
					
				except:
					# Something went wrong reading this section. Log an error.
					logger.error('Encountered an error reading the TARGET_THRESHOLDS section of the configuration file.')
					pass
		except:
			logger.error('Could not read configuration file at %s. Using default values.' % (configurationFilePath))
	
	
if __name__ == '__main__':
	hotJobDetector = HotJobDetector()
	hotJobDetector.run()
	
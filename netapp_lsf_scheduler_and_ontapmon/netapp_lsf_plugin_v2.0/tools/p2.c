/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */
#include "sysntap.h"
#include "expat-2.0.1/lib/expat_external.h"
#include "expat-2.0.1/lib/expat.h"


/* Hash table of all filers, volume, storagemap names is used 
 * for fast load updates.
 */
struct htab   *filertab;
struct htab   *fstab;
struct htab   *mounttab;
struct htab   *fptab;

static char   wbuf[BUFSIZ];
static char   tmpbuf[BUFSIZ];
static int    numfilesys;
static int    numfilers;
static int    numvols;

static char   logfile[PATH_MAX];
static char   eventfile[PATH_MAX];

/* plugin parameters
 */
static struct params   prms;
static struct loadpolicy policy;

static char   *get_config_file(void);
static void   initparams(void);
static int    init(void);
static int    parse_filesys(const char *);
static void   parse_policies(const char *);
static int    parse_filerpolicies(const char *);
static int    parse_params(const char *);
static void   desperado(const char *);
static int    parse_ctrxml(char *);
static int    process_element();
static void   char_handler(void *, const char *, int);
static void   end_handler(void *, const char *);
static void   start_handler(void *, const char *, const char **);
static void   print_list(struct fvlist *);
static void   print_fstab(void);
static void   print_filertab(void);
static void   print_fptab(void);
static void   *hash_install_2(struct htab *, const char *key, void *v);
static void   test_fshashlink(char *);
static void   test_filerhashlink(void);
static void   delSpace(char *);
static int    compare_thresholds(char *filername, char *volname);
static void   free_filer(char *);
static void   free_fs(char *);

/*
 * Variables for XML parsing
 */
static int	depth=0;
static int	Eventcnt=0;
static char	last_content[PATH_MAX];
static char	save_content[PATH_MAX];
static double	tmp_maxdiskb;
static char	endelement[40];
static int	dcnt;
static struct filer	*ftmp;
static struct filesystem *vtmp;


/* 
 * read_conf() - reads configuration (ntapplugin.conf) file and stores 
 * the parameters in structures. 
 * @return -1: If unable to process config file
 */ 
int 
read_conf(void)
{
    static char         fname[] = "read_conf()";
    int                 cc;
    FILE                *fp;
    char                *record;
    char                *file;

    file = get_config_file();
    if (file == NULL) 
	return(-1);

    fp = fopen(file, "r");
    if (fp == NULL) {
	sprintf(tmpbuf, "\
Cannot open %s %s filer plugin disabled", file, errstr);
	desperado(tmpbuf);
	return(-1);
    }
    
    /* Initialize default plugin 
     * parameters.
     */
    log_msg(MSG_INFO, "initializing param\n");
    initparams();

    /* First read the configuration parameters
     * that control the plugin operations.
     */
    record = get_begin_record(fp, PARAMETERS);
    while ((record = get_record_until_end(fp, PARAMETERS, &cc))) {
	/* Ignore comment line */
	if (record[0] == '#')
	  continue;

	parse_params(record);
    }
    log_msg(MSG_INFO, "parsing params: loglevel %d\n", prms.loglevel);
    
    rewind(fp);
    /* Read the Begin FileSystems section.
     * First count how many filesystems are 
     * configured to size the hash tables.
     */

    record = get_begin_record(fp, FILE_SYSTEMS);
    while ((record = get_record_until_end(fp, FILE_SYSTEMS, &cc))) {
        /* Count number of volumes for volume hash tables */
	if (record[0] == '#')
	  continue;
        char *result = NULL;
        result = strtok(record, ":");
        while (result != NULL) {
	    ++numvols;
	    result = strtok(NULL, ":");
        }
	++numfilesys;
    }

    /* At this time intialize the plugin 
     * main data structures.
     */
    if (init() == -1) {
      log_msg(MSG_ERR, "%s: unable to allocate hash tables", fname);
      return (-1);
    }

    log_msg(MSG_INFO, "\
%s: reading filer plugin configuration", fname);

    /* rewind() as the order of section in the file
     * is not guaranteed.
     */
    rewind(fp);
    
    /* Read file systems...
     */
    record = get_begin_record(fp, FILE_SYSTEMS);
    while ((record = get_record_until_end(fp, FILE_SYSTEMS, &cc))) {
	if (record[0] == '#')
	  continue;

	if (parse_filesys(record) == -1) {
	  rewind(fp);
	  return(-1);
	}
    }
    rewind(fp);

    record = get_begin_record(fp, PLUGIN_POLICY);
    while ((record = get_record_until_end(fp, PLUGIN_POLICY, &cc))) {
	if (record[0] == '#')
	  continue;

	parse_policies(record);
    }
    rewind(fp);

    record = get_begin_record(fp, FILER_POLICY);
    while ((record = get_record_until_end(fp, FILER_POLICY, &cc))) {
	if (record[0] == '#')
	  continue;

	parse_filerpolicies(record);
    }
    rewind(fp);
    print_fptab();

    fclose(fp);

    log_msg(MSG_INFO, "\
%s: schmod_ntap.so plugin configured all right", fname);

    return(0);

}

/* 
 * check_dirctr() - Check for existence of directory that contains 
 * the XML files that has the filer counter information.
 * @return -1: If unable to find an existence of counter directory.
 */
int
check_dirctr(void)
{

    static char   fname[] = "chk_dirctr()";
    DIR *dirp;
    struct dirent *dentry;
    
    /* 
     * Count the number of files in directory
     */
    dirp = opendir(prms.counterdir);
    if (dirp == NULL) {
        log_msg(MSG_DEBUG, "\%s: No existence of directory %s %s", fname, prms.workdir, errstr); 
	return(-1);
    }
    while ((dentry = readdir(dirp)) != NULL ) {
	   if (dentry->d_type == DT_REG) {
	     numfilers++;
	   }
    }
    closedir(dirp);
    return(0);
}

/* 
 * filer_load_ok() - Goes thru list of filers and volumes to check if 
 * load is ok. 
 * -1: supplied storagemap name unknown
 *  1: load on mount point from filer/filesystem 
 *     exceeds configured policy threshold
 *  0: load on mount point from filer/filesystem
 *     are within the scheduling threshold
 */
int
filer_load_ok(const char *fstag)
{

    static char         fname[] = "filer_load_ok()";
    struct filer	*filer;
    struct stormap	*fs;
    struct fvlist	*currp;
    time_t		seconds;
    char		vname[PATH_MAX];
    int			res;

    /* Find the list of volumes for this
     * storage map.
     */
    fs = hash_lookup(mounttab, fstag);

    if (fs == NULL) {
	log_msg(MSG_DEBUG, "\
%s: mount point %s is not known", fname, fstag);
	return(-1);
    }

    print_list(fs->vollist);
    currp = fs->vollist;

    /* 
     * Get the current time, and if there is a big time differenece
     * zero out the contents of the filer in filertab and fstab
     * and so that filer information can be re-read 
     *
     * Re-read if seconds - readTime(of each filer) > reread_value
     */
    seconds = time(NULL);
    while (currp != NULL)  {
        filer = hash_lookup(filertab, currp->filer);
	if (filer != NULL)  {
        if ((seconds - filer->readTime) > prms.xmlreread) {
	      log_msg(MSG_DEBUG, "%s: freeing up filer %s from table ", fname, currp->filer);
	        free_filer(currp->filer);
	        free_fs(currp->filer);
	    }
        }
	currp = currp->next;
    }
    
    currp = fs->vollist;

    /*
     * Go thru list of volumes and check filer and volume thresholds and 
     * compare.
     */
    while (currp != NULL) {
	log_msg(MSG_DEBUG, "FILER %s:", currp->filer);
        filer = hash_lookup(filertab, currp->filer);
	if (filer == NULL){
	    sprintf(vname, "%s/%s.xml", prms.counterdir, currp->filer);
  	    /* Parse XML Counter Document */
	    log_msg(MSG_DEBUG, "%s: Parsing %s doc ", fname, vname);
	    if (parse_ctrxml(vname)) {
	      log_msg(MSG_ERR, "%s: Error in parsing %s", fname, vname);
	      return(-1);
	    }

	}
	/* Compare values for filer */
       	res = compare_thresholds(currp->filer, currp->volname);
	if (res != 0)
	    return(res);
	/* Get next filer/volume */
	currp = currp->next;
    }
    return(0);
} 
/*
 * free_filer - Frees filer data from linked list in the hash table
 */
static
void
free_filer(char *name) 
{
    struct nlist   *currp, *prevp;
    int		   indx;
    struct filer   *fp;

    indx = hash(name, filertab->size);
    prevp = NULL;
    for (currp = filertab->tab[indx]; currp != NULL; prevp = currp, currp = currp->next) {
      /* If filer found */
        if (strcmp(currp->key, name) == 0) {
	    /* if removing node from head of list */
	    if (prevp == NULL) {
	        filertab->tab[indx] =  currp->next;
	    } else {
	        prevp->next = currp->next;
	    }
	    fp = currp->data;
	    free(fp->name);
	    free(fp);
	    free(currp->key);
	    free(currp);
	    break;
	}
    }

} 

/*
 * free_fs - frees all items in fstab
 * hash table/linked list associated with name 
 */
static void
free_fs(char *name)
{
  struct nlist	*currp, *prevp, *temp;
    struct filesystem	*fs;
    int			i;
    char		*x;
    
    for (i=0; i < fstab->size; i++) {
        prevp = NULL;
	/* Go thru linked list and check if name is in list */
	currp = fstab->tab[i];
	while (currp != NULL) {
	    x = strstr(currp->key, name); 
	    /* if it is found, remove from linked list and free space */
	    if (x != NULL) {
	      /* if removing node from head of list */
	        if (prevp == NULL) {
		    fstab->tab[i] =  currp->next;
		    prevp = NULL;
		    temp = currp;
		    currp = currp->next;
		} else {
		  /* prevp stays pointing to same self */
		    prevp->next = currp->next;
		    temp = currp;
		    currp = currp->next;
		}
		fs = temp->data;
		free(fs->volume);
		free(fs);
		free(temp->key);
		free(temp);
	    } else {
	      prevp = currp;
	      currp = currp->next;
	    }
	} /* end of while */
    } /* end of for */
} 

/*
 * Compares the filer and volume counter information with the thresholds.
 * @returns:
 *  1: if one counter value does not meet required thesholds
 *  0: if all thresholds meet required thresholds.
 * -1: if unable to compare. 
 */

static int
compare_thresholds(char *filername, char *volname) {
    static char fname[]="compare_thresholds()";
    struct filerpol   *fpo;
    struct filer      *f;
    struct filerpol   *vpo;
    struct filesystem *v;
    int		      i;
    double	      asize;

    f = hash_lookup(filertab, filername);
    if (f == NULL) {
        log_msg(MSG_ERR, "%s: Unable to compare filer thresholds for %s is NULL.", fname, filername);
	return(-1);
    }

    fpo = hash_lookup(fptab, filername);

    /* If there are filer specific policies, check against only those, 
     * otherwise, check against global policies 
     */
    if ((fpo != NULL) && (fpo->policy.maxnedomain != 0)) {
        for (i=0; i<DOMAIN_SIZE;i++) {
	    log_msg(MSG_DEBUG, "%s: filer %s: domain value %0.5f maxdomain %0.5f", fname, filername, f->domains[i], fpo->policy.maxnedomain);
	    if (f->domains[i] > fpo->policy.maxnedomain)
	        return(1);
	}
    } else {
        for (i=0; i<DOMAIN_SIZE;i++) {
	    log_msg(MSG_DEBUG, "%s: filer %s: domain value %0.5f maxdomain %0.5f", fname, filername, f->domains[i], policy.maxnedomain);
	    if (f->domains[i] > policy.maxnedomain)
	        return(1);
	  }
    }

    /* Next check for volume specific policies */
    sprintf(wbuf, "%s:%s", filername, volname);
    v = hash_lookup(fstab, wbuf);
    if (v == NULL) {
        log_msg(MSG_ERR, "%s: Unable to compare volume thresholds for %s is NULL.", fname, wbuf);
	return(-1);
    }

    vpo = hash_lookup(fptab, wbuf);

    log_msg(MSG_DEBUG, "%s: volume %s: diskb %0.5f, avglatency %0.5f, availinodes %0.5f, availsize %0.5f", fname, v->volume, v->maxdiskbusy, v->avglatency, v->availinodes, v->availsize);
    /* Check for maxdisk busy */
    if ((vpo != NULL) && (vpo->policy.maxdiskbusy != 0)) {
      if (v->maxdiskbusy > vpo->policy.maxdiskbusy) 
	    return(1);
    } else if ((fpo != NULL) && (fpo->policy.maxdiskbusy !=0)) {
      if (v->maxdiskbusy > fpo->policy.maxdiskbusy)
	    return(1);

    } else {
      if (v->maxdiskbusy > policy.maxdiskbusy) 
	  return(1);
    }

    /* Check for avg vol latency */
    if ((vpo != NULL) && (vpo->policy.maxavgvollat != 0)) {
      if (v->avglatency > vpo->policy.maxavgvollat) 
	    return(1);
    } else if ((fpo != NULL) && (fpo->policy.maxavgvollat !=0)) {
      if (v->avglatency > fpo->policy.maxavgvollat) 
	  return(1);
    } else {
      if (v->avglatency > policy.maxavgvollat)  
	  return(1);

    }

    /* Check for avail files (num inodes) */
    if ((vpo != NULL) && (vpo->policy.mininodes != 0)) {
	if (v->availinodes < vpo->policy.mininodes)
	    return(1);
    } else if ((fpo != NULL) && (fpo->policy.mininodes !=0)) {
        if (v->availinodes < fpo->policy.mininodes) 
	  return(1);
    } else {
        if (v->availinodes < policy.mininodes) 
	  return(1);
    }

    /* Convert availsize to MB prior to compare */
    asize = (v->availsize/1024)/1024;
    if ((vpo != NULL) && (vpo->policy.minsize != 0)) {
	if (asize < vpo->policy.minsize)
	    return(1);
    } else if ((fpo != NULL) && (fpo->policy.minsize !=0)) {
        if (asize < fpo->policy.minsize) 
	  return(1);
    } else {
        if (asize < policy.minsize) 
	  return(1);
    }

    return (0);
}

/* 
 * get_config_file() - Gets location of config file
 * @return - absolute path of config file.
 * 
 */
static char *
get_config_file(void)
{
    char   *f;

    f = getenv("LSF_ENVDIR");
    if (f)
	sprintf(wbuf, "%s/%s", f, PLUGIN_CONF);
    else
	sprintf(wbuf, "%s/%s", "/etc", PLUGIN_CONF);

    return(wbuf);

} 

/*
 * init() -  initializes the hashtables 
 * @return -1: If unable to allocate space for the hash tables.
 */
static int
init(void)
{
    static char          fname[] = "init()";
    init_log(prms.loglevel);
    open_log(logfile);

    /* Allocate space for filer information */
    filertab = hash_mk(numfilers);
    if (filertab == NULL)
	goto hosed;

    /* Allocate space for volume specific information */
    fstab = hash_mk(numvols);
    if (fstab == NULL)
	goto hosed;

    /* Allocate space for filer policies table */
    fptab = hash_mk(numvols);
    if (fptab == NULL)
	goto hosed;

    /* Allocate space for the list of volumes/filers to track */
    mounttab = hash_mk(numfilesys);
    if (mounttab == NULL)
	goto hosed;

    return(0);

  hosed:
    freeit(filertab);
    freeit(fstab);
    log_msg(MSG_ERR, "Unable to allocate space for hashtables", fname);
    return(-1);

}


/* 
 * parse_filesys_record()  - parses the export names and puts them 
 * in a hash table.
 * @return -1: If there is an error in parsing storagemap 
 * or unable to allocate space
 */
static int
parse_filesys(const char *record)
{
    static char          fname[] = "parse_filesys()";
    struct filesystags	 fst;
    int                  cc;
    char		 lbuf[BUFSIZ];
    struct stormap	 *sm, *hm;
    struct fvlist	 *newp, *endp;
    char		 *result = NULL;

    /* Get storage map name information */
    cc = sscanf(record, "%s \n%[^\n]", &fst.mount, lbuf);

    /* Return -1 if unable to get valid information */
    if (cc < 2) {
	log_msg(MSG_ERR, "\
%s: failed parsing record %s", fname, record);
	return(-1);
    }
    
    /* First check for 
     * duplicate storage name alias.
     * Ignore second occurrence.
     */
    hm = hash_lookup(mounttab, fst.mount);
    if (hm) {
	log_msg(MSG_ERR, "\
%s: duplicate mount point %s found in record %s, ignored", 
		fname, fst.mount, record);
	return(0);
    }

    /* If not in hash, add to hashtable mounttab based on fst.mount as 
       key to hash */
    sm = calloc(1, sizeof(struct stormap));
    if (sm == NULL) {
      log_msg(MSG_ERR, "%s: failed to allocate stormap in record %s", fname, fst.mount);
	   return(-1);
    }

    sm->name = strdup(fst.mount);

    /* Delete spaces in string just in case */
    delSpace(lbuf);
    
    /* Parse list of filers:/vol data. Get first token in string */
    result = strtok(lbuf, ",");

    /* Initialize the head of fvlist */
    sm->vollist = (struct fvlist *)NULL;
    endp = (struct fvlist *)NULL;
    while ( result != NULL) {
      sscanf(result, "%[^:]:%s", &fst.filer, &fst.fs);
      newp = (struct fvlist *) calloc(1, sizeof(struct fvlist));
      if (newp == NULL) {
	log_msg(MSG_ERR, "%s: failed to allocate fvlist for record %s:%s", fname, fst.filer, fst.fs);
	    return(-1);
      }
      newp->filer = strdup(fst.filer);
      newp->volname = strdup(fst.fs);

      /* If in beginning of list */
      if (sm->vollist == NULL)  {
	endp = newp;
	sm->vollist = newp;
      } else {
	/* Add to end of list */
	endp->next = newp;
	newp->next = NULL;
	endp = newp;
      }
      result = strtok( NULL, ",");

    }      

    print_list(sm->vollist);
    /* Add fst.mount as key and list of volumes as data */
    hash_install(mounttab, fst.mount, sm);
    log_msg(MSG_DEBUG, "\
%s: mount export name %s configured", 
	    fname, fst.mount);
    return(0);

} 

/*
 *  parse_policies() - parses the plugin global policies 
 */
static void
parse_policies(const char *record)
{
    static char         fname[] = "parse_policies()";
    char                ptag[32];
    char                ntag[16];

    /* get the first global policies
     */
    sscanf(record, "%[^=]=%s", ptag,  ntag);

    /* Deletes spaces and tabs in ptag and ntag
     */
    delSpace(ptag);
    delSpace(ntag);

    printf("ptag %s, ntag %s\n", ptag,ntag);

     if (strcmp(ptag, "Max_AvgVolLatency") == 0) {
	policy.maxavgvollat = atof(ntag);
	log_msg(MSG_DEBUG, "\
%s:  Max_AvgVolLatency %5.3f configured",
		    fname, policy.maxavgvollat);
	return;
     }

    if (strcmp(ptag, "Max_DiskBusy") == 0) {
	policy.maxdiskbusy = atof(ntag);
	log_msg(MSG_DEBUG, "\
%s:  Max_DiskBusy %5.3f configured",
		    fname, policy.maxdiskbusy);
	return;
    }
     if (strcmp(ptag, "Min_AvailFiles") == 0) {
	policy.mininodes = atof(ntag);
	log_msg(MSG_DEBUG, "\
%s:  Max_NEDomain %5.3f configured",
		    fname, policy.mininodes);
	return;
     }
     if (strcmp(ptag, "Min_AvailSize") == 0) {
	policy.minsize = atof(ntag);
	log_msg(MSG_DEBUG, "\
%s:  Max_NEDomain %5.3f configured",
		    fname, policy.minsize);
	return;
     }
     if (strcmp(ptag, "Max_NEDomain") == 0) {
	policy.maxnedomain = atof(ntag);
	log_msg(MSG_DEBUG, "\
%s:  Max_NEDomain %5.3f configured",
		    fname, policy.maxnedomain);
	return;
     }
} 


/*
 *  parse_filerpolicies() - parses the plugin filer and volume 
 *  specific policies 
 */
static int
parse_filerpolicies(const char *record)
{
    static char         fname[] = "parse_filerpolicies()";
    char                ptag[32];
    char                ntag[16];
    char		ftag[MAX_NAME_LEN];
    struct filerpol	*fpo;

    /* get the filer and volume specific policies
     */
    sscanf(record, "%s %[^=]=%s", ftag, ptag, ntag);

    /* Deletes spaces and tabs in ptag and ntag
     */
    delSpace(ptag);
    delSpace(ntag);

    printf("ftag %s, ptag %s, ntag %s\n", ftag, ptag, ntag);
    /* Look for existence of filer or volume in fptable. */
    fpo = hash_lookup(fptab, ftag);
    if (fpo == NULL) {
      /* If not in table, allocate and install */
        fpo = calloc(1, sizeof(struct filerpol));
	if (fpo == NULL) {
          log_msg(MSG_ERR, "%s: failed allocate : %s", fname, ftag);
	  return(-1);
	}
	fpo->name = strdup(ftag);
	hash_install(fptab, ftag, fpo);
	printf("filer table policies %s\n", ftag);
     }

     if (strcmp(ptag, "Max_AvgVolLatency") == 0) {
	fpo->policy.maxavgvollat = atof(ntag);
	log_msg(MSG_DEBUG, "\
%s:  Max_AvgVolLat_Busy %5.3f configured",
		    fname, fpo->policy.maxavgvollat);
	return(0);
     }

    if (strcmp(ptag, "Max_DiskBusy") == 0) {
	fpo->policy.maxdiskbusy = atof(ntag);

	log_msg(MSG_DEBUG, "\
%s:  Max_DiskBusy %5.3f configured",
		    fname, fpo->policy.maxdiskbusy);
	return(0);
    }
     if (strcmp(ptag, "Min_AvailFiles") == 0) {
	fpo->policy.mininodes = atof(ntag);
	log_msg(MSG_DEBUG, "\
%s:  Max_NEDomain %5.3f configured",
		    fname, fpo->policy.mininodes);
	return(0);
     }
     if (strcmp(ptag, "Min_AvailSize") == 0) {
	fpo->policy.minsize = atof(ntag);
	log_msg(MSG_DEBUG, "\
%s:  Max_NEDomain %5.3f configured",
		    fname, fpo->policy.minsize);
	return(0);
     }
     if (strcmp(ptag, "Max_NEDomain") == 0) {
	fpo->policy.maxnedomain = atof(ntag);
	log_msg(MSG_DEBUG, "\
%s:  Max_NEDomain %5.3f configured",
		    fname, fpo->policy.maxnedomain);
	return(0);
     }
     return(0);

} 

/* 
 * parse_params() - parses the parameters section of config file.
 * @return -1: If unable to parse the parameters in config file
 */
static int   
parse_params(const char *record)
{
    /* Parse the parameters section of 
     * the configuration file.
     */
    sscanf(record, "%s%s", wbuf, tmpbuf);    

    if (strcasecmp(wbuf, Debug) == 0
	&& strcasecmp(tmpbuf, "yes") == 0) {
	prms.loglevel = MSG_DEBUG;
	return(0);
    }

    if (strcasecmp(wbuf, Work_Dir) == 0) {

	strcpy(prms.workdir, tmpbuf);
	/* Plugin working files...
	 */
	sprintf(eventfile, "%s/%s", tmpbuf, Events_File);
	sprintf(logfile, "%s/%s", tmpbuf, Log_File);
	return(0);
    }

    if (strcasecmp(wbuf, Counter_Dir) == 0) {

	/* Location of where counter information for each filer managed
	 * by DFM.
	 */
	strcpy(prms.counterdir, tmpbuf);
	return(0);
    }

    if (strcasecmp(wbuf, XMLReread) == 0) { 
        prms.xmlreread = atoi(tmpbuf);
	return(0);
    }

    if (strcasecmp(wbuf, DryRunMode) == 0) {
        if (strcasecmp(tmpbuf, "yes") == 0)
            prms.dryrun = 1;
	else
	    prms.dryrun = 0;
	return(0);
    }

    return(0);

} 

/*
 * get_dryrun() - returns value of dry run
 * @ return 1: In dry run mode
 *	    0: Not in dry run mode
 */
int 
get_dryrun(void) {
    return(prms.dryrun);
}

/* 
 * desperado() 
 * Dump a desperado message to an emergency log 
 * file in /tmp.
 */
static void
desperado(const char *msg)
{
    static char   fname[] = "desperado()";
    time_t        t;
    FILE          *fp;

    /* This is very bad as we cannot find 
     * the basic configuration files, so 
     * as an act of desperation open a 
     * file in /tmp cry and tell scheduler 
     * we cannot configure ourselves.
     */
    fp = fopen("/tmp/filerplugin.log", "a+");
    if (fp == NULL)
	return;

    time(&t);
    fprintf(fp, "\
%.15s %s: %d %s\n", ctime(&t) + 4, fname, getpid(), msg);

    fclose(fp);

} /* desperado() */

/* 
 * initparams() 
 * Initialize plugin defaults.
 */
static void 
initparams(void)
{
    prms.loglevel = MSG_INFO;

    strcpy(prms.workdir, "/tmp");

    /* Plugin working files...
     */
    sprintf(eventfile, "%s/%s", prms.workdir, Events_File);
    sprintf(logfile, "%s/%s", prms.workdir, Log_File);


} 

/*
 * delSpace() - deletes the spaces within a string or tabs.
 */
static void
delSpace(char *str) 
{
    char *p1=str, *p2=str;

    do {
      while ((*p2 == ' ')  || (*p2 == '\t'))
            p2++;
    } while ((*p1++ = *p2++));
}

/*
 * parse_ctrxml - parses the counter XML document
 * @return -1: If unable to parse the counter XML document
 */
static int
parse_ctrxml(char *xfile) 
{
    char		fname[] = "parse_ctrxml()";
    FILE		 *fp;
    char		lbuf[BUFSIZ];

    fp = fopen(xfile, "r");

    if(fp == NULL) {
	log_msg(MSG_ERR, "%s: Couldn't open filer %s", fname, xfile);
	return(-1);
    }

    XML_Parser xp = XML_ParserCreate(NULL);
    if (! xp) {
	log_msg(MSG_ERR, "%s:Couldn't allocate memory for parser for filer %s\n", fname, xfile);
	fclose(fp);
	return(-1);
    }

    XML_UseParserAsHandlerArg(xp);
    XML_SetElementHandler(xp, start_handler, end_handler);
    XML_SetCharacterDataHandler(xp, char_handler);
    log_msg(MSG_DEBUG, "%s: Registered XML handlers for %s", fname, xfile);
    dcnt = 0;
    for (;;) {
	int done;
	int len;
	/* Get a line from the file */
	fgets(lbuf, sizeof(lbuf), fp);
	len = strlen(lbuf);
	done = feof(fp);
	if (done)
	    break;
	log_msg(MSG_DEBUG, "%s: Got line from file %s", fname, lbuf);

	/* Begin parsing line */
	if (! XML_Parse(xp, lbuf, len, done)) {
	    log_msg(MSG_ERR, "%s: Parse error at line %d:\n%s\n", fname,
		    XML_GetCurrentLineNumber(xp),
		    XML_ErrorString(XML_GetErrorCode(xp)));
	    XML_ParserFree(xp);
	    fclose(fp);
	    return(-1);

	}
	/* Process the elements within XML doc */
	if (process_element()) {
	    fclose(fp);
	    XML_ParserFree(xp);
	    return(-1);
	}
    }
    /* Free parser structure allocated */
    XML_ParserFree(xp);
    fclose(fp);
    return(0);
} 

/*
 * start_handler() - handler for the start tag which just keep track of depth.
 */
static void
start_handler(void *data, const char *element, const char **attr) {
    static char		fname[] = "start_handler()";

    depth++;
    log_msg(MSG_DEBUG, "%s:%4d: Start tag %s - Depth %d - ", fname, Eventcnt++, element, depth);
    sprintf(endelement, "%s", "");

} 

/*
 * end_handler() - handler for the end tag.  End handler is responsible
 * for saving the endelement and last content encountered.
 */
static void
end_handler(void *data, const char *element) 
{
    static char		fname[] = "end_handler()";

    sprintf(endelement, "%s", element);
    sprintf(last_content, "%s", save_content);
    log_msg(MSG_DEBUG, "%s:%4d: End tag %s Saved %s\n", fname, Eventcnt++, endelement, last_content);    
    depth--;
}

/*
 * char_handler() - handler for the values inside the start and end tags.  
 * Character handler saves the content which would be saved in the end handler.
 */
static void
char_handler(void *data, const char *txt, int txtlen) 
{
    static char fname[]="char_handler()";

    strncpy(save_content, txt, txtlen);
    save_content[txtlen]='\0';
    log_msg(MSG_DEBUG, "%s:%4d: Text - %s", fname, Eventcnt++, save_content);

}  

/*
 * process_element() - process the XML file and loads the values into
 * temporary filesystem and filer variables.
 * @return -1: Unable to allocate memory for filer and volume infor
 * @return  0: Able to process element.
 */
static int
process_element() 
{

    static char fname[]="process_element()";  
    
    log_msg(MSG_DEBUG, "%s: endelement %s", fname, endelement);

    if (strcmp(endelement, "filer") == 0) {
       ftmp = calloc(1, sizeof(struct filer));
       if (ftmp == NULL) {
	    log_msg(MSG_ERR, "\
%s: failed allocate : %s",
		    fname, errstr);
	    return(-1);
	}
       ftmp->name = strdup(last_content);
       ftmp->readTime = time(NULL);
       log_msg(MSG_DEBUG, "%s: filer name %s", fname, ftmp->name); 
       return(0);
    }

    if (strcmp(endelement, "value") == 0) {
	ftmp->domains[dcnt] = atof(last_content); 
	log_msg(MSG_DEBUG, "%s: domain value %0.5f", fname, ftmp->domains[dcnt]);
	dcnt++;
	return(0);
    }

    if ((strcmp(endelement, "name") == 0) && (depth == 5)) {
       vtmp = calloc(1, sizeof(struct filesystem));
       if (vtmp == NULL) {
	    log_msg(MSG_ERR, "\
%s: failed allocate: %s",
		    fname, errstr);
	    return(-1);
	}

	vtmp->volume = strdup(last_content);
	vtmp->maxdiskbusy = tmp_maxdiskb;
	log_msg(MSG_DEBUG, "%s: volume  %s", fname, vtmp->volume);
	return(0);
    }

    if ((strcmp(endelement, "maxdiskb") == 0)) {
	tmp_maxdiskb =  atof(last_content);
	log_msg(MSG_DEBUG, "%s: maxdiskbusy %0.5f", fname, tmp_maxdiskb);
	return(0);
    }

    if ((strcmp(endelement, "avglatency") == 0)) {
	vtmp->avglatency = atof(last_content);
	log_msg(MSG_DEBUG, "%s: avglatency %0.5f", fname, vtmp->avglatency);
	return(0);
    }

    if ((strcmp(endelement, "availsize") == 0)) {
	vtmp->availsize = atof(last_content);
	log_msg(MSG_DEBUG, "%s: availsize %0.5f", fname, vtmp->availsize);
	return(0);	
    }

    if ((strcmp(endelement, "availinodes") == 0)) {
	vtmp->availinodes = atof(last_content);
	log_msg(MSG_DEBUG, "%s: availinodes %0.5f", fname, vtmp->availinodes);
	return(0);
    }

    if (strcmp(endelement, "domains") == 0) {
        hash_install(filertab, ftmp->name, ftmp); 
	log_msg(MSG_DEBUG, "%s: Installed filer record %s:", fname, ftmp->name);
	return(0);
    }

    if (strcmp(endelement, "volume") == 0) {
	sprintf(wbuf, "%s:/vol/%s", ftmp->name, vtmp->volume);
	hash_install(fstab, wbuf, vtmp);
	log_msg(MSG_DEBUG, "%s: Installed volume record %s %0.5f", fname, wbuf, vtmp->avglatency); 
	return(0);
    }

    return(0);
}

/*
 * print_list() - prints out the file volume list associated with 
 * a storage map name.  Used for debugging purposes.
 */
static void 
print_list(struct fvlist *ptr) 
{
    static char fname[]="print_list()";

    while (ptr != NULL) {
        log_msg(MSG_DEBUG, "%s: LIST: %s:%s", fname, ptr->filer, ptr->volname);
        ptr = ptr->next;
    }
} 

/*
 * print_fstab()  - prints the entire contents of the FSTAB
 * Used for debugging purposes only.
 */
static void print_fstab(void) 
{
    int i;
    struct nlist *np;
    struct filesystem *data;

    log_msg(MSG_DEBUG, "fstab->size %d\n", fstab->size);
    for (i=0; i< fstab->size; i++) {
      for (np = fstab->tab[i]; np != NULL; np = np->next) {
	      data = np->data;
	      if (data != NULL)
		log_msg(MSG_DEBUG, "%d: data volume %s maxdiskb %0.5f avglat %0.5f\n", i, data->volume, data->maxdiskbusy, data->avglatency);
      }
    }
}

/*
 * print_filertab() - prints the entire contents of FILERTAB
 * Used for debugging purposes only.
 */
static void 
print_filertab(void) {
    int i;
    struct nlist *np;
    struct filer *data;

    log_msg(MSG_DEBUG, "filertab->size %d\n", filertab->size);
    for (i=0; i< filertab->size; i++) {
        for (np = filertab->tab[i]; np != NULL; np = np->next) {
	    if (data != NULL) {
	        data = np->data;
		log_msg(MSG_DEBUG, "%d: data volume %s\n", i, data->name);
	    }
	}
    }
}

/*
 * print_filertab() - prints the entire contents of FILERTAB
 * Used for debugging purposes only.
 */
static void 
print_fptab(void) {
    int i;
    struct nlist *np;
    struct filerpol *data;

    log_msg(MSG_DEBUG, "filertab->size %d\n", fptab->size);
    for (i=0; i< fptab->size; i++) {
        for (np = fptab->tab[i]; np != NULL; np = np->next) {
	    if (data != NULL) {
	        data = np->data;
		log_msg(MSG_DEBUG, \
			"%d: data volume %s %f %f %f %f %f\n", \
			i, data->name, data->policy.maxdiskbusy, \
			data->policy.maxnedomain, data->policy.maxavgvollat, \
			data->policy.minsize, data->policy.mininodes);
	    }
	}
    }
}

/* test_hashlink()  - tests the link in the hash table for proper removal
 */
static void
test_fshashlink(char *name) 
{
    vtmp = calloc(1, sizeof(struct filesystem));
    vtmp->volume = strdup("test");
    vtmp->maxdiskbusy = 0.9;
    vtmp->avglatency = 1.0;
    hash_install_2(fstab, "fas6280c-svl10:/vol/nfs", vtmp);
    vtmp = calloc(1, sizeof(struct filesystem));
    vtmp->volume = strdup("test1");
    vtmp->maxdiskbusy = 0.91;
    vtmp->avglatency = 1.1;
    hash_install_2(fstab, "fas6280c-svl11:/vol/nfs1", vtmp);
    vtmp = calloc(1, sizeof(struct filesystem));
    vtmp->volume = strdup("test2");
    vtmp->maxdiskbusy = 0.92;
    vtmp->avglatency = 1.2;
    hash_install_2(fstab, "fas6280c-svl12:/vol/nfs2", vtmp);

    print_fstab();
    free_fs(name);
    print_fstab();
}

/* test_filerhashlink()  - tests the link in the filer table for proper removal
 */
static void
test_filerhashlink(void) 
{
    int i;
    ftmp = calloc(1, sizeof(struct filer));
    ftmp->name = strdup("fas6280c-svl10");
    for (i = 0; i < DOMAIN_SIZE; i++) 
      ftmp->domains[i] = i;

    hash_install_2(filertab, "fas6280c-svl10", ftmp);

    ftmp = calloc(1, sizeof(struct filer));
    ftmp->name = strdup("fas6280c-svl11");
    for (i = 0; i < DOMAIN_SIZE; i++) 
      ftmp->domains[i] = i;

    hash_install_2(filertab, "fas6280c-svl11", ftmp);

    ftmp = calloc(1, sizeof(struct filer));
    ftmp->name = strdup("fas6280c-svl12");
    for (i = 0; i < DOMAIN_SIZE; i++) 
      ftmp->domains[i] = i;

    hash_install_2(filertab, "fas6280c-svl12", ftmp);

    print_filertab();
    /* For free filer, need to set indx to 1 and commenting out hash */
    free_filer("fas6280c-svl12");
    print_filertab();
}

/* hash_install_2() - hashes to same location for testing purposes.
 */
static void *
hash_install_2(struct htab *ht,
	     const char *key, 
	     void *v)
{
    struct nlist   *np;
    unsigned int   hashval;

    np = calloc(1, sizeof(struct nlist));
    if (np == NULL)
	return(NULL);

    np->key = strdup(key);
    if (np->key == NULL) {
	free(np); /* K&R forgets to free it */
	return(NULL);
    }
    
    /*    hashval = hash(key, ht->size); */
    /* ah single linked list...
     */
    hashval = 1;
    np->next = ht->tab[hashval];
    ht->tab[hashval] = np;
    np->data = v;
    return(np->data);

} 

main() {

    int                  cc;
    int			 result;
    /* Read plugin configuration
     */

    cc = read_conf();
    if (cc < 0){
      printf("unable to read conf file \n");
      exit(1);
    }

    check_dirctr();
    result = filer_load_ok("test1");
    if (result == -1) 
      printf("Got a parsing error \n");
    else if (result == 1)
      printf("LOAD NOT OK\n");
    else
      printf("LOAD OK\n");

    printf("Sleeping \n");
    sleep(10);
    printf("Waking up \n");

    result = filer_load_ok("test1");
    if (result == -1) 
      printf("Got a parsing error \n");
    else if (result == 1)
      printf("LOAD NOT OK\n");
    else
      printf("LOAD OK\n");
    close_log();

}


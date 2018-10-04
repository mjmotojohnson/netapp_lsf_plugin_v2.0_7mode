/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */

/* Plugin system header file
 */
#ifndef _PLUGIN_SYS_H_
#define _PLUGIN_SYS_H_

#include "tools.h"

/* Configuration file sections
 */
#define PLUGIN_CONF     "ntapplugin.conf"
#define FILE_SYSTEMS    "exportnames"
#define PLUGIN_POLICY   "pluginpolicy"
#define PARAMETERS      "parameters"
#define FILER_POLICY	"filerpolicy"

/* Parameters keywords
 */
#define Debug         "Debug"
#define Work_Dir      "Work_Dir"
#define Events_File   "events"
#define Log_File      "ntapplugin.log"
#define Counter_Dir   "Counter_Dir"
#define XMLReread     "XMLReread"
#define DryRunMode    "DryRunMode"

/* Configuration 
 */
struct filesystags {
    char   mount[MAX_NAME_LEN];
    char   filer[PATH_MAX];
    char   fs[MAX_NAME_LEN]; 
};

/* Plugin parameters
 */
struct params {
    int    loglevel;
    char   workdir[PATH_MAX];
    char   counterdir[PATH_MAX];
    int	   xmlreread;
    int	   dryrun;
};


/* Load policy and runtime information
 */
struct loadpolicy {
    double   maxdiskbusy;
    double   maxnedomain;
    double   maxavgvollat;
    double   minsize;
    double   mininodes;
};

/* List of storage maps
 */
struct stormap {
    char *name;
    struct fvlist *vollist;
};

/* List of volumes for storage map
 */
struct fvlist {
    char *filer;
    char *volname;
    struct fvlist *next;
};

/*
 * name --> filer
 */
#define DOMAIN_SIZE 6

/* The filer
 */
struct filer {
    time_t		readTime;
    char                *name;
    double		domains[DOMAIN_SIZE];
};

/* The file system
 * name --> filer:/vol/volname
 */
struct filesystem {
    char                *volume;
    double		avglatency;
    double		maxdiskbusy;
    double		availsize;
    double		availinodes;
};

struct filerpol {
    char                *name;
    struct loadpolicy	policy;
};

extern int   read_conf(void);
extern int   filer_load_ok(const char *);
extern int   check_dirctr(void);
extern int   get_dryrun(void);
#endif 

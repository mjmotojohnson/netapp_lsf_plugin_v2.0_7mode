/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */

#include "tools.h"

static FILE   *logfp;
static char   buf[PATH_MAX];
static int    runlevel = MSG_INFO;

/* init_log()
 */
int
init_log(int level)
{
    runlevel = level;

    return(0);

} /* init_log() */

/* open_log() 
 */
int
open_log(const char *file)
{
    if (file == NULL) {
	/* Use default name and location 
	 * if the user did not configure
	 * the logfile.
	 */
	file = "/tmp/ntapplugin.log";
    }

    logfp = fopen(file, "a");
    if (logfp == NULL) {
      /* The directory may not exist and thus create file in /tmp 
       */
      logfp = fopen("/tmp/ntapplugin.log", "a");
      if (logfp == NULL)
	return(-1);
    }
    
    return(0);

} /* open_log() */

/* close_log() 
 */
void 
close_log(void)
{
    if (logfp)
	fclose(logfp);

    logfp = NULL;

} /* close_log() */

/* log_msg()
 */
int
log_msg(int level, const char *fmt, ...)
{
    va_list          ap;
    int              cc;
    struct timeval   tv;
    time_t           t;

    if (logfp == NULL)
	return(-1);
    
    /* Log msg only upto the current 
     * configured level.
     */
    if (level > runlevel)
	return(0);

    gettimeofday(&tv, NULL);
    t = tv.tv_sec;	
    fprintf(logfp, "\
%.15s:%-6d %d ", ctime(&t) + 4, tv.tv_usec, getpid()); 

    va_start(ap, fmt);
    cc = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    fprintf(logfp, "%s\n", buf);

    /* show me in the log file...
     */
    fflush(logfp);

    return(0);

} /* log_msg() */

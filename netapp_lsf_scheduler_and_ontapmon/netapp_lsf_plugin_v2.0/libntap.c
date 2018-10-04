/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */
#include"lssched.h"
#include<assert.h>
#include"tools.h"
#include "sysntap.h"

/* definition of handler ID 
 */
static const int HANDLER_ID = 18;

/* customer specific pending reason 
 */
#define PEND_FILER_LOAD    20002

int new_(void *);

int match(char *, void *, void *);

int sort(char *, void *, void *);

void free_(char *);

static int allocate(void *job, 
		    void * hostGroupList, 
		    void *reason, 
		    void **alloc);

static int notify(void *info,
		  void *job, 
		  void *alloc,
		  void *allocLimitList,
		  int  flag);

static char *getmount(char *);

/* This is the initialisation function used to register
 * the handler functions that will process the external 
 * resource requirement (-extsched) of the job.
 */
int 
sched_init(void *param)
{
    RsrcReqHandlerType   *handler;
    int                  cc;

    /* Read plugin configuration
     */
    cc = read_conf();
    if (cc < 0)
	return(-1);

    handler = calloc(1, sizeof(RsrcReqHandlerType));
    if (handler == NULL) {
        return (-1);
    }
    
    handler->newFn 
	= (RsrcReqHandler_NewFn)new_;
    handler->matchFn 
	= (RsrcReqHandler_MatchFn)match;
    handler->sortFn 
	= (RsrcReqHandler_SortFn)sort; 
    handler->notifyAllocFn
	= (RsrcReqHandler_NotifyAllocFn)notify;
    handler->freeFn 
	= (RsrcReqHandler_FreeFn)free_;
    
    lsb_resreq_registerhandler(HANDLER_ID, handler);

    lsb_alloc_registerallocator(allocate);

    return (0);

} /* sched_init() */

/* This function is invoked by the scheduler before
 * entering a scheduling session. 
 */
int
sched_pre_proc(void *p)
{
    return(0);

} /* sched_pre_proc() */

int
new_(void  *resreq)
{
    static char   fname[] = "new_()";
    char          **p;
    int           num;
    char          *s;

    if (resreq == NULL) {
        return(0);
    }

    p = lsb_resreq_getextresreq(resreq, &num);
    if (p == NULL || num == 0)
	return(0);

    s = strdup(p[1]);

    lsb_resreq_setobject(resreq, HANDLER_ID, s, NULL);

    return(0);

} /* new_() */

int
match(char *s,
      void *candGroupList, 
      void *reasonTb)
{
    return (0);

} /* match() */

int 
sort(char *s,
     void *candGroupList,
     void *reasonTb)
{
    return (0);

} /* sort() */

/*
 * allocate() - main part of handler that would check if specified volumes 
 * are above a certain threshold.
 * @return:
 * SCH_MOD_DECISCION_DISPATCH - continue job as normal
 * SCH_MOD_DECISION_NONE - ignore job
 * SCH_MOD_DECISION_PENDJOBS - place job on pending 
 * 
 */
static int
allocate(void *job, 
	 void *hostGroupList, 
	 void *reason, 
	 void **alloc)
{
    static char      fname[] = "allocate()";
    int              msgcnt;
    int              cc;
    struct jobInfo   *j;
    char             *mounts;
    char             **msg;
    char             *t;
    char	     *dryrun;
    int		     dryrunflag;
    if (lsb_alloc_type(*alloc) != SCH_MOD_DECISION_DISPATCH) {
        /* We only want to modify a dispatched alloction, 
	 * ignore other allocations. return 
	 */
        return(SCH_MOD_DECISION_NONE);
    }

    /* get user-specified resource requirement string, and decide whether
     * to continue.
     */
    msg = lsb_job_getextresreq(job, &msgcnt);
    if (msgcnt == 0 || msg == NULL) {
        /* do not need to do allocation for this job 
	 */
      log_msg(MSG_DEBUG, "MSG NULL\n");
        return(SCH_MOD_DECISION_NONE);
    }

    j = lsb_get_jobinfo(job, PHASE_ALLOC);
    log_msg(MSG_DEBUG, "\
%s: PHASE_ALLOC job %d index %d user %s queue %s", 
	    fname, j->jobId, j->jobIndex,
	    j->user, j->queue);

    
    /* Check for dry run flag passed. If dry run, do not do anything
     */
    dryrunflag = get_dryrun();
    dryrun = strstr(msg[1], "-n");
    if ((dryrun != NULL)  || (dryrunflag == 1)) 
        log_msg(MSG_INFO, "DRY RUN MODE");

    /* get the filer or file system
     */
    mounts = getmount(msg[1]);
    log_msg(MSG_DEBUG, "%s: storage map name %s", fname, mounts);

    if (mounts == NULL) {
        return(SCH_MOD_DECISION_NONE);
    }

    /* if directory with XML counter does not exist then just return*/
    if (check_dirctr()) {
	log_msg(MSG_DEBUG, "\
%s: filer plugin cannot get the load, all jobs SCH_MOD_DECISION_DISPATCH", fname);
	return(SCH_MOD_DECISION_NONE);
    }

    /* Now check the load condition of all mounts
     * if all are ok then we can give green light
     * otherwise either pend at least one mount 
     * not ok or decision none if unknown mount.
     */

    /* get a timestamp, read all the filer and volume info, and free the if timestamp stored is too old. (5s) */

    while ((t = get_next_token(&mounts))) {

        cc = filer_load_ok(t);
	switch (cc) {
	    case -1: 
		log_msg(MSG_DEBUG, "\
%s: unknown mount point %s for jobID %d SCH_MOD_DECISION_NONE",
			fname, t, j->jobId);
		return(SCH_MOD_DECISION_NONE);
	    case 1:
		if ((dryrun != NULL)  || (dryrunflag == 1)) {
		    log_msg(MSG_INFO, "\
%s: DRY RUN - filer load not ok jobID %d mount %s SCH_MOD_DECISION_PENDJOB",
			fname, j->jobId, t);

		    return(SCH_MOD_DECISION_NONE);
		} else { 
		    log_msg(MSG_DEBUG, "\
%s: filer load not ok jobID %d mount %s SCH_MOD_DECISION_PENDJOB",
			fname, j->jobId, t);
		    return(SCH_MOD_DECISION_PENDJOB);
		}
	    case 0:
	        if ((dryrun != NULL)  ||  (dryrunflag == 1))
		    log_msg(MSG_INFO, "\
%s: DRY RUN: filer load ok jobID %d mount %s SCH_MOD_DECISION_DISPATCH",
			fname, j->jobId, t);
		else
		    log_msg(MSG_DEBUG, "\
%s: filer load ok jobID %d mount %s SCH_MOD_DECISION_DISPATCH",
			fname, j->jobId, t);

		/* this mount is all right so let's
		 * move to the next one...
		 */
	}

    } /* end of while ((t = get_token())) */

    if ((dryrun != NULL)  || (dryrunflag == 1)) 
        return(SCH_MOD_DECISION_NONE);    
    else
        return(SCH_MOD_DECISION_DISPATCH);


} /* allocate() */

/* notify() 
 */
static int 
notify(void *info,
       void *job, 
       void *alloc,
       void *allocLimitList,
       int  flag)
{
    static char      fname[] = "notify()";
    struct jobInfo   *j;

    j = lsb_get_jobinfo(job, PHASE_NOTIFY);

    log_msg(LOG_DEBUG, "\
%s: PHASE_NOTIFY job %d index %d user %s queue %s", 
	    fname, j->jobId, j->jobIndex,
	    j->user, j->queue);

    return(0);

} /* notify() */

/* getfstag()
 * No need to wake up flex to parse
 * filer[xxx]
 */
static char *
getmount(char *msg)
{
    static char   buf[PATH_MAX];
    char          *x;
    char          *y;

    strcpy(buf, msg);

    x = strstr(buf, "filer");
    if (x == NULL)
      return(NULL);

    x = strchr(buf, '[');
    if (x == NULL)
	return(NULL);
    ++x;

    y = strchr(x, ']');
    if (y == NULL)
	return(NULL);
    *y = 0;

    return(x);

} /* getmount() */

void
free_(char *s)
{
 
} /* delete() */

int 
sched_order_alloc(void *p)
{

    return(0);

} /* sched_order_alloc() */

int
sched_post_proc(void *p)
{
    return(0);
    
} /* sched_post_proc() */

int
sched_version(void *p)
{
    return (0);

} /* sched_version() */

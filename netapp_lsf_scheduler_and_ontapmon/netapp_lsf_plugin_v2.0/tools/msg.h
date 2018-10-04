/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */
#if !defined(_LOG_MSG_)
#define _LOG_MSG_

/* Log message levels
 */
#define MSG_ERR     0x01
#define MSG_INFO    0x02
#define MSG_DEBUG   0x04

extern int   init_log(int);
extern int   open_log(const char *);
extern void  close_log(void);
extern int   log_msg(int, const char *, ...);

#endif /* _LOG_MSG_ */

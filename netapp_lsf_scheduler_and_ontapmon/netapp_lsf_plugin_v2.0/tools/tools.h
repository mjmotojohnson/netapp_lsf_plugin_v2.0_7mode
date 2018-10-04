/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */
/* Unix
 */
#ifndef _TOOLS_H_
#define _TOOLS_H_

#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <strings.h>
#include <limits.h>
#include <errno.h>
#include <time.h>
#include <sys/time.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <dirent.h>

#define freeit(p) \
{\
   if (p) \
     free(p); \
}

#define errstr (strerror(errno))

#define MAX_NAME_LEN   256

#include "tab.h"
#include "conf.h"
#include "msg.h"

#endif /* _TOOLS_H_ */

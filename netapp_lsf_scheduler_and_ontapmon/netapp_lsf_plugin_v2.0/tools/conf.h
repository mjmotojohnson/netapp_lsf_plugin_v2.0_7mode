/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */
#if !defined(_TOOLS_CONF_H_)
#define _TOOLS_CONF_H_
#include "tools.h"

extern char   *get_next_line(FILE *);
extern char   *get_begin_record(FILE *, const char *);
extern char   *get_record_until_end(FILE *, const char *, int *);
extern char   *get_next_token(char **);
#endif

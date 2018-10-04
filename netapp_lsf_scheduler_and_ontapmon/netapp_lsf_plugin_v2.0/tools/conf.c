/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */

#include "tools.h"

/* Local BUFSIZ
 */
#define LBUFSIZ   128

/* Da working buffer
 */
static char   buf[BUFSIZ];

static char *chop(char *);

/* Get the next meaningful line from the configuration
 * file, meaningful is a line that is not isspace()
 * and that does not start with a comment # character.
 */
char *
get_next_line(FILE *fp)
{
    static char  buf[BUFSIZ];
    char         *p;

    p = NULL;
    while (fgets(buf, BUFSIZ, fp)) {
        p = buf;
        while (isspace(*p))
            ++p;
        if (*p == '#'
            || *p == 0) {
	    /* If this is the last or only 
	     * line do not return the 
	     * previous buffer to the caller.
	     */
	    p = NULL;
            continue;
	}
        break;
    }

    return(chop(p));

} /* get_next_line() */

/* get_begin_record() 
 * Search file until <begin tag> is found.
 */
char *
get_begin_record(FILE *fp, const char *tag)
{
    char   name[LBUFSIZ];
    char   key[LBUFSIZ];

    while (fgets(buf, BUFSIZ, fp)) {

	sscanf(buf, "%s%s", name, key);

	if (strcasecmp(name, "begin") != 0)
	    continue;
	if (strcasecmp(key, tag) == 0)
	    return(buf);
    }

    return(NULL);

} /* get_begin_record() */

/* get_record_until_end() 
 */
char *
get_record_until_end(FILE *fp, const char *tag, int *found)
{
    char   name[LBUFSIZ];
    char   key[LBUFSIZ];
    
    *found = 0;
    while (fgets(buf, BUFSIZ, fp)) {
	
	sscanf(buf, "%s%s", name, key);

	if (strcasecmp(name, "end") != 0)
	    return(buf);
	/* begin found let's check the tag...
	 * if matches return NULL
	 */
	if (strcasecmp(key, tag) == 0) {
	    *found = 1;
	    return(NULL);
	}
    }

    return(NULL);

} /* get_record_until_end() */

/* get_next_token()
 * Return space separated tokens from a zero 
 * terminated string. Meant to be used in 
 * loop.
 */
char *
get_next_token(char **l)
{
    static char token[BUFSIZ];
    char        *p;

    p = token;

    while (isspace(**l))
	(*l)++;

    while (**l 
	   && !isspace(**l)) {
	*p++ = *(*l)++;
    }
    
    if (p == token)
	return(NULL);
    
    *p = '\0';

    return(token);

} /* get_next_token() */

/* Perl?
 */
static char *
chop(char *z)
{
    int   L;
    
    L = strlen(z);
    z[L - 1] = 0;

    return(z);

} /* chop() */

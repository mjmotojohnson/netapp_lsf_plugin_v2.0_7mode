/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */

#include<stdio.h>

int
main(int argc, char **argv)
{
    char   *p;
    char   *p0;
    char   *p1;
    char   *buf;
    char   ebuf[128];

    memset(ebuf, 0, sizeof(ebuf));

    buf = argv[1];

    /* first match filer
     */
    p = strstr(buf, "filer");
    if (p == NULL) {
	printf("filer not found\n");
	return(-1);
    }

    p0 = strchr(p, '[');
    p1 = strchr(p, ']');
    ++p0;
    *p1 = 0;
    
    strncpy(ebuf, p0, p1 - p0);
    
    printf("%s\n", ebuf);
    
    return(0);
}

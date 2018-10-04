/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */
#include "tools.h"

int
main(int argc, char **argv)
{
    struct htab   *ht;
    char          *names[] = {"david", "sofia", NULL};
    int           i;
    int           new;

    ht = hash_mk(0);
    
    i = 0;
    while (names[i]) {
	hash_install(ht, names[i], names[i], &new);
	printf("key %s new %d\n", names[i], new);
	++i;
    }
    i = 0;
    while (names[i]) {
	hash_install(ht, names[i], names[i], &new);
	printf("key %s new %d\n", names[i], new);
	++i;
    }

    while (names[i]) {
	if (hash_lookup(ht, names[i]))
	    printf("key %s\n", names[i]);
	++i;
    }

    return(0);
}

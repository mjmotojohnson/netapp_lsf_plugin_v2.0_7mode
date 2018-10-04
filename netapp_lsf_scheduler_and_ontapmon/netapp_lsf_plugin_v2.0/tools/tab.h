/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */
#ifndef _TOOLS_HTAB_
#define _TOOLS_HTAB_

struct htab {
    int            size;
    struct nlist   **tab;
};

struct nlist {
    struct nlist   *next;
    char           *key;
    void           *data;
};

extern struct htab *hash_mk(int);
extern unsigned int hash(const char *,
			 int size);
extern void        *hash_install(struct htab *, 
				 const char *, 
				 void *);

extern void        *hash_lookup(struct htab *, 
				const char *);

extern void        hash_free(struct htab *,
			     const char *);
			
#endif /* _TOOLS_HTAB_ */

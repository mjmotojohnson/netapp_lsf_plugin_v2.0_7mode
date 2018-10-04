/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */
#ifndef _TOOLS_LIST_
#define _TOOLS_LIST_

struct list_ {
    struct list_   *forw;
    struct list_   *back;
    int            num;
    char           *name;
};

#define LIST_NUM_ENTS(L) ((L)->num)

extern struct list_ *listmake(const char *);
extern int  listinsert(struct list_ *,
		       struct list_ *,
		       struct list_ *);
extern int listpush(struct list_ *,
		    struct list_ *);
extern int listenque(struct list_ *,
		     struct list_ *);
extern struct list_ * listrm(struct list_ *,
			     struct list_ *);
struct list_ *listpop(struct list_ *);
extern struct list_ *listdeque(struct list_ *);
extern void listfree(struct list_ *, void (*f)(void *));

#endif /* _TOOLS_LIST_ */

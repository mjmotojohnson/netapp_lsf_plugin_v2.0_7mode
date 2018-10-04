/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */
#include"tools.h"

struct list_ *
listmake(const char *name)
{
    struct list_   *L;

    L = calloc(1, sizeof(struct list_));
    assert(L);
    L->forw = L->back = L;

    L->name = strdup(name);
    assert(L->name);

    return(L);
    
} /* listmake() */

/* Insert e2 after e
 * 
 *  e2 <-> e <-> h
 *
 *  or
 *
 *  h <-> e <-> e2
 *
 */
int
listinsert(struct list_ *h,
	    struct list_ *e,
	    struct list_ *e2)
{
    assert(h && e && e2);

    e->back->forw = e2;
    e2->back = e->back;
    e->back = e2;
    e2->forw = e;

    h->num++;

    return(h->num);

} /* listinsert() */

/* Push at front...
 */
int 
listpush(struct list_ *h,
	  struct list_ *e)
{
    assert(h && e);

    listinsert(h, h, e);

    return(0);

} /* listpush() */

/* Enqueue at end
 */
int 
listenque(struct list_ *h,
	   struct list_ *e)
{
    listinsert(h, h->forw, e);

    return(0);

} /*listenqueue */

struct list_ *
listrm(struct list_ *h,
	struct list_ *e)
{
    if (h->num == 0)
	return(NULL);

    e->back->forw = e->forw;
    e->forw->back = e->back;
    h->num--;

    return(e);

} /* listrm() */

/* pop from front
 */
struct list_ *
listpop(struct list_ *h)
{
    struct list_   *e;

    if (h->forw == h) {
	assert(h->back == h);
	return(NULL);
    }

    e = listrm(h, h->back);

    return(e);

} /* listpop() */

/* dequeue from the end
 */
struct list_ *
listdeque(struct list_ *h)
{
    struct list_   *e;

    if (h->forw == h) {
	assert(h->back == h);
	return(NULL);
    }

    e = listrm(h, h->forw);

    return(e);

} /* listdeque() */

void
listfree(struct list_ *L,
	 void (*f)(void *))
{
    struct list_   *l;

    while ((l = listpop(L))) {
	if (f == NULL)
	    free(l);
	else
	    (*f)(l);	
    }

    free(L->name);
    free(L);

} /* listfree()*/

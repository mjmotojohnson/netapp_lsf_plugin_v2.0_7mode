/*
 * Copyright (c) 2005-2012 NetApp, Inc.
 * All rights reserved.
 */
/* ANSI C K&R 
 */
#include "tools.h"

static int primes[] = 
{269, 1481, 2011, 3331, 4219, 5507, 10079, 33427, 999979}; 


unsigned int   hash(const char *, int);
static struct nlist   *hash_lookupent(struct htab *,
				      const char *);

/* hash_init()
 */
struct htab *
hash_mk(int size)
{
    struct htab   *ht;
    int           psize;
    int           i;

    psize = primes[sizeof(primes)/sizeof(primes[0]) - 1];
    for (i = 0; i < sizeof(primes)/sizeof(primes[0]); i++) {
	if (primes[i] > size) {
	    psize = primes[i];
	    break;	    
	}
    }

    /* Modified this to only alloc 1 instead of size, because this
     * structure will eventually point to a table of size psize
     */
    ht = calloc(1, sizeof(struct htab));
    if (ht == NULL)
	return(NULL);

    ht->tab = calloc(psize, sizeof(struct nlist **));
    ht->size = psize;

    return(ht);

} /* hash_init() */

/* hash_install()
 */
void  *
hash_install(struct htab *ht,
	     const char *key, 
	     void *v)
{
    struct nlist   *np;
    unsigned int   hashval;

    np = hash_lookupent(ht, key);
    if (np) {
	/* this is the policy duplicates 
	 * are overwritten.
	 */
	log_msg(MSG_INFO, "Found duplicate key %s in install.\n", key);
	np->data = v;
	return(v);
    }
    
    np = calloc(1, sizeof(struct nlist));
    if (np == NULL)
	return(NULL);

    np->key = strdup(key);
    if (np->key == NULL) {
	free(np); /* K&R forgets to free it */
	return(NULL);
    }
    
    hashval = hash(key, ht->size);
    /* ah single linked list...
     */
    np->next = ht->tab[hashval];
    ht->tab[hashval] = np;
    np->data = v;
    return(np->data);

} /* hash_install() */

/* hash_lookup()
 */
void  *
hash_lookup(struct htab *ht,
	    const char *key)
{
    struct nlist   *np;

    np = hash_lookupent(ht, key);
    if (np == NULL)
	return(NULL);

    return(np->data);

} /* hash_lookup() */

/* hash()
 */
unsigned int
hash(const char *key, int size)
{
    unsigned int hashval;

    for (hashval = 0; *key != 0; key++) 
	hashval = *key + 31 * hashval;
    return(hashval % size);

} /* hash() */

/* hash_lookupent() 
 */
static struct nlist *
hash_lookupent(struct htab *ht,
	       const char *key)
{
    struct nlist   *np;

    for (np = ht->tab[hash(key, ht->size)]; 
	 np != NULL; 
	 np = np->next) {

	if (strcmp(np->key, key) == 0) 
	    return(np);
    }

    return(NULL);

} /* hash_lookupent() */


#
#
CC = gcc -g -fPIC
OBJS = conf.o tab.o msg.o 
LIBTOOLS = libtools.a 
CFLAGS = -I. -I../ -I./expat-2.0.1/lib
LIBEXPAT = expat-2.0.1/.libs/libexpat.a

all : $(LIBTOOLS) 

libtools.a : $(OBJS)
	ar r $@ $^ 

conf.o : conf.c conf.h
	$(CC) -c $^
tab.o : tab.c tab.h
	$(CC) -c $^
msg.o : msg.c msg.h
	$(CC) -c $^

$(OBJS) : tools.h 

# Standalone program to test sysntap.c
$(LIBEXPAT) : expat-2.0.1/*.[hc]
	cd expat-2.0.1; ./configure --with-pic; $(MAKE) 

p2: p2.o $(LIBTOOLS) $(LIBEXPAT)
	$(CC) -o $@ $^ $(LIBTOOLS) $(LIBEXPAT)

p2.o : p2.c 
	$(CC) $(CFLAGS) -c $^


clean:
	rm -f $(OBJS) $(LIBTOOLS) main *.gch *.o 

realclean:
	rm -f $(OBJS) $(LIBTOOLS) main *.gch *.o *~ 

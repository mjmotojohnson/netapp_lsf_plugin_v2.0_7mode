# make make make
#
CC = gcc -ggdb
CFLAGS = -I/usr/share/lsf/8.0/include/lsf -fPIC -I./tools
LDFLAGS = -shared 
LIBS = -lm 
PLUGIN = schmod_netapp.so
TOOLS = tools/libtools.a 
LIBEXPAT = tools/expat-2.0.1/.libs/libexpat.a

all : $(PLUGIN) 

$(PLUGIN) : libntap.o sysntap.o $(TOOLS) $(LIBEXPAT)
	$(CC) $(LDFLAGS) -o $@ $^ $(LIBS)

libntap.o: libntap.c
	$(CC) $(CFLAGS) -c $^

sysntap.o : sysntap.c 
	$(CC) $(CFLAGS) -c $^

$(TOOLS) : tools/*.[hc] 
	cd tools; $(MAKE)

$(LIBEXPAT) : tools/expat-2.0.1/*.[hc]
	cd tools/expat-2.0.1; ./configure --with-pic; $(MAKE) 


sysntap.o : sysntap.h 

etags: 
	etags *.[hc] tools/*.[hc]

clean :
	rm -f *.o $(PLUGIN) *.gch
	cd tools; $(MAKE) clean
	cd tools/expat-2.0.1; $(MAKE) clean

realclean:
	rm -f *.o $(PLUGIN) *.gch *~
	cd tools; $(MAKE) realclean
	cd tools/expat-2.0.1; $(MAKE) extraclean
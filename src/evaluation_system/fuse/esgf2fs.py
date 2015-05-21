import os
import re
import errno
import threading
import logging
import grp

from stat import S_IFDIR, S_IFREG, S_IREAD, S_IWRITE, S_IRGRP, S_IWGRP
from sys import argv, exit
from time import time, sleep,mktime
from subprocess import call
from datetime import datetime
from subprocess import Popen, PIPE

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

from evaluation_system.model.esgf import P2P
from evaluation_system.misc import config
from esgf_crawl_config import Solr2EsgfConfig


logging.getLogger().setLevel(logging.INFO)

class EsgfFuse(Operations):
    def __init__(self):
        
        self.logcache = config.get('esgf_logcache')
        self.esgftmp = '%s/%s/' % (self.logcache,'ESGF_CACHE')
        self.logpath = '%s/%s/' % (self.logcache,'ESGF_LOG')
        
        self.wgetlog = 'wget_raw.log'
        self.downlog = 'download_error.log'
        self.certs   = config.get('private_key')
        self.wget    = config.get('wget_path')
          
        self.threadLimiter = threading.BoundedSemaphore(5)
        
        self.gid = grp.getgrnam("bmx828").gr_gid
        try:
            os.makedirs(self.logpath,775)
        except OSError as exception:
            if exception.errno != errno.EEXIST: raise
        try:
            file(self.logpath+self.wgetlog,'a+').close()
            os.chown(self.logpath+self.wgetlog, -1,self.gid)
            os.chmod(self.logpath+self.wgetlog,S_IREAD|S_IWRITE|S_IRGRP|S_IWGRP)
             
            file(self.logpath+self.downlog,'a+').close()
            os.chown(self.logpath+self.downlog, -1,self.gid)
            os.chmod(self.logpath+self.downlog,S_IREAD|S_IWRITE|S_IRGRP|S_IWGRP)
        except IOError as e:
            pass
            
    def get_url(self,path,p2p=P2P(node='pcmdi9.llnl.gov')):
        
        esgfpath,filename  = os.path.split(path)
        try: 
            project,product,institute,model,experiment,\
            time_frequency,realm,variable,ensemble=esgfpath[1:].split('/')
        except ValueError:
            print 'PATH: '+path
            print 'PATH structure is not supported'
            return
         
        cmor_path = Solr2EsgfConfig().project_select(esgfpath, filename)
        fields = ['url','size','timestamp']
        print path
        print cmor_path 
        facets = {'project'        : cmor_path['project'],
                  'type'           : 'File',
                  'product'        : cmor_path['product'],
                  'institute'      : cmor_path['institute'],
                  'experiment'     : cmor_path['experiment'],
                  'time_frequency' : cmor_path['time_frequency'],
                  'realm'          : cmor_path['realm'],
                  'variable'       : cmor_path['variable'],
                  'ensemble'       : cmor_path['ensemble'],
                  'title'          : cmor_path['filename']
                  }
        timestamp = 0
        for ncfile in p2p.get_datasets(fields=','.join(fields),**facets):
            url = [url for url in ncfile['url'] if 'application/netcdf' in url][0]
            if mktime((datetime.strptime(ncfile['timestamp'],'%Y-%m-%dT%H:%M:%SZ')).timetuple()) >= timestamp:
                timestamp = mktime((datetime.strptime(ncfile['timestamp'],'%Y-%m-%dT%H:%M:%SZ')).timetuple())
                size = int(ncfile['size'])
        url = url.split('|')[0]
        
        try:
            return url,size
        except UnboundLocalError:
            print 'PATH: '+path
            print 'No url for this PATH'
             
         
    def download(self,esgfpath,path,httppath,filename):
        self.threadLimiter.acquire()
        try:
            try:
                 with open(self.esgftmp+path+'.lock') as testfile: pass
            except IOError as e:
                    file(self.esgftmp+path+'.lock','w').close()
                    command = self.wget+" --no-check-certificate -O "+self.esgftmp+esgfpath+'/'+filename+\
                                        " --secure-protocol=TLSv1 --certificate "+self.certs+" --private-key "+\
                                        self.certs+' '+httppath
                    process = Popen(command, shell=True, stdout=PIPE, stderr=PIPE)
                    stderr   = file(self.logpath+self.wgetlog,'a+')
                    download = file(self.logpath+self.downlog,'a+') 
                    for line in process.stderr:
                        stderr.write(line) 
                        if 'OpenSSL: error:' in line:
                            download.write('Certificate Error:\n')
                            download.write('URL: '+httppath+'\n')
                    stderr.close()
                    download.close()
                    process.wait()    
                    os.remove(self.esgftmp+path+'.lock')
        finally:
            self.threadLimiter.release()
                         
    def getattr(self, path, fh=None):
        filepath,extension = os.path.splitext(path)
        st = dict(st_mode=(S_IFDIR | 0755), st_nlink=2)
        if extension == '.nc':
            try:
                st = dict(st_mode=(S_IFREG | 0444), st_size=self.get_url(path)[1])
            except TypeError:
                print 'PATH: '+path
                print 'No size for this PATH'
        st['st_ctime'] = st['st_mtime'] = st['st_atime'] = time()
        return st
         
        
    
    def open(self, path,fh):
               
        esgfpath,filename = os.path.split(path)
        sleep(0.1)
        httppath,_ =self.get_url(path)
        # create directories recursively       
        try:
            os.makedirs(self.esgftmp+esgfpath,0775)
            [os.chown(dir, -1, 1000) for root, dirs, _ in os.walk(self.esgftmp+esgfpath) for dir in dirs]
            [os.chmod(os.path.join(root,dir),S_IREAD|S_IWRITE|S_IRGRP|S_IWGRP) for root, dirs, _ in os.walk(self.esgftmp+esgfpath) for dir in dirs]
        except OSError as exception:
            if exception.errno != errno.EEXIST: raise
        try: # look for lock file - lock file = signal for download
                 with open(self.esgftmp+path+'.lock') as testfile:pass
        except IOError as e:
            try:
                with open(self.esgftmp+path) as testfile: pass
                return fh
            except IOError as e:
                self.download(esgfpath,path,httppath,filename)
                return fh
               
    
    def read(self, path, length, offset,fh):
        try:
            with open(self.esgftmp+path+'.lock') as testfile:pass
            self.open(path,fh)
        except IOError:
            try:
                with open(self.esgftmp+path) as f:
                    f.seek(offset, 0)
                    buf = f.read(length)
                    f.close()
                    return buf
            except IOError:
                self.open(path, fh)
    
    readdir = None
    access = None
    flush = None
    getxattr = None
    listxattr = None
    opendir = None
    releasedir = None
    statfs = None
    release = None

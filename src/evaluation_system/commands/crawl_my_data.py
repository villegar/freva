# encoding: utf-8

'''
crawl_my_data - Sets path to crawl a useres data

@copyright:  2015 FU Berlin. All rights reserved.
        
@contact:    sebastian.illing@met.fu-berlin.de
'''

import sys, os, time
from evaluation_system.commands import FrevaBaseCommand
from evaluation_system.model.user import User
import logging
from evaluation_system.model.solr_models.models import UserCrawl
from evaluation_system.misc import config
import subprocess

class Command(FrevaBaseCommand):
 
   # _short_args = 'hd'
   # _args = ['path=', 'debug', 'help']
    __short_description__ = '''Use this command to update your projectdata.'''
    __description__ = __short_description__
   
    _args = [
             {'name':'--debug','short':'-d','help':'turn on debugging info and show stack trace on exceptions.','action':'store_true'},
             {'name':'--help','short':'-h', 'help':'show this help message and exit','action':'store_true'},
             {'name':'--path','help':'crawl the given directory', 'metavar':'PATH'},
             ]   
    
    def _run(self):
        #root_path =  config.get('project_data')
        root_path = '/miklip/integration/data4miklip/projectdata/'
        # Setup argument parser
        args = self.args
        crawl_dir=args.path
        
        t1 = time.time()        
        sys.stderr.flush()
        user_root_path = os.path.join(root_path,User().getName()) 
        if crawl_dir:
            if(not root_path in crawl_dir):
                raise Exception('You are only allowed to crawl data in this root path %s' % root_path)
        else:
            crawl_dir = user_root_path
        path = os.path.dirname(os.path.abspath(__file__))
        script_path = path + '/../../../sbin/crawl_data'
        print 'Please wait while the system is crawling your data'
        out = subprocess.Popen('/bin/bash '+script_path + ' ' + crawl_dir, shell=True)
        print out.wait()
        print 'Finished.\nCrawling took ' + str(time.time() - t1) + ' seconds'


if __name__ == "__main__":
    Command().run()

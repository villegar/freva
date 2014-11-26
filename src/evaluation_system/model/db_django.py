'''
.. moduleauthor:: estani <estanislao.gonzalez@met.fu-berlin.de>

This modules encapsulates all access to databases.
'''
import history.models as hist
import plugins.models as pin

from django.contrib.auth.models import User

from datetime import datetime
import json
import ast
import os
import re
import logging
from evaluation_system.misc import py27, config
from evaluation_system.model import repository_git
log = logging.getLogger(__name__)

import evaluation_system.settings.database


class HistoryEntry(object):
    """This object encapsulates the access to an entry in the history DB representing an analysis
the user has done in the past."""
    TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S.%f'
    """This timestamp format is used for parsing times when referring to a history entry and displaying them.""" 
    
    @staticmethod
    def timestampToString(datetime_obj):
        """This is the inverse of :class:`HistoryEntry.timestampFromString`. The formatting is defined by
:class:`TIMESTAMP_FORMAT`.

:returns: a string as formated out of a (:py:class:`datetime.datetime`) object.""" 
        return datetime_obj.strftime(HistoryEntry.TIMESTAMP_FORMAT)
    
    @staticmethod
    def timestampFromString(date_string):
        """This is the inverse of :class:`HistoryEntry.timestampToString`. The parsing is defined by
:class:`TIMESTAMP_FORMAT` and every sub-set of it generated by dropping the lower resolution time
values, e.g. dropping everything with a higher resolution than minutes (i.e. dropping seconds and microseconds).

:returns: a (:py:class:`datetime.datetime`) object as parsed from the given string.""" 
        tmp_format = HistoryEntry.TIMESTAMP_FORMAT
        while tmp_format:
            try:
                return datetime.strptime(date_string, tmp_format)
            except:
                pass
            tmp_format = tmp_format[:-3]    #removing last entry and separator (one of ' :-')
        raise ValueError("Can't parse a date out of '%s'" % date_string)
    
    def __init__(self, row):
        """Creates an entry out of the row returned by a DB proxy.

:param row: the DB row for which this entry will be created.
"""
	#print len(row)
        self.rowid = row[0]
        self.timestamp = str(row[1]) #datetime object
        self.tool_name = row[2]
        self.version = ast.literal_eval(row[3]) if row[3] else (None,None,None)
        self.configuration = json.loads(row[4]) if row[4] else {}
        self.results = []#json.loads(row[5]) if row[5] else {}
        self.slurm_output = row[5]
        self.uid = row[6]
        self.status = row[7]
        self.flag = row[8]
        self.version_details_id = row[9]
        
    def toJson(self):
        return json.dumps(dict(rowid=self.rowid, timestamp=self.timestamp.isoformat(), tool_name=self.tool_name,
             version=self.version, configuration=self.configuration, results=self.results,status=self.status))
        
    def __eq__(self, hist_entry):
        if isinstance(hist_entry, HistoryEntry):
            return self.rowid == hist_entry.rowid and self.timestamp == hist_entry.timestamp and \
                    self.tool_name == hist_entry.tool_name and self.version == hist_entry.version and \
                    self.configuration == hist_entry.configuration
    def __str__(self, compact=True):
        if compact:
            out_files = []
            for f in self.results:
                out_files.append(os.path.basename(f))
            conf_str = ', '.join(out_files) + ' ' + str(self.configuration)
            if len(conf_str) > 70:
                conf_str = conf_str[:67] + '...'
            version = '' 
        else:
            items = ['%15s=%s' % (k,v) for k,v in sorted(self.configuration.items())]
            if items:
                #conf_str = '\n' + json.dumps(self.configuration, sort_keys=True, indent=2)
                conf_str = '\nConfiguration:\n%s' % '\n'.join(items)
            if self.results:
                out_files = []
                for out_file, metadata in self.results.items():
                    status = 'deleted'
                    if os.path.isfile(out_file):
                        if 'timestamp' in metadata and os.path.getctime(out_file) - metadata['timestamp'] <= 0.9:
                            status = 'available'
                        else:
                            status = 'modified' 
                    out_files.append('  %s (%s)' % (out_file, status))
                conf_str = '%s\nOutput:\n%s' % (conf_str, '\n'.join(out_files))
                    
                    

            version = ' v%s.%s.%s' % self.version
            
        
        return '%s) %s%s [%s] %s' % (self.rowid, self.tool_name, version, self.timestamp, conf_str)
        

class HistoryResultEntry(object):
    """
    This class encapsulates the access to the results.
    """
    def __init__(self, row):
        self.id = row[0]
        self.history_id_id = row[1]
        self.output_file = row[2]
        self.preview_file = row[3]
        self.filetype = row[4]

        
class HistoryTagEntry(object):
    """
    This class encapsulates the access to the HistoryTag entries.
    """
    def __init__(self, row):
        self.id = row[0]
        self.history_id_id = row[1]
        self.type = row[2]
        self.uid = row[3]
        self.text = row[4]
        
class UserDB(object):
    '''Encapsulates access to the local DB of a single user.

The main idea is to have a DB for storing the analysis runs.
At the present time the DB stores who did what when and what resulted out of it.
This class will just provide the methods for retrieving and storing this information.
There will be no handling of configuration in here.

Furthermore this class has a schema migration functionality that simplifies modification
of the DB considerably without the risk of loosing information.'''
    __tables = {'meta': {1:['CREATE TABLE meta(table_name text, version int);',
                            "INSERT INTO meta VALUES('meta', 1);"],
                         2: ['ALTER TABLE meta ADD COLUMN description TEXT;',
                             "INSERT INTO meta VALUES('meta', 2, 'Added description column');"]},    
                'history': {1: ['CREATE TABLE history(timestamp timestamp, tool text, version text, configuration text);',
                                "INSERT INTO meta VALUES('history', 1);"],
                            2: ["ALTER TABLE history ADD COLUMN result text;",
                                "INSERT INTO meta VALUES('history', 2, 'Added ');"]},
                '__order' : [('meta', 1), ('history', 1), ('meta', 2), ('history', 2)]}
    """This data structure is managing the schema Upgrade of the DB.
    The structure is: {<table_name>: {<version_number>:[list of sql cmds required]},...
                        __order: [list of tuples (<tble_name>, <version>) marking the cronological
                                        ordering of updates]"""
                                        

        

    def __init__(self, user):
        '''As it is related to a user the user should be known at construction time.
Right now we have a descentralized sqllite DB per user stored in their configuration directory.
This might (and will) change in the future when we move to a more centralized architecture,
but at the present time the system works as a toolbox that the users start from the console.

:param user: the user this DB access relates to.
:type user: :class:`evaluation_system.model.user.User`
'''
        self._user = user
        #self._db_file = user.getUserConfigDir(create=True) + '/history.sql3'
        self._db_file = config.get(config.DATABASE_FILE, "")
        #print self.db_file
        self.initialize()
    
    
    def initialize(self, tool_name=None):
        """If not already initialized it will performed the required actions.
There might be differences as how tools are initialized (maybe multiple DBs/tables),
so if given, the initialization from a specific tool will be handled.
While initializing the schemas will get upgraded if required.

:param tool_name: name of the tool whose DB/table will get initialized. We are not using
                  this at this time, but to keep the DB as flexible as possible please provide this
                  information if available."""
        if not self.isInitialized():
            #well we need to walk throw history and replay what's missing. We assume a monotone increasing timeline
            #so when the first missing step is found, it as well as all the remining ones need to be replayed.
            #in order to update this DB state to the latest known one.
            for table_name, version in self.__tables['__order']:
                db_perform_update_step = True
                try:
                    (cur, tmp) = self.safeExecute('SELECT * FROM meta WHERE table_name = %s AND version = %s', (table_name, version))
                    res = cur.fetchone()
                    cur.close()
                    if res:
                        #the expected state is done, so just skip it 
                        db_perform_update_step = False
                except Exception as e:
                    if table_name == 'meta' and version == 1:
                        #this means we don't even have the meta table in there... no problem,
                        log.debug('Creating DB for the first time')
                    else:
                        #something went wrong
                        log.error("Can't update DB: %s", e)
                if db_perform_update_step: 
                    #we need to perform this update step
                    log.debug('Updating %s to version %s', table_name, version)
                    for sql_item in self.__tables[table_name][version]:
                        log.debug('Updating Schema: %s', sql_item)
                        (cur, res) = self.safeExecute(sql_item)
                        cur.close()
    
    def isInitialized(self):
        """:returns: (bool) If this DB is initialized and its Schema up to date."""
#        try:
#            rows = self._getConnection().execute("SELECT table_name, max(version) FROM meta GROUP BY table_name;").fetchall()
#            if not rows or rows[0] is None or rows[0][0] is None: return False
#            tables = set([item[0] for item in rows])    #store the table names found
#            for row in rows:
#                table_name, max_version = row
#                if table_name in self.__tables and max(self.__tables[table_name]) > max_version:
#                    return False 
#            return not bool(tables.difference([table for table in self.__tables if not table.startswith('__')]))
#        except:
#            return False
        return True
        
    def storeHistory(self, tool, config_dict, uid, status,
                     slurm_output = None, result = None, flag = None, version_details = None):
        """Store a an analysis run into the DB.

:type tool: :class:`evaluation_system.api.plugin.pluginAbstract`
:param tool: the plugin for which we are storing the information.
:param config_dict: dictionary with the configuration used for this run,
:param uid: the user id (useful in a global database)
:param status: the process status
:param result: dictionary with the results (created files).
"""
        if result is None: result = {}
        if slurm_output is None: slurm_output = 0
        if flag is None: flag = 0
        if version_details is None: version_details = 1
        
        newentry = hist.History(timestamp =  datetime.now(),
                                tool = tool.__class__.__name__.lower(),
                                configuration = json.dumps(config_dict),
                                slurm_output = slurm_output,
                                uid_id = uid,
                                status = status,
                                flag = flag)
        
        newentry.save()
                
        return newentry.id

    def scheduleEntry(self, row_id, uid, slurmFileName):
        """
        :param row_id: The index in the history table
        :param uid: the user id
        :param slurmFileName: The slurm file belonging to the history entry
        Sets the name of the slurm file 
        """
        
        h = hist.History.objects.get(id=row_id,
                                     uid_id=uid,
                                     status=hist.History.processStatus.not_scheduled)
        
        h.slurm_output = slurmFileName
        h.status = hist.History.processStatus.scheduled
        
        h.save()
        
        
    class ExceptionStatusUpgrade(Exception):
        """
        Exception class for failing status upgrades
        """
        def __init__(self, msg="Status could not be upgraded"):
            super(UserDB.ExceptionStatusUpgrade, self).__init__(msg)
        
        
    def upgradeStatus(self, row_id, uid, status):
        """
        :param row_id: The index in the history table
        :param uid: the user id
        :param status: the new status 
        After validation the status will be upgraded. 
        """

        h = hist.History.objects.get(pk=row_id,
                                     uid_id=uid)
                
        if(h.status < status):
            raise self.ExceptionStatusUpgrade('Tried to downgrade a status')
        
        h.status = status
        
        h.save()
        
        
    def changeFlag(self, row_id, uid, flag):
        """
        :param row_id: The index in the history table
        :param uid: the user id
        :param flag: the new flag 
        After validation the status will be upgraded. 
        """
        
        h = hist.History.objects.get(id = row_id, uid_id = uid)
        
        h.flag = flag
        
        h.save()
        
        
    def getHistory(self, tool_name=None, limit=-1, since=None, until=None, entry_ids=None, uid=None):
        """Returns the stored history (run analysis) for the given tool.

:type tool_name: str
:param tool_name: name of the tool for which the information will be gathered (if None, then everything is returned).
:type limit: int
:param limit: Amount of rows to be returned (if < 0, return all).
:type since: datetime.datetime
:param since: Return only items stored after this date
:type until: datetime.datetime
:param until: Return only  items stored before this date
:param entry_ids: ([int] or int) id or list thereof to be selected
:returns: ([:class:`HistoryEntry`]) list of entries that match the query.
"""
        #print uid
        #ast.literal_eval(node_or_string)
        sql_params = []

	filter_dict = {}

        o = None

        sql_str = "SELECT * FROM history_history"
        if entry_ids is not None:
            if isinstance(entry_ids, int): entry_ids=[entry_ids]
            filter_dict['id__in'] = entry_ids

        if tool_name is not None:
            filter_dict['tool'] = tool_name

        if since is not None:
            filter_dict['timestamp__gte'] = since

        if until is not None:
            filter_dict['timestamp__lte'] = until

        if uid is not None:
            filter_dict['uid_id'] = uid

        o = hist.History.objects.filter(**filter_dict).order_by('-id')

        if limit > 0:
             o=o[:limit]

        return o
                    
    def addHistoryTag(self, hrowid, tagType, text, uid=None):
        """
        :type hrowid: integer
        :param hrowid: the row id of the history entry where the results belong to
        :type tagType: integer 
        :param tagType: the kind of tag
        :type: text: string
        :param: text: the text belonging to the tag
        :type: uid: string
        :param: uid: the user, default: None
        """
        
        data_to_store = []
        insert_string = ''
        
        h = hist.HistoryTag(history_id_id = hrowid,
                            type = tagType,
                            text = text)
        
        if not uid is None:
            h.uid_id = uid
            
        h.save()
        
                
         
    class ExceptionTagUpdate(Exception):
        """
        Exception class for failing status upgrades
        """
        def __init__(self, msg="Tag not found"):
            super(UserDB.ExceptionTagUpdate, self).__init__(msg)
        

    def updateHistoryTag(self, trowid, tagType=None, text=None, uid=None):
        """
        :type trowid: integer
        :param trowid: the row id of the tag
        :type tagType: integer 
        :param tagType: the kind of tag
        :type: text: string
        :param: text: the text belonging to the tag
        :type: uid: string
        :param: uid: the user, default: None
        """
        
        data_to_store = []
        insert_string = ''
        
        h = hist.HistoryTag.objects.get(id=trowid,
                                        uid_id = uid)
        
        if not tagType is None:
            h.type = tagType
                
        if not text is None:
            h.text = text

        h.save()
    
    def storeResults(self, rowid, results):
        """
        :type rowid: integer
        :param rowid: the row id of the history entry where the results belong to
        :type results: dict with entries {str : dict} 
        :param results: meta-dictionary with meta-data dictionaries assigned to the file names.
        """
        
        data_to_store = []
        reg_ex = None

        # regex to get the relative path
        preview_path = config.get(config.PREVIEW_PATH, None)
        expression = '(%s\\/*){1}(.*)' % re.escape(preview_path)

        # only try to create previews, when a preview path is given
        if preview_path:
            reg_ex = re.compile(expression)

        for file_name in results:
            metadata = results[file_name]
            
            type_name = metadata.get('type','')
            type_number = hist.Result.Filetype.unknown
            
            preview_path = metadata.get('preview_path', '')
            preview_file = ''

            if preview_path and not reg_ex is None:
                # We store the relative path for previews only.
                # Which allows us to move the preview files to a different folder.
                preview_file = reg_ex.match(preview_path).group(2)
                        
            if type_name == 'plot':
                type_number = hist.Result.Filetype.plot
            elif type_name == 'data':
                type_number = hist.Result.Filetype.data
                
                
            h = hist.Result(history_id_id=rowid,
                            output_file=file_name,
                            preview_file=preview_file,
                            file_type=type_number)
            
            h.save()
            
            result_id = h.pk
            self._storeResultTags(result_id, metadata)

    def _storeResultTags(self, result_id, metadata):
        """
        :type result_id: integer
        :param result_id: the id of the result entry where the tag belongs to
        :type metadata: dict with entries {str : dict} 
        :param metadata: meta-dictionary with meta-data dictionaries assigned to the file names.
        """
        
        data_to_store = []


        # append new tags here        
        caption = metadata.get('caption', None)

        if caption:
            data_to_store.append(hist.ResultTag(result_id_id=result_id,
                                                type=hist.ResultTag.flagType.caption,
                                                text=caption))
                        
        hist.HistoryTag.objects.bulk_create(data_to_store)
        
        
    def getVersionId(self, toolname, version, repos_api, internal_version_api, repos_tool, internal_version_tool):
        repository = '%s;%s' % (repos_tool, repos_api)
        
        retval = None
        
        try:
            p = pin.Version.objects.get(tool=toolname,
                                        version=version,
                                        internal_version_tool=internal_version_tool[:40],
                                        internal_version_api=internal_version_api[:40],
                                        repository=repository)
            
            retval = p.pk
        
        except pin.Version.DoesNotExist:
            pass
        
        return retval

    def newVersion(self, toolname, version, repos_api, internal_version_api, repos_tool, internal_version_tool):
        repository = '%s;%s' % (repos_tool, repos_api)
        
        p = pin.Version(timestamp=datetime.now(),
                        tool=toolname,
                        version=version,
                        internal_version_tool=internal_version_tool,
                        internal_version_api=internal_version_api,
                        repository=repository)
        
        p.save()

        result_id = p.pk
        
        return result_id
    
    
    def getUserId(self, username):
        retval = 0
        
        try:
            u = User.objects.get(username=username)
            
            retval = u.pk
        except User.DoesNotExist:
            pass
        
        return retval
        

    def updateUserLogin(self, row_id, email = None):
        u = User.objects.get(id=row_id)
        
        u.last_login = datetime.now()
        
        if not email is None:
            u.email = email
            
        u.save()
        
        
    def createUser(self,
                   username,
                   email='-',
                   first_name='',
                   last_name='',):

        timestamp = datetime.now()
        
        u = User(username=username,
                 password='NoPasswd',
                 date_joined=timestamp, 
                 last_login=timestamp,
                 first_name=first_name,
                 last_name=last_name,
                 email=email,
                 is_active=1,
                 is_staff=0,
                 is_superuser=0)
        
        u.save()
        

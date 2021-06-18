#!/bin/bash
set -e
#source /opt/evaluation_system/bin/activate
#/opt/evaluation_system/bin/activate init --all &> /dev/null
#/opt/evaluation_system/bin/conda activate /opt/evaluation_system

/usr/bin/git config --global init.defaultBranch main &> /dev/null
/usr/bin/git config --global user.email "user@docker.org" &> /dev/null
/usr/bin/git config --global user.name "Freva" &> /dev/null
sleep 0.5
export PATH=/opt/evaluation_system/bin:$PATH
if [ -z "$(ps aux|grep mysqld_safe|grep -v grep)" ];then
    nohup mysqld_safe &> /dev/null &
fi

if [ -z "$(ps aux|grep solr|grep -v grep|grep java)" ];then
    export SOLR_HOME=${HOME}/solr/data
    export SOLR_PID_DIR=${HOME}/solr
    export SOLR_LOGS_DIR=${HOME}/solr/logs
    export LOG4J_PROPS=${HOME}/solr/log4j2.xml
    nohup /opt/solr/bin/solr start -s ${HOME}/solr/data &> /dev/null &
fi
if [ -f /opt/evaluation_system/sbin/solr_ingest ];then
   nohup /opt/evaluation_system/sbin/solr_ingest --crawl /mnt/data4freva/observations --output /tmp/dump2.gz
   nohup /opt/evaluation_system/sbin/solr_ingest --ingest /tmp/dump2.gz
   nohup rm /tmp/dump2.gz
fi

exec /opt/docker-solr/scripts/docker-entrypoint.sh "$@"

import requests
import json
import re
import sys, os
import subprocess
import logging, logging.handlers
import pandas as pd

#--------------------------------------------
# Global Variable
#--------------------------------------------
# CSV file path
path_alertlist = "/home/snow00/zabicom_alert/zabicom_alert.csv"
path_alertlist_attachment = "/home/snow00/zabicom_alert/zabicom_alert_for_attachment.csv"
path_hostlist = "/home/snow00/zabicom_alert/zabicom_hostlist.csv"
path_hostlist_attachment = "/home/snow00/zabicom_alert/zabicom_hostlist_for_attachment.csv"

# CSV file header 
hostlist_header = ['Host Name','SSH IP Address']
alertList_header = ['Service','Host Name', 'Alert Name', 'OID', 'Instance', 'Error Threshold', 'Get Zabicom Graph', 'Zabicom Item Name']

# servicenow Authenticate info
region = os.uname()[1][0:3]
token_file = '/opt/token/access.txt'
ticket_table_sys_id = sys.argv[4]
alertlist_table_sys_id = sys.argv[5]
hostlist_table_sys_id = sys.argv[6]
if region.startswith("lb"):
    top_level_url = 'https://op-support-stg.dev.servicenow.ntt.com/'
else:
    top_level_url = 'https://op-support.servicenow.ntt.com/'

with open(token_file, 'r') as f:
    token = f.read().strip()

#--------------------------------------------
# class
#--------------------------------------------
# Authenticate zabicom
class Zabicom:
    def __init__(self, ip, user, pw):
        self.url = 'http://{}/zabicom/api_jsonrpc.php'.format(ip)
        self.headers = {"Content-Type": "application/json-rpc"}
        self.auth(user, pw)
        
    def post_api(self, method, params):
        payload = {
            "method": method,
            "id": 1,
            "params": params,
            "auth": self.token,
            "jsonrpc": "2.0"
        }
        result = requests.post(self.url, headers=self.headers, data=json.dumps(payload))
        return result.json()['result']
    
    def auth(self, user, pw):
        self.token = ''
        params = {
            "user": user,
            "password": pw
        }
        result = self.post_api('user.login', params)
        self.token = result

#--------------------------------------------
# Function
#--------------------------------------------
# Convert operator string to sympol 
def convert_opr(s):
    if s == 'ge':
        return '>= '
    elif s == 'gt':
        return '> '
    elif s == 'eq':
        return '== '
    elif s == 'lt':
        return '< '
    elif s == 'le':
        return '<= '
    
def create_attach_csv(mode, header_list, path_data_list, path_list_attachment, datalist):
    df = pd.DataFrame(datalist, columns=header_list, dtype=str)
    if mode == 'new':
        df.to_csv(path_list_attachment, mode='w', index=False)
        return True
    
    if mode == 'update':
        old_df = pd.read_csv(path_data_list, dtype=str).fillna('')
        d = diff_list(old_df, df, header_list)
        if len(d.index) == 0:
            return False
        d.to_csv(path_list_attachment, mode='w', index=False)

    return True

def create_master_csv(header_list, path_data_list, datalist):
    df = pd.DataFrame(datalist, columns=header_list, dtype=str)
    df.to_csv(path_data_list, mode='w', index=False)

def diff_list(old_dataframe, new_dataframe, header_list):
    d = pd.merge(old_dataframe,new_dataframe, on=header_list, how='outer', indicator=True)
    return d[d['_merge'] == 'right_only'].iloc[:,:-1]

# attach csvfile to servicenow
def upload_csv(table_sys_id, upload_file):
    try:
        upload_file_uri = top_level_url + 'api/now/attachment' + '/upload '

        cmd = "curl -s " + upload_file_uri\
        + "--request POST "\
        + "--header 'Accept:application/json' "\
        + "--header \'Authorization: Bearer " + token + "\' "\
        + "--header \'Content-Type:multipart/form-data\' "\
        + "-F \'table_name=" + 'sys_data_source' + "\' "\
        + "-F \'table_sys_id=" + table_sys_id + "\' "\
        + "-F \'uploadFile=@" + upload_file + "\'"

        res = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
        result = res.communicate()[0].decode("utf-8")
        logger.info(result)

        if ('error' in result) or (result == ''):
            logger.error('File upload failed')
            return False
        else:
            logger.info('File upload success - %s', upload_file)
            return True
        
    except Exception as e:
        logger.error(e)

# update data collection ticket 
def update_ticket_status(ticket_sys_id):
    try:
        update_ticket_uri = top_level_url + 'api/now/table/u_data_collection/' + ticket_sys_id

        headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token
        } 

        payload = {
            "state": "2"
        }

        response = requests.patch(update_ticket_uri, headers=headers, json=payload)
        update_result = response.text
        logger.info(update_result)

        if response.status_code == 200:
            logger.info('Status update success \nstatus code: %s',response.status_code)
            return True
        else:
            logger.error('Status update failed \nstatus code: %s',response.status_code)
            return False

    except Exception as e:
        logger.error(e)

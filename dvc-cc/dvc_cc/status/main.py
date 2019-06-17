SCRIPT_NAME = 'dvc-cc status'
TITLE = 'tools'
DESCRIPTION = 'Gives you the status of your project and an overview, which experiments was already executed.'

import os
import yaml
import requests
import keyring
from dvc.repo import Repo as DVCRepo
from git import Repo as GITRepo
from argparse import ArgumentParser
import datetime
import pandas
import time

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def get_main_git_directory_path():
    gitrepo = GITRepo('.')
    git_path = gitrepo.common_dir.split('/.git')[0]
    return git_path

def show_nodes(auth,execution_engine):
    r = requests.get(
        execution_engine+'/nodes',
        auth=auth
    )
    r.raise_for_status()
    nodes = r.json()
    nodes.sort(key=lambda n: n['nodeName'])
    for n in nodes:
        if n['state'] == 'online':
            state = bcolors.OKGREEN + 'online' + bcolors.ENDC
        else:
            state = bcolors.FAIL + n['state'] + bcolors.FAIL

        #if 'gpus' in n:
        #    # its a gpu server
        #else:
        #    # its not a gpu server

        used_ram = 0
        for i in n['currentBatches']:
            used_ram += i['ram']

        used_ram = used_ram / 1000.
        n['ram'] = n['ram'] / 1000.

        if used_ram / 0.9 + 0.1 > n['ram']:
            ram = bcolors.FAIL + str(int(used_ram)) + bcolors.ENDC + '/' + str(int(n['ram']))
        elif used_ram / 0.75 + 0.1 > n['ram']:
            ram = bcolors.WARNING + str(int(used_ram)) + bcolors.ENDC + '/' + str(int(n['ram']))
        else:
            ram = bcolors.OKGREEN + str(int(used_ram)) + bcolors.ENDC + '/' + str(int(n['ram'])) 

        if 'gpus' in n:
            gpus = []
            for gpu in n['gpus']:
                gpus.append(str(int(gpu['vram']/1000.)) + 'GB')
            print(('%30s   '+bcolors.BOLD+'RAM:'+bcolors.ENDC+'%20s GB    '+bcolors.BOLD+'Num of Jobs:'+bcolors.ENDC+'%5s    '+bcolors.BOLD+'Num of GPUs:'+bcolors.ENDC + ' %s %s') % (n['nodeName'] + ' (' + state + ')',
                            ram,
                            len(n['currentBatches']),
                            len(gpus),
                            str(gpus)
                        ))
        else:
            print(('%30s   '+bcolors.BOLD+'RAM:'+bcolors.ENDC+'%20s GB    '+bcolors.BOLD+'Num of Jobs:'+bcolors.ENDC+'%5s') % (n['nodeName'] + ' (' + state + ')',
                            ram,
                            len(n['currentBatches'])
                            ))

def read_execution_engine():
    with open('.dvc_cc/cc_config.yml') as f:
        y = yaml.safe_load(f.read())
    return y['execution']['settings']['access']['url']

    

def main():
    parser = ArgumentParser(description=DESCRIPTION)
    parser.add_argument('-a','--all', help='Show all experiments of this project.', default=False, action='store_true')
    parser.add_argument('-at','--all-time', help='Show all experiments over all projects.', default=False, action='store_true')
    parser.add_argument('-n','--number-of-experiments', help='Number of the last experiments that should be displayed. Default is 1. Is the parameter --all or --all-time is set, this parameter have no effect.', type=int, default=1)
    parser.add_argument('-id','--show-ids', help='Show the curious containers id of the experiment and curious containers id of the sub-experiments.', default=False, action='store_true')
    parser.add_argument('-s','--summary', help='Summary the Output.', default=False, action='store_true')
    parser.add_argument('-d','--detail', help='Show all details and outputs for the sub experiments.', default=False, action='store_true')
    parser.add_argument('-e','--list-of-experimentids', help='A list of experiment ids that you want include in the display.', nargs="+", type=int)
    parser.add_argument('-p','--list-of-position-of-the-subprojects', help='A list of positions of the subproject that you want include in the display.', nargs="+", type=int)
    parser.add_argument('-f','--only-failed', help='Show only failed experiments.', default=False, action='store_true')
    parser.add_argument('-ne','--only-not-executed', help='Show only not executed experiments.', default=False, action='store_true')
    parser.add_argument('--node', help='Show all nodes in the cluster. If you run this command, it will ignore all other paramters!', default=False, action='store_true')
    args = parser.parse_args()
    
    # Change the directory to the main git directory.
    os.chdir(get_main_git_directory_path())

    # TODO CHECK IF THIS IS SAVED, ELSE ASK FOR IT !!!
    pw = keyring.get_password('red', 'agency_password')
    uname = keyring.get_password('red', 'agency_username')
    auth = (uname, pw)


    execution_engine = read_execution_engine()


    if args.node:
        show_nodes(auth,execution_engine)
        exit(0)

    if os.path.exists('.dvc_cc/cc_agency_experiments.yml'):
        with open(".dvc_cc/cc_agency_experiments.yml", 'r') as stream:
            try:
                experiments = yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                print(exc)
                exit(1)

    if args.only_not_executed:
        experimentsIDS = [[e,experiments[e]['id']] for e in experiments if experiments[e]['id'] is None]
        print(pandas.DataFrame(experimentsIDS, columns=['experiment_name', 'ID']).to_string())
        exit(0)




    experimentsIDS = pandas.DataFrame([[e,experiments[e]['id']] for e in experiments if experiments[e]['id'] is not None], columns=['experiment_name','experimentId'])

    if args.only_failed:
        requesting_string = execution_engine+'/batches?state=failed'
    else:
        requesting_string = execution_engine+'/batches'

    # get all experiments:
    r = requests.get(
        requesting_string,
        auth=auth
    )
    all_time_experiments = pandas.DataFrame(r.json())



    # filter experiments:
    if args.all_time:
        experiments = pandas.merge(experimentsIDS, all_time_experiments, how='outer')
    else:
        experiments = pandas.merge(experimentsIDS, all_time_experiments, how='inner')

    experiments = experiments

    # TODO: SOMETHING IS WRONG WITH THE ORDER !!!

    if args.all == False:
        if args.list_of_experimentids is not None:
            experiments = experiments[experiments['experimentId'].isin(args.list_of_experimentids)]

        grouped = experiments.groupby('experimentId')

        pos = args.list_of_position_of_the_subprojects
        if pos is not None and len(pos) > 0:
            grouped_filtered = []
            for group in grouped:
                group = (group[0],group[1].iloc[pos])
                if len(group[1]) > 0:
                    grouped_filtered.append(group)
            grouped = grouped_filtered
        else:
            grouped = list(grouped)
        if args.number_of_experiments is not None and args.number_of_experiments > 0:
            grouped = grouped[-args.number_of_experiments:]
        if len(grouped) <= 0:
            print(bcolors.WARNING+'Warning: No jobs matching your search were found.'+bcolors.ENDC)
            exit(0)
        df = grouped[0][1]
        for i in range(1,len(grouped)):
            df = df.append(grouped[i][1])
    else:
        df = experiments

    if len(df) <= 0:
        print(bcolors.WARNING+'Warning: No jobs matching your search were found.'+bcolors.ENDC)
        exit(0)

    # replace strings
    ids = df['_id'].copy()
    if args.show_ids == False:
        df['experimentId'] = '...'+df['experimentId'].apply(lambda x: x[-3:])
        df['_id'] = '...'+df['_id'].apply(lambda x: x[-3:])
    df['registrationTime'] = df['registrationTime'].apply(lambda x: time.ctime(int(x)))
    df['state'] = df['state'].replace(['succeeded', 'cancelled','failed','processing'],[bcolors.OKGREEN+'succeeded'+bcolors.ENDC,bcolors.WARNING+'cancelled'+bcolors.ENDC,bcolors.FAIL+'failed'+bcolors.ENDC,bcolors.OKBLUE+'processing'+bcolors.ENDC])

    # print everything    
    if args.detail == False:
        if args.summary:
            print(df.groupby('experimentId')['state'].value_counts().to_string())
        else:
            print(df.to_string())

    else:
        for i in range(len(df)):
            d = df.iloc[i]
            r = requests.get(
                execution_engine+'/batches/'+ids.iloc[i],
                auth=auth
            )
            detail = r.json()

            print(bcolors.OKGREEN+'#'*63+bcolors.ENDC)
            print(bcolors.OKGREEN+'# %50s (%6s) #' % (d['experiment_name'], d['experimentId']) +bcolors.ENDC)
            print(bcolors.OKGREEN+'# %59s #' % ('batch id: ' + d['_id']) +bcolors.ENDC)
            print(bcolors.OKGREEN+'#'*63+bcolors.ENDC)
        
            print(bcolors.OKGREEN+'State: '+bcolors.ENDC + d['state'])

            for h in detail['history']:

                print(bcolors.OKGREEN+'Time (' + h['state'] + '):  '+bcolors.ENDC + datetime.datetime.fromtimestamp(h['time']).strftime('%Y-%m-%d %H:%M:%S'))
            if d['state'].find('failed') >= 0 or d['state'].find('succeeded') >= 0 or d['state'].find('canceled') >= 0:
                print(bcolors.OKGREEN+'Used server node: '+bcolors.ENDC + str(d['node']))
                if 'usedGPUs' in detail and detail['usedGPUs'] is not None:
                    if len(detail['usedGPUs']) == 1:
                        print(bcolors.OKGREEN+'Used GPUs: '+bcolors.ENDC + str(detail['usedGPUs'][0]))
                    else:
                        print(bcolors.OKGREEN+'Used GPUs: ' +bcolors.ENDC+ str(detail['usedGPUs']))

                if detail['history'][-1]['ccagent'] is not None:
                    c = detail['history'][-1]['ccagent']['command']
                    if len(c) == 13:
                        print(bcolors.OKGREEN +'Files: '+bcolors.ENDC + str(c[-1]))                    
                    else:
                        print(bcolors.OKGREEN +'Files:'+bcolors.ENDC+' ALL')
                    print(bcolors.OKGREEN + 'Return Code: ' + bcolors.ENDC + str(detail['history'][-1]['ccagent']['process']['returnCode']))
                    if args.summary is False:
                        print()
                        print(bcolors.OKGREEN + 'stdOut: ' + bcolors.ENDC)
                        print('\n'.join(detail['history'][-1]['ccagent']['process']['stdOut']))
                        print()
                        print(bcolors.WARNING + 'stdErr: ' + bcolors.ENDC)
                        print('\n'.join(detail['history'][-1]['ccagent']['process']['stdErr']))
                        print()
                else:
                    print(bcolors.FAIL+'ERROR: The ccagend is None.' + bcolors.ENDC)
            print()



#!/usr/bin/env python3

import dvc_cc.run.helper as helper
from argparse import ArgumentParser
from dvc.repo import Repo as DVCRepo
from git import Repo as GITRepo
import yaml
import os
from subprocess import check_output
from subprocess import Popen, PIPE
import json
import numpy as np
import subprocess
#import dvc_cc.hyperopt.dummy_to_dvc as dummy_to_dvc
import nbformat
from nbconvert import PythonExporter
import keyring
import requests
from dvc_cc.hyperopt.variable import *
from dvc_cc.hyperopt.hyperoptimizer import *
import uuid
from pathlib import Path
from dvc_cc.run.jupyter_notebook_to_source import jupyter_notebook_to_source

DESCRIPTION = 'This script starts one or multiple dvc jobs in a docker on the CC server.'

def read_execution_engine():
    with open(str(Path('.dvc_cc/cc_config.yml'))) as f:
        y = yaml.safe_load(f.read())
    return y['execution']['settings']['access']['url']

def get_main_git_directory_Path():
    gitrepo = GITRepo('.')
    git_path = gitrepo.common_dir.split('/.git')[0]
    return git_path

def get_gitinformation():
    # TODO: use the intern python-git for this.
    out = check_output(["git", "config", "--get", "remote.origin.url"]).decode("utf8")
    if out.startswith('https://'):
        _,_, gitrepo,gitowner,gitname = out.split('/')
    else:
        gitrepo = out[4:out.find(':')]
        gitowner = out[out.find(':')+1:out.find('/')]
        gitname = out[out.find('/')+1:]

    gitname = gitname[:gitname.find('.git')+4]
    return gitrepo,gitowner,gitname

def create_new_exp_id():
    all_branches = [f.split('/')[-1].replace(' ', '') for f in check_output(["git", "branch", "-a"]).decode("utf8").split('\n')]

    pre_tag = [i.split('_')[1] for i in all_branches if len(i.split('_')) > 2]
    pre_tag = [int(tag) for tag in pre_tag if tag.isdigit()]
    if len(pre_tag) > 0:
        new_tag = np.max(pre_tag) + 1
    else:
        new_tag = 1
    new_tag = 'cc_%0.4d' % new_tag
    return new_tag

def get_mount_values_for_a_direcotry(path):
    mount = [m.split(' ') for m in check_output(["mount"]).decode("utf8").split('\n')]
    for m in mount:
        if len(m) == 6 and m[2] == path:
            username = m[0].split('@')[0]
            servername = m[0].split('@')[1].split(':')[0]
            path = m[0].split('@')[1].split(':')[1]
            return username, servername, path
    return None, None, None

def get_dvcurl():
    dvc_url = []
    try:
      with open(str(Path(".dvc/config.local")), "r") as fi:
        for ln in fi:
            ln = ln.replace(' ', '')
            if ln.startswith("url="):
              dvc_url.append(ln)
    except:
        try:
          with open(str(Path(".dvc/config")), "r") as fi:
            for ln in fi:
                ln = ln.replace(' ', '')
                if ln.startswith("url="):
                  dvc_url.append(ln)
        except:
          print('No .dvc/config or .dvc/config.local was found.')

    if len(dvc_url) != 1:
      if len(dvc_url) == 0:
        print('no url was found. please set the url in the .dvc/config file.')
      if len(dvc_url) > 1:
        print('multiple url was found. only one url is currently allowed')
      print('Please specifier the servername and the repository.')
      dvc_server = input("dvc_servername: ")
      dvc_path = input("dvc_path_to_working_repository: ")
    else:
      dvc_url = dvc_url[0].split('@')[1]
      dvc_server = dvc_url[:dvc_url.find(':')]
      dvc_path = dvc_url[dvc_url.find(':')+1:].rstrip()
    return dvc_url, dvc_server, dvc_path

def check_git_repo(args):
    gitrepo = GITRepo('.')
    if args.yes == False:
        files_are_not_commited = False        
        untracked_files = [f for f in gitrepo.untracked_files if not f.startswith('.dvc_cc')]
        if len(untracked_files) > 0:
            print('Warning: Some files are untracked: ' + str(untracked_files))
            files_are_not_commited = True
        changed_files = [f.a_path for f in gitrepo.index.diff(None) if not f.a_path.startswith('.dvc_cc')] 
        if len(changed_files) > 0:
            print('Warning: Some files are changed: ' + str(changed_files))
            files_are_not_commited = True
        if files_are_not_commited:
            user_answer = input("Do you want continue? (y/n): ")
            if user_answer.lower().strip().startswith('n'):
                print('You abort this command. You could use "git add -A", "git commit -m \'some message\'" and "git push" to commit this file.')
                exit(1)
    """ No need for this, because this script pushes the results and the not pushed commits also.
    if check_output(["git", "status"]).decode("utf8").split('\n')[1].startswith('Your branch is ahead'):
        print('Warning: You did not push the last commit. Use "git push".')
        if args.yes == False:
            user_answer = input("Do you want continue? (y/n): ")
            if user_answer.lower().strip().startswith('n'):
                print('You abort this command. Please push your commit first.')
                exit(1)
    """
    return

def get_leafs_that_need_to_reproduce(dvcrepo, Gs):
    # Get all leaf files.
    leafs = []
    for G in Gs:
        leafs = leafs + [[x.path_in_repo] for x in G.nodes() if G.in_degree(x) == 0]

    status_of_leafs = [dvcrepo.status(targets=l, with_deps=True) for l in leafs]

    # check if the leafs need to reproduce:
    leafs_to_reproduce = [len(status_of_leafs) > 0 for s in status_of_leafs]
    leafs = [leafs[i] for i in range(len(leafs)) if leafs_to_reproduce[i]]
    status_of_leafs = [status_of_leafs[i] for i in range(len(leafs)) if leafs_to_reproduce[i]]

    # check if there two leafs need both to reproduce the same stages.
    move_leafs = []
    for i in range(len(leafs) -1):
        move_leaf = None
        for j in range(i+1, len(leafs)):
            for k in status_of_leafs[i].keys():
                if k in status_of_leafs[j]:
                    # both leafs need to reproduce same stage
                    move_leaf = j
        move_leafs.append(move_leaf)

    move_leafs.append(None)

    leafs_need_to_reproduce = []
    for i in range(len(move_leafs)):
        if move_leafs[i] is not None:
            leafs[move_leafs[i]].extend(leafs[i])
        else:
            leafs_need_to_reproduce.append(leafs[i])
    return leafs_need_to_reproduce

def all_jupyter_notebook_to_py_files(Gs):
    created_files = []
    for G in Gs:
        for s in G.nodes():
            if s.cmd is not None:
                cmd = s.cmd.split()
                if cmd[0] == 'python':
                    for c in cmd:
                        if c.endswith('.py'):
                            if not os.path.exists(c) and os.path.exists(c[:-3]+'.ipynb'):
                                created_files.append(jupyter_notebook_to_py_file(c[:-3]+'.ipynb'))
                                print(bcolors.BOLD+'    Convert ' + c[:-3]+'.ipynb' +  ' to ' + c + ' file.' + bcolors.ENDC)
    return created_files

def jupyter_notebook_to_py_file(path_to_ipynb):
    source = jupyter_notebook_to_source(path_to_ipynb)
    output_name = path_to_ipynb[:-6]+'.py'
    with open(str(Path(output_name)), 'w') as fh:
        print(source, file=fh)
    return output_name

def run_command(command):
    process = Popen(command, stdout=PIPE, shell=True)
    while True:
        line = process.stdout.readline().rstrip()
        if not line:
            break
        yield line

def get_last_cc_experimentid(keyring_service):
    if keyring_service is None:
        keyring_service = 'red'
    pw = keyring.get_password(keyring_service, 'agency_password')
    uname = keyring.get_password(keyring_service, 'agency_username')
    if uname is None:
        uname = input('agency_username: ')
        pw = input('agency_password: ')
    #TODO CHECK if this is NONE!
    auth = (uname, pw)

    r = requests.get(
        read_execution_engine()+'/experiments',
        auth=auth
    )
    r.raise_for_status()
    a = r.json()
    # make sure a is not empty before directly acessing
    return sorted(a,key=lambda x: x['registrationTime'])[-1]['_id']  if a else None


def create_cc_config(dvc_files, exp_name, rcc_branch_names, num_of_repeats, live_output_files,
                live_output_update_frequence):
    git_path, git_owner, git_name = get_gitinformation()

    dvc_url, dvc_server, dvc_path = get_dvcurl()

    project_dir = get_main_git_directory_Path()
    path_to_sshfs_json = str(Path(os.path.join(project_dir, '.dvc_cc/sshfs.json')))

    if os.path.exists(path_to_sshfs_json):
        with open(path_to_sshfs_json, "r") as jsonFile:
            sshfs_data = json.load(jsonFile)
    else:
        sshfs_data = None

    with open('cc_execution_file.red.yml',"w") as f:
        print("batches:", file=f)
        for i in range(len(dvc_files)):
            dvcfiles_to_execute = str(dvc_files[i])[1:-1].replace("'", "").replace('"', '').replace(' ', '')
            for rcc_branch in rcc_branch_names:
                for k in range(num_of_repeats):
                    # print("batches:", file=f)
                    print("  - inputs:", file=f)
                    print("      git_authentication_json:", file=f)
                    print("        class: File", file=f)
                    print("        connector:", file=f)
                    print("          access: {username: '{{" + git_path.replace('.', '_').replace('-',
                                                                                                  '_') + "_username}}', password: '{{" + git_path.replace(
                        '.', '_').replace('-', '_') + "_password}}', email: '{{" + git_path.replace('.', '_').replace('-',
                                                                                                                      '_') + "_email}}'}",
                          file=f)
                    print("          command: dvc-cc-connector", file=f)
                    print("      git_path_to_working_repository: \"" + git_path + "\"", file=f)
                    print("      git_working_repository_owner: \"" + git_owner + "\"", file=f)
                    print("      git_working_repository_name: \"" + git_name + "\"", file=f)
                    print("      git_name_of_input_branch: \"" + exp_name + "\"", file=f)
                    print("      git_name_of_result_branch: \"" + rcc_branch + "\"", file=f)
                    print("      dvc_authentication_json:", file=f)
                    print("        class: File", file=f)
                    print("        connector:", file=f)
                    print("          access: {username: '{{" + dvc_server.replace('.', '_').replace('-',
                                                                                                    '_') + "_username}}', password: '{{" + dvc_server.replace(
                        '.', '_').replace('-', '_') + "_password}}'}", file=f)
                    print("          command: dvc-cc-connector", file=f)
                    print("      dvc_servername: \"" + dvc_server + "\"", file=f)
                    print("      dvc_path_to_working_repository: \"" + dvc_path + "\"", file=f)

                    if sshfs_data is not None:
                        print("      sshfs_input_server_settings:", file=f)
                        for i in range(len(sshfs_data.keys())):
                            sshfs_dest_rel = list(sshfs_data.keys())[i]
                            sshfs_username = sshfs_data[sshfs_dest_rel]["username"]
                            sshfs_server = sshfs_data[sshfs_dest_rel]["server"]
                            sshfs_path = sshfs_data[sshfs_dest_rel]["remote_path"]
                            sshfs_password = '{{' + str(sshfs_server).replace('.', '_').replace('-', '_') + '_password}}'

                            print("        - class: Directory", file=f)
                            print("          connector:", file=f)
                            print("              command: \"red-connector-ssh\"", file=f)
                            print("              mount: true", file=f)
                            print("              access:", file=f)
                            print("                host: '" + sshfs_server + "'", file=f)
                            print("                port: 22", file=f)
                            print("                auth:", file=f)
                            print("                  username: '" + sshfs_username + "'", file=f)
                            print("                  password: '" + sshfs_password + "'", file=f)
                            print("                dirPath: '" + sshfs_path + "'", file=f)

                        print("      sshfs_input_dest_rel_paths:", file=f)
                        for i in range(len(sshfs_data.keys())):
                            sshfs_dest_rel = list(sshfs_data.keys())[i]
                            print("        - '"+sshfs_dest_rel+"'", file=f)

                    print("      dvc_remote_directory_sshfs:", file=f)
                    print("        class: Directory", file=f)
                    print("        connector:", file=f)
                    print("            command: \"red-connector-ssh\"", file=f)
                    print("            mount: true", file=f)
                    print("            access:", file=f)
                    print("              host: '" + dvc_server + "'", file=f)
                    print("              port: 22", file=f)
                    print("              auth:", file=f)
                    print("                username: '" + "{{" + dvc_server.replace('.', '_').replace('-',
                                                                                                      '_') + "_username}}'",
                          file=f)
                    print("                password: '" + "{{" + dvc_server.replace(
                        '.', '_').replace('-', '_') + "_password}}" + "'", file=f)
                    print("              writable: True", file=f)
                    print("              dirPath: '" + dvc_path + "'", file=f)

                    print("      dvc_file_to_execute: '" + dvcfiles_to_execute.replace('\\\\', '/') + "'", file=f)
                    if live_output_files is not None:
                        print("      live_output_files: '" + live_output_files + "'", file=f)
                        print("      live_output_update_frequence: " + str(live_output_update_frequence), file=f)
                    print("    outputs: {}", file=f)
        with open('.dvc_cc/cc_config.yml',"r") as r:
            print(r.read(), file=f)

    subprocess.call(['git', 'add', 'cc_execution_file.red.yml'])
    subprocess.call(['git', 'add', '.dvc_cc/cc_config.yml'])
    # subprocess.call(['git', 'add', '.dvc_cc/cc_agency_experiments.yml'])
    subprocess.call(['git', 'commit', '-m', '\'Create red.yml file.\''])
    subprocess.call(['git', 'push'])

def exec_branch(keyring_service):

    # Get last experiment ID
    last_cc_id = get_last_cc_experimentid(keyring_service)

    # EXECUTE THE RED-YML
    if keyring_service is None:
        p = 'faice exec cc_execution_file.red.yml --disable-retry'
    else:
        p = 'faice exec --keyring-service ' + keyring_service + ' cc_execution_file.red.yml --disable-retry'
    message = subprocess.call(p.split(' '))
    cc_id = get_last_cc_experimentid(keyring_service)
    if last_cc_id == cc_id:
        raise RuntimeError(bcolors.FAIL+'The job could not be started. Maybe there is some error in the '
                                        'RED-YML file.\n\nMessage of "faice exec":\n' + message + bcolors.ENDC)
    print('The experiment ID is: ' + str(cc_id))
    return cc_id

def intarray_to_shortstr(input_array):
    input_array = np.array(input_array, dtype=int)
    str_array = np.array(input_array, dtype=str)
    max_length = np.max([len(s) for s in str_array])
    if max_length <= 6:
        return str_array
    else:
        unique_values = len(np.unique(str_array))
        i = 0
        while len(np.unique([('%.'+str(i)+'E')%s for s in input_array])) < unique_values:
            i += 1
        return [('%.'+str(i)+'E')%s for s in input_array]

def floatarray_to_shortstr(input_array):
    input_array = np.array(input_array, dtype=float)
    unique_values = len(np.unique(input_array))
    i = 0
    while len(np.unique([('%.'+str(i)+'f')%s for s in input_array])) < unique_values:
        i += 1
    str_array = [('%.'+str(i)+'f')%s for s in input_array]
    max_length = np.max([len(s) for s in str_array])
    if max_length <= 6:
        return str_array
    else:
        unique_values = len(np.unique(str_array))
        i = 0
        while len(np.unique([('%.'+str(i)+'E')%s for s in input_array])) < unique_values:
            i += 1
        return [('%.'+str(i)+'E')%s for s in input_array]

def strarray_to_shortstr(input_array):
    input_array = np.array(input_array, dtype=str)
    unique_values = len(np.unique(input_array))
    min_len_of_text = np.min([len(s) for s in input_array])
    if unique_values == 1:
        return [s[0] for s in input_array]
    else:
        start_index = 0
        while len(np.unique([s[start_index] for s in input_array])) == 1 and start_index < min_len_of_text - 1:
            start_index += 1
        end_index = start_index + 1
        while len(np.unique([s[start_index:end_index] for s in input_array])) < unique_values:
            end_index += 1
        return [s[start_index:end_index] for s in input_array]

def define_the_rcc_branch_names(exp_name, hyperopt_draws, list_of_variables):
    # TODO: USE PARAMS FOR THIS: + '___' + str(draw)[1:-1].replace(',','_').replace(' ','').replace('[','').replace(']','').replace('-','')
    hyperopt_draws = np.array(hyperopt_draws)
    result = []
    result_only_values = []
    for i in range(len(list_of_variables)):
        v = list_of_variables[i]
        if v.vartype == 'float':
            values = floatarray_to_shortstr(hyperopt_draws[:, i])
        elif v.vartype == 'int':
            values = intarray_to_shortstr(hyperopt_draws[:, i])
        else:
            values = [hyperopt_draws[j, i].lower().replace('/', '_').replace('\\\\', '_').replace(' ', '') for j in
                                                                                    range(len(hyperopt_draws))]
            values = strarray_to_shortstr(values)
        values_with_name = [v.varname.upper().replace('_','').replace('-','') + var for var in values]
        if len(np.unique(values_with_name)) > 1:
            result.append(values_with_name)
            result_only_values.append(values)

    if len(result) == 0:
        return [ 'r'+exp_name ]

    result = list(map(list, zip(*result)))
    result_only_values = list(map(list, zip(*result_only_values)))

    batch_names = []
    for i in range(len(result)):
        batch_append = False
        batch_name = 'r'+exp_name + '_' + '_'.join(result[i])
        if len(batch_name) < 50:
            batch_names.append(batch_name)
            batch_append = True
        if batch_append == False:
            # try reducing the exp name
            batch_name = 'r'+exp_name[:18] + '_' + '_'.join(result[i])
            if len(batch_name) < 50:
                batch_names.append(batch_name)
                batch_append = True
        if batch_append == False:
            # try reducing the exp name + only_values
            batch_name = 'r'+exp_name[:18] + '_' + '_'.join(result_only_values[i])
            if len(batch_name) < 50:
                batch_names.append(batch_name)
                batch_append = True
        if batch_append == False:
            # use reduced exp name + index
            batch_name = 'r'+exp_name[:18] + '_' + str(i)
            batch_names.append(batch_name)

    return batch_names

def find_all_dvc_leafs(args_dvc_files):

    #####################################
    # Rename the hyperopt-files to .dvc #
    #####################################
    if os.path.exists('dvc') and os.path.exists(str(Path('dvc/.hyperopt'))):
        list_of_hyperopt_files = [f for f in os.listdir(str(Path('dvc/.hyperopt'))) if f.endswith('.hyperopt')]
        for f in list_of_hyperopt_files:
            os.rename(str(Path('dvc/.hyperopt/' + f)), str(Path('dvc/'+f[:-9]+'.dvc')))
            print(str(Path('dvc/.hyperopt/' + f)), str(Path('dvc/'+f[:-9]+'.dvc')))
    else:
        list_of_hyperopt_files = []

    #############################
    # Find all leafs to execute #
    #############################
    try:
        dvcrepo = DVCRepo('.')
        Gs = dvcrepo.pipelines

        if len(Gs) > 0:
            if args_dvc_files is None:
                #dvc_files = [[f[2:]] for f in helper.getListOfFiles(add_only_files_that_ends_with='.dvc')]
                dvc_files = get_leafs_that_need_to_reproduce(dvcrepo, Gs)
            else:
                dvc_files = []
                dvc_files_tmp = args_dvc_files.dvc_files.replace(' ', '').split(',')
                for dvc_files_branch in dvc_files_tmp:
                    dvc_files.append([])
                    dvc_files_file = dvc_files_branch.split('|')
                    for i in range(len(dvc_files_file)):
                        dvc_files[-1].append(dvc_files_file[i])
                        if not dvc_files_file[i].endswith('.dvc'):
                            raise ValueError('Error: You define with -f which dvc files you want to exec. One or more files does not ends with .dvc. Please use only DVC files.')
        else:
            dvc_files = []
    # make sure that the hyperopt files get always renamed!
    finally:
        #############################
        # Rename the hyperopt-files #
        #############################
        for f in list_of_hyperopt_files:
            if os.path.exists(str(Path('dvc/'+f[:-9]+'.dvc'))):
                os.rename(str(Path('dvc/'+f[:-9]+'.dvc')), str(Path('dvc/.hyperopt/' + f)))
            else:
                print(bcolors.WARNING+'Warning: File ' + str(Path('dvc/'+f[:-9]+'.dvc')) + ' not found.'+bcolors.ENDC)
    return dvc_files, list_of_hyperopt_files, Gs



def main():

    parser = ArgumentParser(description=DESCRIPTION)
    parser.add_argument('experimentname', help='The name of the experiment that should be used. This can help you to search between all files.')
    parser.add_argument('-ne','--no-exec', help='If true the experiment get defined, but it will not run at a server. Warning: You should not use this command.', default=False, action='store_true')
    # TODO: parser.add_argument('-l','--local', help='Run the experiment locally!', default=False, action='store_true')
    # TODO: parser.add_argument('-q','--question', help='A question that you want to answer with that experiment.')
    # TODO: parser.add_argument('--use_only_a_tag', help='If you don't have any Hyperopt-DVC-CC files or just set one set of fixed parameters you can create a tag instead of a new branch.', default=False, action='store_true')
    parser.add_argument('-f','--dvc-files', help='The DVC files that you want to execute. If this is not set, it will search for all DVC files in this repository and use this. You can set multiple dvc files with: "first_file.dvc,second_file.dvc" or you can use "first_file.dvc|second_file.dvc" to run in a row the files in the same branch.')
    parser.add_argument('-y','--yes', help='If this paramer is set, than it will not ask if some files are not commited or it the remote is not on the last checkout. Warning: Untracked changes could be lost!', default=False, action='store_true')
    parser.add_argument('-r','--num-of-repeats', type=int, help='If you want to repeat the job multiple times, than you can set this value to a larger value than 1.', default=1)
    parser.add_argument('--not-ipynb-to-py', help='If this paramer is set, than it will NOT convert all jupyter notebook files to py files.', default=False,
                        action='store_true')
    parser.add_argument('-l','--live_output_files',
                        help='Comma separated string list of files that should be included to the live output for example: "tensorboard,output.json" This could track a tensorboard folder and a output.json file.')
    parser.add_argument('-lf','--live_output_update_frequence', type=int,
                        help='The update frequence of the live output in seconds.',
                        default=60)
    parser.add_argument('--keyring-service', type=str,
                        help='The default name of the keyring service that is used. For more information visit: '
                             'https://www.curious-containers.cc/docs/red-format-protecting-credentials',
                        default= None)

    parser.add_argument('-p','--papermill',help='Use papermill to run the jupyter notebook on the server and save the results in the jupyter notebook. If this parameter is set, no jupyter notebook will be converted to py files.',
                        default=False, action='store_true')


    parser.add_argument('-de','--delay-execution',help='If this parameter is true, than it will create first ALL input branches and than execute it once.',
                        default=False, action='store_true')
    parser.add_argument('--optuna',
                        help='This script to this parameter is in progress. It will create two directories beside your main git repository folder. In the first you find a generated script to '
                             'run a hyperoptimization with optuna. In the second you find a script that copy metrics from different result branches to the other folder. You need to start '
                             'both script manually.',
                        default=False, action='store_true')


    args = parser.parse_args()

    project_dir = get_main_git_directory_Path()
    #os.chdir(str(Path(project_dir)))
    
    gitrepo = GITRepo('.')

    startbranch = gitrepo.active_branch.name

    # Check if all files are checked and pushed.
    check_git_repo(args)

    exp_id = create_new_exp_id()

    ##########################################
    # WARN, if you are on a cc or rcc branch #
    ##########################################
    if startbranch.startswith('cc_'):
        print(bcolors.WARNING+'WARNING: You are on a DVC-CC branch.'+bcolors.ENDC)
        # TODO if the rerun command exists throw an error!
        #   print('         You should use the dvc rerun command')
        user_input = input('Do you want to continue? [y,N]')
        if not user_input.lower().startswith('y'):
            print('You can switch to a other branch with "git checkout THE_BRANCH_NAME".')
            exit(0)
    elif startbranch.startswith('rcc_'):
        print(bcolors.FAIL+'ERROR: you are on a DVC-CC-RESULT branch. It is not allowed to execute DVC-CC here. To run a job take a look at the readme of this repository.'+ bcolors.ENDC)
        exit(1)

    ############################
    # Check the Experimentname #
    ############################
    args.experimentname = args.experimentname.replace('/',' ').replace('_',' ').replace('\\\\',' ')\
                                                        .replace(';',' ').replace('.',' ').split(' ')
    if len(args.experimentname) == 1:
        args.experimentname = args.experimentname[0]
    else:
        args.experimentname = ''.join([e.capitalize() for e in args.experimentname])

    #################################################################################
    # Do a DVC-checkout to delete all files that was not created with DVC repro/run #
    #   TODO: This does not work currently! https://github.com/iterative/dvc/issues/2146
    #################################################################################
    try:
        subprocess.call(['dvc', 'checkout'])
    except:
        print('Some files are missing.')

    #############################################################
    # Find all hyperopt files and leafs to execute the pipeline #
    #############################################################
    dvc_files, list_of_hyperopt_files, Gs = find_all_dvc_leafs(args.dvc_files)

    ####################################
    # Error if no DVC-file was defined #
    ####################################
    if len(dvc_files) == 0 and not args.papermill:
        raise ValueError('There exist no job to execute! Create DVC-Files with "dvc run --no-exec ..." to define the jobs. Or check the .dvc_cc/dvc_cc_ignore file. All DVC-Files that are defined there are ignored from this script.')

    loaded_yml = None

    try:
        ###########################
        # Create an input branch! #
        ###########################
        exp_name = exp_id + '_' + args.experimentname
        print(bcolors.BOLD+'Create an input git-branch: ' + exp_name + bcolors.ENDC)
        subprocess.call(['git', 'checkout','-q', '-b', exp_name])
        #print(['git', 'push', '-u', 'origin', exp_name+':'+exp_name])
        #TODO: THIS THROWS ALWAYS A MERGE REQUEST ????
        subprocess.call(['git', 'push', '-q','-u', 'origin', exp_name+':'+exp_name])

        #############################
        # CONVERT Jupyter Notebooks #
        #############################
        if not args.not_ipynb_to_py and len(Gs) > 0:
            created_pyfiles_from_jupyter = all_jupyter_notebook_to_py_files(Gs)
        else:
            created_pyfiles_from_jupyter = []
        for f in created_pyfiles_from_jupyter:
            subprocess.call(['git', 'add', f]) #TODO: build quite mode!
            print(bcolors.BOLD + 'The following file was created from a jupyter notebook: ' + f + bcolors.ENDC)
        if not args.not_ipynb_to_py:
            subprocess.call(['git', 'commit','-q','-m', 'Convert Jupyter Notebooks to Py-File.'])
            subprocess.call(['git', 'push', '-q', '-u', 'origin', exp_name + ':' + exp_name])

        ######################################
        # Use papermill to create a dvc file #
        ######################################
        if args.papermill:
            ipynb_files_in_main_dir = [f for f in os.listdir() if f.endswith('.ipynb')]  # Todo: Allow different location of the ipynb file
            if len(ipynb_files_in_main_dir) == 0:
                raise ValueError('To use papermill you need a jupyter notebook to run on the server in the main git '
                                 'directory.')
            else:
                ipynb_files_in_main_dir = ipynb_files_in_main_dir[0]
            print(bcolors.BOLD + 'Create a DVC file for executing ' + ipynb_files_in_main_dir + ' with papermill.' +
                  bcolors.ENDC)
            from dvc_cc.run import papermill_helper
            parameters = papermill_helper.read_parameters_from_parametercell(ipynb_files_in_main_dir)
            outputs = papermill_helper.read_definitions_from_parametercell(ipynb_files_in_main_dir, 'outputs')
            metrics = papermill_helper.read_definitions_from_parametercell(ipynb_files_in_main_dir, 'metrics')

            cmd = 'papermill ' + ipynb_files_in_main_dir + ' ' + ipynb_files_in_main_dir[:-6] + '_output.ipynb --log-output -k python'
            for p in parameters:
                cmd = cmd +' -p ' + p[0] + ' {{' + p[0] + ':' + p[1] + ':None}}'

            dvc_cc_command = ['dvc-cc', 'hyperopt', 'new', '-d', ipynb_files_in_main_dir, '-o',
                             ipynb_files_in_main_dir[:-6] + '_output.ipynb', '-f','papermill.dvc']
            for o in outputs:
                dvc_cc_command = dvc_cc_command + ['-o', o[1]]
            for m in metrics:
                dvc_cc_command = dvc_cc_command + ['-M', m[1]]
            dvc_cc_command = dvc_cc_command + [cmd]

            subprocess.call(dvc_cc_command)
            subprocess.call(['git', 'add', 'dvc/.hyperopt/papermill.hyperopt'])  # TODO: build quite mode!
            subprocess.call(['git', 'commit','-q','-m', 'Create a dvc file for papermill.'])
            subprocess.call(['git', 'push', '-q', '-u', 'origin', exp_name + ':' + exp_name])
            dvc_files, list_of_hyperopt_files, Gs = find_all_dvc_leafs(args.dvc_files)

        ##########################
        # Get All Hyperparemters #
        ##########################
        vc = VariableCache()

        for f in list_of_hyperopt_files:
            f = str(Path('dvc/.hyperopt/' + f))
            vc.register_dvccc_file(f)

        if args.optuna:
            from dvc_cc.run import optuna_scripts
            rcc_branch_names = [exp_name+'_XXXXXXXXXX']
            create_cc_config(dvc_files, exp_name, rcc_branch_names, args.num_of_repeats,
                                args.live_output_files, args.live_output_update_frequence)
            optuna_scripts.create_optuna_directories(exp_name, vc)
            return

        ###################################
        # DEFINE ALL Hyperopt-Experiments #
        ###################################
        if len(vc.list_of_all_variables) > 0:
            hyperopt_draws = create_hyperopt_variables(vc)
            user_input = input(
                'You defined ' + str(len(hyperopt_draws)) + ' * ' + str(args.num_of_repeats) + ' = ' + str(
                    len(
                        hyperopt_draws) * args.num_of_repeats) + ' hyperoptimization pairs. Do you want to continue and start the job? [y,n]: ')
            if not user_input.lower().startswith('y'):
                print('The job was canceled')
                exit(0)
        else:
            hyperopt_draws = [[]]

        loaded_yml = None


        #####################################################
        # TODO: SAVE the Hyperopt-Values and the VC!        #
        #   WITH THIS It is possible to get rerun the code. #
        #####################################################

        ######################################
        # TODO: DEFINE THE NEW BRANCH NAMES! #
        ######################################
        rcc_branch_names = define_the_rcc_branch_names(exp_name, hyperopt_draws, vc.list_of_all_variables)

        #################################
        # Loop each Hyperopt-Experiment #
        #################################
        print(bcolors.BOLD + 'DVC-CC: Generate all dvc files.' + bcolors.ENDC)
        for i, (draw,rcc_branch_name) in enumerate(zip(hyperopt_draws, rcc_branch_names)):

            os.mkdir('dvc/'+str(rcc_branch_name))
            vc.set_values_for_hyperopt_files(draw, dvc_save_path='dvc/'+str(rcc_branch_name))

            subprocess.call(['git', 'add', 'dvc/'+str(rcc_branch_name)])

        print(bcolors.BOLD + 'DVC-CC: Build CC red yml.' + bcolors.ENDC)
        create_cc_config(dvc_files, exp_name, rcc_branch_names, args.num_of_repeats,
                                args.live_output_files, args.live_output_update_frequence)

        subprocess.call(['git', 'add', 'cc_execution_file.red.yml'])

        print(bcolors.BOLD + 'DVC-CC: Save DVC and CC files to git.' + bcolors.ENDC)
        subprocess.call(['git', 'commit', '-q', '-m', 'DVC-CC: created DVC and the CC red yml file.'])
        subprocess.call(['git', 'push', '-q', '-u', 'origin', exp_name + ':' + exp_name])

        print(bcolors.BOLD + 'DVC-CC: Execute jobs.' + bcolors.ENDC)
        cc_id = exec_branch(args.keyring_service)

        if os.path.exists(str(Path('.dvc_cc/cc_ids.yml'))):
            with open(str(Path('.dvc_cc/cc_ids.yml')), 'r') as f:
                loaded_yml = yaml.safe_load(f)
        else:
            loaded_yml = {}

        if exp_name in loaded_yml:
            loaded_yml[exp_name].append(cc_id)
        else:
            loaded_yml[exp_name] = [cc_id]

        with open(str(Path('.dvc_cc/cc_ids.yml')), 'w') as f:
            yaml.dump(loaded_yml, f)

        print(bcolors.BOLD + 'DVC-CC: Save the ID to git.' + bcolors.ENDC)
        subprocess.call(['git', 'add', '.dvc_cc/cc_ids.yml'])
        subprocess.call(['git', 'commit', '-q', '-m', 'DVC-CC: Start the jobs.'])
        subprocess.call(['git', 'push', '-q', '-u', 'origin', exp_name + ':' + exp_name])

    finally:
        ##########################
        # Return to START-Branch #
        ##########################
        subprocess.call(['git', 'checkout', startbranch])
        try:
            subprocess.call(['rm', '-R', '.dvc/lock'], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
            print('Information: ".dvc/lock" was removed.')
        except:
            pass

        try:
            subprocess.call(['rm', 'cc_execution_file.red.yml'], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
            print('Information: delete "cc_execution_file.red.yml')
        except:
            pass

        if 'rcc_branch_names' in locals():
            for rcc_branch_name in rcc_branch_names:
                if os.path.isdir('dvc/'+str(rcc_branch_name)):
                    try:
                        subprocess.call(['rm', '-fR', 'dvc/'+str(rcc_branch_name)], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
                    except:
                        pass

        if loaded_yml is not None:
            if os.path.exists(str(Path('.dvc_cc/cc_all_ids.yml'))):
                with open(str(Path('.dvc_cc/cc_all_ids.yml')), 'r') as f:
                    loaded_yml2 = yaml.safe_load(f)
            else:
                loaded_yml2 = {}
            loaded_yml2.update(loaded_yml)
            with open(str(Path('.dvc_cc/cc_all_ids.yml')), 'w') as f:
                yaml.dump(loaded_yml2, f)

            subprocess.call(['git', 'add', '.dvc_cc/cc_all_ids.yml'])
            subprocess.call(['git', 'commit', '-m', 'Update .dvc_cc/cc_all_ids.yml'])
            try:
                subprocess.call(['git', 'push'])
            except:
                print(bcolors.WARNING+'WARNING: It could not push the ID\' to git. This can happen if your branch is behind the remote branch. '
                      'You need to run "git pull" and "git push" to save the ID\'s in the git repository.'+bcolors.ENDC)





#check_output(["git", "status"]).decode("utf8")
        
# TODO: CHECK IF A COMMIT WAS DONE BEFORE A NEW PROJEC

#
#### Improvements:
#
# - it should be possible to check if this repo already are in the yaml file and than it should not be pushed in the file!
# 
# - the BETTER solution is to use yaml see below:
#
#
# from ruamel.yaml import YAML
# yaml = YAML(typ='safe')
#
#red = {
#  'batches': [{
#     'inputs': {},
#     'outputs': {}
#   }]
#}
#
#with open(str(Path(path), 'w') as f:
#  yaml.dump(red, f)
#

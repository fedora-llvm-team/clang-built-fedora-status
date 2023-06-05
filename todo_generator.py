import configparser
import json
from copr.v3 import Client
import os
import sys
import io
import urllib

def load_config(file):
    c = configparser.ConfigParser()
    c.read(file)
    return c

def create_copr_client(configfile = None, copr_url = None):
    if copr_url:
        config = {'copr_url' : copr_url }
        return Client(config)

    return Client.create_from_config_file(configfile)

def get_package(name, pkg_list):
    for p in pkg_list:
        if p['name'] == name:
            return p

    return None

def get_combined_build_state(chroots):
    state = 'succeeded'
    for c in chroots:
        chroot = chroots[c]
        if chroot['state'] == 'failed':
            state = 'failed'
            break
    return state

def handle_missing_builds(builds_a, builds_b):
    arches = set([])
    for builds in [builds_a, builds_b]:
        for build in builds:
            arch = build.name.split('-')[-1]
            if arch not in arches:
                arches.add(arch)

    for arch in arches:
        for builds in [builds_a, builds_b]:
            if not has_arch(builds, arch):
                builds.append(create_missing_build(arch))

def add_url_build_log_field(project, packages):
    for p in packages:
        for c in p['chroots']:
            chroot = p['chroots'][c]
            chroot['url_build_log'] = "{}0{}-{}/builder-live.log{}".format(project['chroot_repos'][c], chroot['build_id'], p['name'],
                                                                      ".gz" if chroot['state'] != 'running' else "")
            chroot['url_resubmit'] = 'https://copr.fedorainfracloud.org/coprs/g/{}/repeat_build/{}/'.format(project['full_name'][1:], chroot['build_id'])

def add_url_rebuild_field(project, packages):
    for p in packages:
        p['url_rebuild'] = "https://copr.fedorainfracloud.org/coprs/g/{}/package/{}/rebuild".format(project['full_name'][1:], p['name'])

config_file = './config.ini'
if len(sys.argv) == 2:
    config_file = sys.argv[1]
config = load_config(file=config_file)
client_next = create_copr_client(copr_url = config.get('next', 'url', fallback = None),
                                 configfile = config.get('next', 'config', fallback = None))
client_current = create_copr_client(copr_url = config.get('current', 'url', fallback = None),
                                    configfile = config.get('current', 'config', fallback = None))

missing = []
failed = []

project_current = client_current.project_proxy.get(config['current']['owner'], config['current']['project'])
project_next = client_current.project_proxy.get(config['next']['owner'], config['next']['project'])

response = client_next.monitor_proxy.monitor(config['next']['owner'], config['next']['project'])
packages_next = response['packages']
response = client_current.monitor_proxy.monitor(config['current']['owner'], config['current']['project'])
packages_current = response['packages']

add_url_build_log_field(project_current, packages_current)
add_url_build_log_field(project_next, packages_next)
add_url_rebuild_field(project_current, packages_current)
add_url_rebuild_field(project_next, packages_next)
#print(json.dumps(packages_next))

results = {}

next_chroot = list(project_next['chroot_repos'].keys())[0]
next_os_version = "-".join(next_chroot.split('-')[0:2])
try:
    filename = f'status/{next_os_version}.cfg'
    notes_file = open(filename)
    notes_cfg = configparser.ConfigParser()
    notes_cfg.optionxform = str
    notes_cfg.read_file(notes_file)
except Exception as e:
    try:
        notes_file=open('status/' + os.path.basename(config_file)[:-4] + ".cfg")
        notes_cfg = configparser.ConfigParser()
        notes_cfg.optionxform = str
        notes_cfg.read_file(notes_file)
    except Exception as e:
        print(e, f"Failed to load notes file: {filename}")
        notes_cfg = {'willfix' : {}, 'wontfix' : {}}

for p in packages_next:
    state = get_combined_build_state(p['chroots'])
    if state == 'succeeded':
        continue

    if p['name'] in notes_cfg['wontfix']:
        continue

    failed.append(p)

for p_next in failed:
    p_current = get_package(p_next['name'], packages_current)
    if not p_current:
        p_current = {'name' : p_next['name'], 'chroots' : {} }
    for c in project_current['chroot_repos']:
        if c in p_current['chroots']:
            continue
        p_current['chroots'][c] = { 'state' : 'missing', 'url_build_log' : '' } 
    result = {}
    result['name'] = p_next['name']
    result['os_version'] = next_os_version
    result['builds_a'] = p_current
    result['builds_b'] = p_next
    result['note'] = ''
    if p_next['name'] in notes_cfg['willfix']:
        result['note'] = notes_cfg['willfix'][p_next['name']]

    results[p_next['name']] = result

with open("packages.json", "w") as out:
    json.dump(results, out, indent=2)

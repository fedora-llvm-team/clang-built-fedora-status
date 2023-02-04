import json
import configparser
from copr.v3 import Client
from munch import Munch
import sys


def load_config(file):
    c = configparser.ConfigParser()
    c.read(file)
    return c

def create_missing_package(name):
    return Munch(name = name, state = 'missing', builds = {'latest' : None })

def create_missing_build(arch):
    return Munch(name = arch, state = 'missing', result_url = '')

def retrieve_packages(client, project_owner, project_name):
    response = client.monitor_proxy.monitor(project_owner, project_name, additional_fields = ['url_build_log'])
    return response['packages']

def get_package(name, pkg_list):
    for p in pkg_list:
        if p['name'] == name:
            return p

def handle_missing_packages(packages_a, packages_b):

    for p_a in packages_a:
        p_b = get_package(p_a['name'], packages_b)
        if not p_b:
            packages_b.append({'name' : p_a['name'], 'chroots' : {} })

    for p_b in packages_b:
        p_a = get_package(p_b['name'], packages_a)
        if not p_a:
            packages_a.append({'name' : p_b['name'], 'chroots' : {} })

def get_chroot_arch(chroot):
    return chroot.split('-')[-1]

def has_arch(builds, arch):
    for build in builds:
        if get_chroot_arch(build.name) == arch:
            return True
    return False

def retrieve_builds(client, package):

    latest_build = package.builds['latest']
    if not latest_build:
        return []

    # When a build has state of succeeded, we don't need to query COPR for
    # more information, because we know the builds have succeeded for all
    # chroots.  A 'failed' state means that there was at least 1 failure,
    # so in that case we still need to query COPR to see which chroots
    # suceeded and which chroots failed.
    if latest_build['state'] == 'succeeded':
        builds = []
        for c in sorted(latest_build['chroots']):
            builds.append(Munch(name=c, result_url='{}/{}/0{}-{}/'.format(latest_build['repo_url'], c, latest_build['id'], package.name),
                                           state = latest_build['state']))
        return builds


    b = client.build_chroot_proxy.get_list(package.builds['latest']['id'])
    return b


def create_copr_client(configfile = None, copr_url = None):
    if copr_url:
        config = {'copr_url' : copr_url }
        return Client(config)

    return Client.create_from_config_file(configfile)

if __name__ == '__main__':
    config_file = './config.ini'
    if len(sys.argv) == 2:
        config_file = sys.argv[1]
    config = load_config(file=config_file)
    client_a = create_copr_client(copr_url = config.get('current', 'url', fallback = None),
                                  configfile = config.get('current', 'config', fallback = None))
    client_b = create_copr_client(copr_url = config.get('next', 'url', fallback = None),
                                  configfile = config.get('next', 'config', fallback = None))
    packages_a = retrieve_packages(client_a, config['current']['owner'], config['current']['project'])
    packages_b = retrieve_packages(client_b, config['next']['owner'], config['next']['project'])
    handle_missing_packages(packages_a, packages_b)

    project_b = client_b.project_proxy.get(config['next']['owner'], config['next']['project'])
    chroot_b = list(project_b['chroot_repos'].keys())[0]
    os_version_b = "-".join(chroot_b.split('-')[0:2])
    packages = {}
    sort_key = lambda x : x['name']
    for pa, pb in zip(sorted(packages_a, key = sort_key), sorted(packages_b, key = sort_key)):
        new_package = {'name' : pa['name'],
                       'os_version' : os_version_b, 
                       'builds_a' : pa,
                       'builds_b' : pb
                      }
        packages[pa['name']] = new_package

    with open("packages.json", "w") as out:
        json.dump(packages, out, indent=2)

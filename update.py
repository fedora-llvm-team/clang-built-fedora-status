#!/usr/bin/python3

import cgi
import dnf
import rpm
import koji
import re
import datetime
import concurrent.futures
import configparser
import urllib.request
import io
from dnf.subject import Subject
import hawkey
from copr.v3 import Client
import threading
import time
import os
import sys
import subprocess
import jinja2

class CoprResults:
    def __init__(self, url, owner, project):
        self.url = url
        config = {'copr_url': url  }
        self.client = Client(config)
        self.owner = owner
        self.project = project
        try:
            self.client.base_proxy.home()
            self.packages = executor.submit(self.get_packages, clang_gcc_br_pkgs_fedora)
        except Exception as e:
            print(project, str(e), file = sys.stderr)
            self.packages = executor.submit(lambda : {})

    def get_build_link(self, pkg_id):
        return '{}/coprs/{}/{}/build/{}/'.format(self.url, self.owner.replace('@','g/'), self.project, pkg_id)

    def get_package_base_link(self):
        return '{}/coprs/{}/{}/package/'.format(self.url, self.owner.replace('@','g/'), self.project)

    def get_package_link(self, pkg):
        return '{}{}'.format(self.get_package_base_link(), pkg.name)

    def get_packages(self, clang_gcc_br_pkgs_fedora):
        pkgs = {}
        for p in self.client.package_proxy.get_list(self.owner, self.project, with_latest_succeeded_build=True, with_latest_build=True):
            build_passes = True
            pkg =  p['builds']['latest_succeeded']
            if not pkg:
                pkg =  p['builds']['latest']
                if not pkg:
                    continue
                build_passes = False
            pkg['copr'] = self
            src_version = pkg['source_package']['version']
            pkg['nvr'] = "{}-{}".format(p['name'], src_version)
            pkg['name'] = p['name']
            pkgs[p['name']] = CoprPkg(pkg, self, build_passes)
        return pkgs

    def get_file_prefix(self, is_baseline):
        if is_baseline:
            return None
        return self.project

class KojiResults:
    def __init__(self, tag, koji_url = 'https://koji.fedoraproject.org/kojihub'):
        self.tag = tag
        self.session = koji.ClientSession(koji_url)
        try:
            self.session.hello()
            self.packages = executor.submit(self.get_packages, clang_gcc_br_pkgs_fedora)
        except Exception as e:
            print(tag, str(e), file = sys.stderr)
            self.packages = executor.submit(lambda : {})


    def get_package_base_link(self):
        return "'https://koji.fedoraproject.org/koji/search?type=package&match=glob&terms="

    def get_packages(self, clang_gcc_br_pkgs_fedora):
        clang_gcc_br_pkgs = clang_gcc_br_pkgs_fedora
        tag = "{}-updates".format(self.tag)
        pkgs = {}
        for p in self.session.listTagged(tag = tag, inherit = True, latest = True):
            if not p['tag_name'].startswith(self.tag):
                continue
            if p['name'] not in clang_gcc_br_pkgs.result():
                continue

            pkgs[p['name']] = KojiPkg(p, 'https://koji.fedoraproject.org/koji/')
        return pkgs

    def get_file_prefix(self, is_baseline):
        if not is_baseline:
            return None
        return self.tag

def remove_dist_tag(pkg):
    return pkg.get_nvr_without_dist()

def remove_epoch(pkg):
    subject = Subject(pkg)
    possible_nevr = subject.get_nevra_possibilities(forms=hawkey.FORM_NEVR)
    if not len(possible_nevr):
        print("Cannot remove epoch for ", pkg, sys.stderr)
        return pkg

    nevr = possible_nevr[0]
    return "{}-{}-{}".format(nevr.name, nevr.version, nevr.release)

def get_package_link(koji_url, pkg):
    return "{}/search?type=package&match=glob&terms={}".format(
            koji_url, pkg)

def get_build_link(koji_url, pkg, search_str = None):
    return pkg.get_build_link(search_str)

def get_base_tag(tag):
    return tag.split('-')[0]

def tag_to_dist_prefix(tag):
    basetag = get_base_tag(tag)
    if basetag.startswith('f'):
        return "fc{}".format(basetag[1:])

    # eln
    return basetag

def get_build_link_with_different_dist(koji_url, pkg):
    if 'copr' in pkg:
        return pkg['copr'].get_build_link(pkg)
    tag = pkg['tag_name']
    nvr = pkg['nvr']
    #Remove everything after the dist-tag
    dist_prefix = tag_to_dist_prefix(tag)
    dist_start = nvr.find(dist_prefix)
    dist_prefix_end = dist_start + len(dist_prefix)
    search_str = nvr[0:dist_prefix_end]
    return get_build_link(koji_url, pkg, search_str)

class Pkg:
    def __init__(self, name, nvr, build_passes = True):
        self.name = name
        self.nvr = nvr
        self.build_passes = build_passes


class KojiPkg(Pkg):
    def __init__(self, pkg, koji_weburl):
        super(KojiPkg, self).__init__(pkg['name'], pkg['nvr'])
        self.pkg = pkg
        self.koji_weburl = koji_weburl

    def get_nvr_without_dist(self):
        return re.sub('\.[^.]+$','', self.nvr)

    def get_build_link(self, search_str = None):
        if not search_str:
            build = self.pkg['build_id']
            return "{}/buildinfo?buildID={}".format(self.koji_weburl, build)
        return "{}/search?type=build&match=regexp&terms={}".format(
                self.koji_weburl, search_str)
    
    def get_package_base_link(self):
        return "{}/search?type=package&match=glob&terms=".format(
                self.koji_weburl)

    def get_package_link(self):
        return "{}{}".format(self.get_package_base_link(), self.name)


class CoprPkg(Pkg):
    def __init__(self, pkg, copr_results, build_passes):
        super(CoprPkg, self).__init__(pkg['name'], pkg['nvr'], build_passes)
        self.pkg = pkg
        self. copr_results = copr_results
    
    def get_nvr_without_dist(self):
        return self.nvr

    def get_package_base_link(self):
        return self.copr_results.get_package_base_link()
    
    def get_build_link(self, koji_url, search_str = None):
        return self.copr_results.get_build_link(self.pkg['id'])

    def get_package_link(self):
        self.copr_results.get_package_link(self)


# https://koji.fedoraproject.org/koji/
class PkgCompare:

    STATUS_REGRESSION = 0
    STATUS_MISSING = 1
    STATUS_OLD = 2
    STATUS_FIXED = 3
    STATUS_FAILED = 4
    STATUS_PASS = 5

    def __init__(self, pkg):
        self.pkg = pkg
        self.other_pkg = None
        self.note = None

    def add_other_pkg(self, pkg):
        self.other_pkg = pkg

    def add_note(self, note):
        self.note = note

    def compare_nvr(self, a_nvr, b_nvr):
        subject_a = Subject(a_nvr)
        subject_b = Subject(b_nvr)
        possible_nevra_a = subject_a.get_nevra_possibilities(forms=hawkey.FORM_NEVR)
        if not len(possible_nevra_a):
            return 1
        possible_nevra_b = subject_b.get_nevra_possibilities(forms=hawkey.FORM_NEVR)
        if not len(possible_nevra_b):
            return -1
        nevra_a = possible_nevra_a[0]
        nevra_b = possible_nevra_b[0]
        return rpm.labelCompare(("", nevra_a.version, nevra_a.release), ("", nevra_b.version, nevra_b.release))

    def is_up_to_date(self):
        if not self.other_pkg:
            return False
        if not self.other_pkg.build_passes:
            return False
        pkg_nvr = remove_epoch(remove_dist_tag(self.pkg))
        other_nvr = remove_epoch(remove_dist_tag(self.other_pkg))

        return self.compare_nvr(pkg_nvr, other_nvr) <= 0

    def get_pkg_status(self):
        if not self.pkg.build_passes:
            return self.STATUS_FAILED
        else:
            return self.STATUS_PASS

    def get_other_pkg_status(self):
        if not self.other_pkg:
            return self.STATUS_MISSING

        if not self.other_pkg.build_passes:
            if self.get_pkg_status() == self.STATUS_PASS:
                return self.STATUS_REGRESSION
            return self.STATUS_FAILED

        # other_pkg build passes
        if not self.is_up_to_date():
            return self.STATUS_OLD

        # other pkg is up-to-date.
        if self.get_pkg_status() == self.STATUS_FAILED:
            return self.STATUS_FIXED

        return self.STATUS_PASS


    def html_row(self, index, pkg_notes):
        row_style=''
        clang_nvr=''
        build_success = False
        has_note = False

        if index % 2 == 0:
            row_style=" class='even_row'"
        if self.other_pkg:
            clang_nvr = self.other_pkg.nvr

        column2 = ''
        if not self.is_up_to_date():
            column2 = "<a target='_blank' href='{}/rebuild'>Rebuild</a>".format(self.package_base_link + self.pkg.name)

        clang_latest_build_link = ''
        clang_latest_build_text = ''
        column3 = ''
        column4 = ''
        status = self.get_other_pkg_status()
        if status == self.STATUS_FIXED or status == self.STATUS_PASS:
            column3 = "<a href='{link}'><span class='tooltip'>{clang_nvr}</span>{clang_nvr}</a>".format(
                    link = get_build_link('', self.other_pkg),
                    clang_nvr = clang_nvr)
            column4 = "SAME"
            build_success = True
        else:
            if status == self.STATUS_MISSING or status == self.STATUS_OLD:
                url = self.package_base_link + self.pkg.name
                text = 'MISSING'
            else:
                url = get_build_link('', self.other_pkg)
                text = 'FAILED'

            column3 = "<a href='{link}'>{text}</a>".format(link=url, text=text)

            if status == self.STATUS_OLD:
                column4 = "<a href='{link}'><span class='tooltip'>{clang_nvr}</span>{clang_nvr}</a>".format(
                        link = get_build_link('', self.other_pkg),
                        clang_nvr = clang_nvr)
                build_success = True
            else:
                column4 = "NONE"

        note = ""
        short_note = ""
        if self.note:
            has_note = True
            note = self.note
            short_note = self.note

        history_url = self.package_base_link + self.pkg.name
        history="<a href='{history_url}'>[Build History]</a></td>".format(history_url=history_url)
        if not use_copr and not self.other_pkg:
           history=""

        if not has_note and not build_success:
            row_style=" class='todo_row'"

        self.row_style = row_style
        self.fedora_build_url = get_build_link('https://koji.fedoraproject.org/koji/', self.pkg)
        self.nvr = self.pkg.nvr + (' (FAILED)' if use_copr and not self.pkg.build_passes else '')
        self.rebuild_link = column2
        self.clang_build_latest_url = column3
        self.clang_build_url = column4
        self.history = history
        self.note = note
        self.short_note = short_note

class Stats:
    def __init__(self):
        self.num_fedora_pkgs = 0
        self.num_clang_pkgs = 0
        self.num_up_to_date_pkgs = 0
        self.num_pass_or_note = 0

        self.num_regressions = 0
        self.num_fixed = 0
        self.num_missing = 0

    def html_color_for_percent(percent):
        return 'black'
        if percent < 33.3:
            return 'red'
        if percent < 66.7:
            return '#CC9900'
        return 'green'


def get_gcc_clang_users_fedora():
    # Repo setup
    base = dnf.Base()
    conf = base.conf
    for compose in ['BaseOS', 'AppStream', 'CRB', 'Extras']:
        base.repos.add_new_repo(f'eln-{compose}-source', conf, baseurl=[f'https://odcs.fedoraproject.org/composes/production/latest-Fedora-ELN/compose/{compose}/source/tree/'])
    repos = base.repos.get_matching('*')
    repos.disable()
    repos = base.repos.get_matching('eln-*-source')
    repos.enable()

    # Find all the relevant packages
    base.fill_sack()
    q = base.sack.query()
    q = q.available()
    q = q.filter(requires=['gcc', 'gcc-c++', 'clang'])
    return set([p.name for p in list(q)])

def get_package_notes(fedora_version):
    try:
        notes_cfg = open(f'status/fedora-{fedora_version}.cfg')
    except:
        return {}
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read_file(notes_cfg)
    notes = {}
    for s in config.sections():
        notes.update(config[s])
    return notes

executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)

clang_gcc_br_pkgs_fedora = executor.submit(get_gcc_clang_users_fedora)

# Exclude clang and llvm packages.
package_exclude_list = [
    'clang',
    'compiler-rt',
    'libomp',
    'lld',
    'lldb',
    'llvm'
]

form = cgi.FieldStorage()
tags = ['f36', 'f37', 'f38', 'clang-built-f36', 'clang-built-f37', 'clang-built-f38', 'fedora-37-clang-16']
if "tag" in form:
    tag = form['tag'].value
    if tag in tags:
        tags = [tag]

use_copr = True

f35 = CoprResults(u'https://copr.fedorainfracloud.org', '@fedora-llvm-team', 'clang-built-f35')
f36 = CoprResults(u'https://copr.fedorainfracloud.org', '@fedora-llvm-team', 'clang-built-f36')
f37 = CoprResults(u'https://copr.fedorainfracloud.org', '@fedora-llvm-team', 'clang-built-f37')
f38 = CoprResults(u'https://copr.fedorainfracloud.org', '@fedora-llvm-team', 'clang-built-f38')
f37_clang16 = CoprResults(u'https://copr.fedorainfracloud.org', 'tstellar', 'fedora-37-clang-16')

comparisons = [
(KojiResults('f36'), f36),
(KojiResults('f37'), f37),
(KojiResults('f38'), f38),
(f35, f36),
(f36, f37),
(f37, f38),
(f37, f37_clang16)
]

# Assume copr-reporter is in the current directory

if len(tags) !=1 and os.path.isdir('./copr-reporter'):

    pages = ['f36', 'f37', 'f38']

    print("COPR REPORTER", pages)
    old_cwd = os.getcwd()
    os.chdir('./copr-reporter')

    os.chdir(old_cwd)
    for p in pages:
        print('TODO', p)
        subprocess.call(f'python3 ./todo_generator.py ./copr-reporter/{p}.ini', shell = True)
        subprocess.call('python3 ./copr-reporter/html_generator.py', shell = True)
        subprocess.call(f'cp report.html {p}-todo.html', shell = True)

for results in comparisons:

    try:
        # Get list of package notes
        fedora_version = results[1].project[-2:]
        print("Compare: ", fedora_version)
        package_notes = executor.submit(get_package_notes, fedora_version)

        stats = Stats()

        file_prefix = results[0].get_file_prefix(True)
        if not file_prefix:
            file_prefix = results[1].get_file_prefix(False)

        if file_prefix not in tags:
            continue

        baseline_pkgs = results[0].packages
        test_pkgs = results[1].packages

        # Filter out packages form exclude list
        baseline_pkgs = baseline_pkgs.result()
        for p in package_exclude_list:
            if p in baseline_pkgs:
                del baseline_pkgs[p]

        pkg_compare_list = []
        for p in sorted(baseline_pkgs.keys()):
            pkg_compare_list.append(PkgCompare(baseline_pkgs[p]))

        stats.num_fedora_pkgs = len(pkg_compare_list)
        test_pkgs = test_pkgs.result()

        if len(baseline_pkgs) == 0 or len(test_pkgs) == 0:
            raise Exception('Failed to load package lists')

        for c in pkg_compare_list:

            c.package_base_link = results[1].get_package_base_link()

            if c.pkg.name in package_notes.result():
                c.add_note(package_notes.result()[c.pkg.name])
            elif '__error' in package_notes.result():
                c.add_note('Failed to load notes: {}'.format(package_notes.result()['__error']))

            test_pkg = test_pkgs.get(c.pkg.name, None)
            if not test_pkg:
                stats.num_missing += 1
                continue

            if test_pkg.build_passes:
                stats.num_clang_pkgs += 1
                stats.num_pass_or_note += 1
            elif c.note:
                stats.num_pass_or_note +=1

            c.add_other_pkg(test_pkg)
            if c.is_up_to_date():
                stats.num_up_to_date_pkgs += 1

            status = c.get_other_pkg_status()
            if status == c.STATUS_REGRESSION:
                stats.num_regressions += 1
            elif status == c.STATUS_FIXED:
                stats.num_fixed += 1

        loader = jinja2.FileSystemLoader(searchpath="./")
        environment = jinja2.Environment(loader=loader)
        template = environment.get_template('status-template.html')
        for index, c in enumerate(pkg_compare_list):
            c.html_row(index, package_notes.result())
        text = template.render(
          stats = stats,
          date=datetime.datetime.utcnow(),
          pkg_compare_list = pkg_compare_list
        )
        f = open('{}-status.html'.format(file_prefix), 'w')
        f.write(text)
        f.close()
    except Exception as e:
        print(e)
        continue

executor.shutdown(True)

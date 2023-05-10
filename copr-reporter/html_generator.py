import json
import datetime
import configparser
import io
import urllib.request

import jinja2


# TODO: Add a summary of the new broken packages
# TODO: Add in the summary the total amount of packages
def generate_report(title, results, description):
    loader = jinja2.FileSystemLoader(searchpath="./")
    environment = jinja2.Environment(loader=loader)
    file = "template.html"

    template = environment.get_template(file)
    text = template.render(
        title=title,
        date=datetime.datetime.now().isoformat(),
        results=results,
        description = description
    )
    report = open("report.html", 'w')
    report.write(text)
    report.close()

def get_combined_build_state(chroots):
    state = None
    for c in chroots:
        chroot = chroots[c]
        if chroot['state'] == 'failed':
            state = 'failed'
            break
        if chroot['state'] == 'succeeded':
            state = 'succeeded'
            continue
        if chroot['state'] == 'missing':
            if not state:
                state = 'missing'
            continue
    return 'failed' if not state else state


def get_state_change(chroots_a, chroots_b):
    chroots = set(chroots_a.keys()) | set(chroots_b.keys())
    state = "Same results"
    for c in chroots:
        if c not in chroots_a or c not in chroots_b:
            continue
        chroot_a = chroots_a[c]
        chroot_b = chroots_b[c]

        if chroot_a['state'] == 'succeeded' and chroot_b['state'] == 'failed':
            return 'Regression'
        if chroot_a['state'] == 'failed' and chroot_b['state'] == 'succeeded':
            state = "Fixed"
            continue
        if chroot_a['state'] != chroot_b['state']:
            state = "Something has changed. You should verify the builds"
            continue
    return state


if __name__ == '__main__':
    title = "Clang Mass Rebuild TODO dashboard"
    packages = {}
    with open("packages.json", "r") as f:
        packages = json.load(f)

    current_ver = None
    next_ver = None

    for k, v in packages.items():
        packages[k]['changed'] = 'Same results'
        state_a = get_combined_build_state(packages[k]['builds_a']['chroots'])
        state_b = get_combined_build_state(packages[k]['builds_b']['chroots'])
        packages[k]['changed'] = get_state_change(packages[k]['builds_a']['chroots'], packages[k]['builds_b']['chroots'])
        description = f"""
    Explanation of the columns:<ul>
    <li>Name: The name of the package.</li>
    <li>Builds with current Clang release on {current_ver}.</li>
    <li>Builds with next Clang release on {next_ver}.</li>
    <li>Changes: Notes so you can search results easily.</li></ul>
    """
    generate_report(title, packages, description)

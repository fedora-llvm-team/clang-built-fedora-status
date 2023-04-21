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
        if state_a == 'succeeded' and state_b == 'failed':
            packages[k]['changed'] = "Regression"
        elif state_a == 'failed' and state_b == 'succeeded':
            packages[k]['changed'] = "Fixed"
        elif state_a != state_b:
            packages[k]['changed'] = "Something has changed. You should verify the builds"
    
        description = f"""
    Explanation of the columns:<ul>
    <li>Name: The name of the package.</li>
    <li>Builds with current Clang release on {current_ver}.</li>
    <li>Builds with next Clang release on {next_ver}.</li>
    <li>Changes: Notes so you can search results easily.</li></ul>
    """
    generate_report(title, packages, description)

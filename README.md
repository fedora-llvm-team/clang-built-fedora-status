# Clang Built RPMS

## How to build packages

You can fetch the package sources from fedora dist-git and you can build
the packages locally using [mock](https://github.com/rpm-software-management/mock).

First you need to install the relevant mock config file from ./mock-configs
in /etc/mock/

It's also recommended that you use fedpkg (which has a wrapper around mock) to
do the builds since this simplifies the process.

```bash
# Clone the repo
fedpkg clone lld
cd lld

# Build the RPM Package
fedpkg mockbuild --root fedora-37-clang-15-x86_64

```

If you don't want to use fepkg you can use plain mock instead.

```bash
# Clone the repo
git clone https://src.fedoraproject.org/rpms/lld.git
cd lld

# Download the sources
spec -a -g lld.spec

# Build the SRPM
mock -r fedora-37-clang-15-x86_64 --buildsrpm --spec lld.spec --sources . --resultdir .

# Build the RPM package
mock -r fedora-37-clang-15-x86_64 --rebuild

```


import hashlib
import io
import json
import logging
import os
import posixpath
import sys
import tarfile
import tempfile

from datetime import datetime
from os.path import basename, dirname, exists, join, relpath, split, splitext

log = logging.getLogger('rsconnect')
log.setLevel(logging.DEBUG)


def make_source_manifest(entrypoint, environment, appmode):
    package_manager = environment['package_manager']

    manifest = {
        "version": 1,
        "metadata": {
            "appmode": appmode,
            "entrypoint": entrypoint
        },
        "locale": environment['locale'],
        "python": {
            "version": environment['python'],
            "package_manager": {
                "name": package_manager,
                "version": environment[package_manager],
                "package_file": environment['filename']
            }
        },
        "files": {}
    }
    return manifest


def manifest_add_file(manifest, rel_path, base_dir):
    """Add the specified file to the manifest files section

    The file must be specified as a pathname relative to the notebook directory.
    """
    path = join(base_dir, rel_path)

    manifest['files'][rel_path] = {
        'checksum': file_checksum(path)
    }


def manifest_add_buffer(manifest, filename, buf):
    """Add the specified in-memory buffer to the manifest files section"""
    manifest['files'][filename] = {
        'checksum': buffer_checksum(buf)
    }


def file_checksum(path):
    """Calculate the md5 hex digest of the specified file"""
    with open(path, 'rb') as f:
        m = hashlib.md5()
        chunk_size = 64 * 1024

        chunk = f.read(chunk_size)
        while chunk:
            m.update(chunk)
            chunk = f.read(chunk_size)
        return m.hexdigest()


def buffer_checksum(buf):
    """Calculate the md5 hex digest of a buffer (str or bytes)"""
    m = hashlib.md5()
    m.update(to_bytes(buf))
    return m.hexdigest()


def to_bytes(s):
    if hasattr(s, 'encode'):
        return s.encode('utf-8')
    return s


def bundle_add_file(bundle, rel_path, base_dir):
    """Add the specified file to the tarball.

    The file path is relative to the notebook directory.
    """
    path = join(base_dir, rel_path)
    bundle.add(path, arcname=rel_path)
    log.debug('added file: %s', path)


def bundle_add_buffer(bundle, filename, contents):
    """Add an in-memory buffer to the tarball.

    `contents` may be a string or bytes object
    """
    buf = io.BytesIO(to_bytes(contents))
    fileinfo = tarfile.TarInfo(filename)
    fileinfo.size = len(buf.getvalue())
    bundle.addfile(fileinfo, buf)
    log.debug('added buffer: %s', filename)


def write_manifest(relative_dir, nb_name, environment, output_dir):
    """Create a manifest for source publishing the specified notebook.
    
    The manifest will be written to `manifest.json` in the output directory..
    A requirements.txt file will be created if one does not exist.

    Returns the list of filenames written.
    """
    manifest_filename = 'manifest.json'
    manifest = make_source_manifest(nb_name, environment, 'jupyter-static')
    manifest_file = join(output_dir, manifest_filename)
    created = []
    skipped = []
    
    manifest_relpath = join(relative_dir, manifest_filename)
    if exists(manifest_file):
        skipped.append(manifest_relpath)
    else:
        with open(manifest_file, 'w') as f:
            f.write(json.dumps(manifest, indent=2))
            created.append(manifest_relpath)
            log.debug('wrote manifest file: %s', manifest_file)

    environment_filename = environment['filename']
    environment_file = join(output_dir, environment_filename)
    environment_relpath = join(relative_dir, environment_filename)
    if exists(environment_file):
        skipped.append(environment_relpath)
    else:
        with open(environment_file, 'w') as f:
            f.write(environment['contents'])
            created.append(environment_relpath)
            log.debug('wrote environment file: %s', environment_file)

    return created, skipped


def list_files(base_dir, include_subdirs, walk=os.walk):
    """List the files in the directory at path.

    If include_subdirs is True, recursively list
    files in subdirectories.

    Returns an iterable of file paths relative to base_dir.
    """
    skip_dirs = ['.ipynb_checkpoints', '.git']

    def iter_files():
        for root, subdirs, files in walk(base_dir):
            if include_subdirs:
                for skip in skip_dirs:
                    if skip in subdirs:
                        subdirs.remove(skip)
            else:
                # tell walk not to traverse any subdirs
                subdirs[:] = []

            for filename in files:
                yield relpath(join(root, filename), base_dir)
    return list(iter_files())


def make_source_bundle(file, environment, extra_files=[]):
    """Create a bundle containing the specified notebook and python environment.

    Returns a file-like object containing the bundle tarball.
    """
    base_dir = dirname(file)
    nb_name = basename(file)

    manifest = make_source_manifest(nb_name, environment, 'jupyter-static')
    manifest_add_file(manifest, nb_name, base_dir)
    manifest_add_buffer(manifest, environment['filename'], environment['contents'])

    if extra_files:
        skip = [nb_name, environment['filename'], 'manifest.json']
        extra_files = sorted(list(set(extra_files) - set(skip)))

    for rel_path in extra_files:
        manifest_add_file(manifest, rel_path, base_dir)

    log.debug('manifest: %r', manifest)

    bundle_file = tempfile.TemporaryFile(prefix='rsc_bundle')
    with tarfile.open(mode='w:gz', fileobj=bundle_file) as bundle:

        # add the manifest first in case we want to partially untar the bundle for inspection
        bundle_add_buffer(bundle, 'manifest.json', json.dumps(manifest, indent=2))
        bundle_add_buffer(bundle, environment['filename'], environment['contents'])
        bundle_add_file(bundle, nb_name, base_dir)

        for rel_path in extra_files:
            bundle_add_file(bundle, rel_path, base_dir)

    bundle_file.seek(0)
    return bundle_file


def get_exporter(**kwargs):
    """get an exporter, raising appropriate errors"""
    # if this fails, will raise 500
    try:
        from nbconvert.exporters.base import get_exporter
    except ImportError as e:
        raise Exception("Could not import nbconvert: %s" % e)

    try:
        Exporter = get_exporter('html')
    except KeyError:
        raise Exception("No exporter for format: html")

    try:
        return Exporter(**kwargs)
    except Exception as e:
        raise Exception("Could not construct Exporter: %s" % e)


def make_html_manifest(file_name):
    return {
        "version": 1,
        "metadata": {
            "appmode": "static",
            "primary_html": file_name,
        },
    }


def make_html_bundle(file, nb_title, config_dir, ext_resources_dir, config, jupyter_log):
    ext_resources_dir = dirname(file)
    nb_name = basename(file)

    # create resources dictionary
    modified = datetime.fromtimestamp(os.stat(file).st_mtime)

    if sys.platform == 'win32':
        date_format = "%B %d, %Y"
    else:
        date_format = "%B %-d, %Y"

    resource_dict = {
        "metadata": {
            "name": nb_title,
            "modified_date": modified.strftime(date_format)
        },
        "config_dir": config_dir
    }

    if ext_resources_dir:
        resource_dict['metadata']['path'] = ext_resources_dir

    exporter = get_exporter(config=config, log=jupyter_log)
    output, resources = exporter.from_filename(file, resources=resource_dict)

    filename = splitext(nb_name)[0] + resources['output_extension']
    log.info('filename = %s' % filename)

    bundle_file = tempfile.TemporaryFile(prefix='rsc_bundle')

    with tarfile.open(mode='w:gz', fileobj=bundle_file) as bundle:
        bundle_add_buffer(bundle, filename, output)

        # manifest
        manifest = make_html_manifest(filename)
        log.debug('manifest: %r', manifest)
        bundle_add_buffer(bundle, 'manifest.json', json.dumps(manifest))

    # rewind file pointer
    bundle_file.seek(0)
    return bundle_file
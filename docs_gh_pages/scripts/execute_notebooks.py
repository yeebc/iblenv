import os
import json
import time
import numpy as np
from nbconvert.preprocessors import (ExecutePreprocessor, CellExecutionError,
                                     ClearOutputPreprocessor)
from nbconvert.exporters import RSTExporter
from nbconvert.writers import FilesWriter
import nbformat
import re
import sphinx_gallery.notebook as sph_nb
import sphinx_gallery.gen_gallery as gg
import shutil
import logging
from pathlib import Path

_logger = logging.getLogger('ibllib')
IPYTHON_VERSION = 4


class NotebookConverter(object):

    def __init__(self, nb_path, output_path=None, rst_template=None, colab_template=None,
                 overwrite=True, kernel_name=None):
        """
        Parameters
        ----------
        nb_path : str
            Path to ipython notebook
        output_path: str, default=None
            Path to where executed notebook, rst file and colab notebook will be saved. Default is
            to save in same directory of notebook
        rst_template: str, default=None
            Path to rst template file used for styling during RST conversion. If not specified,
            uses default template in nbconvert
        colab_template: str, default=None
            Path to colab code to append to notebook to make it colab compatible. If colab=True but
            colab_template not specified, the code skips colab conversion bit
        overwrite: bool, default=True
            Whether to save executed notebook as same filename as unexecuted notebook or create new
            file with naming convention 'exec_....'. Default is to write to same file
        kernel_name: str
            Kernel to use to run notebooks. If not specified defaults to 'python3'
        """
        self.nb_path = Path(nb_path).absolute()
        self.nb_link_path = Path(__file__).parent.parent.joinpath('notebooks_external')
        os.makedirs(self.nb_link_path, exist_ok=True)
        self.nb = self.nb_path.parts[-1]
        self.nb_dir = self.nb_path.parent
        self.nb_name = self.nb_path.stem
        self.overwrite = overwrite

        # If no output path is specified save everything into directory containing notebook
        if output_path is not None:
            self.output_path = Path(output_path).absolute()
            os.makedirs(self.output_path, exist_ok=True)
        else:
            self.output_path = self.nb_dir

        # If a rst template is passed
        if rst_template is not None:
            self.rst_template = Path(rst_template).absolute()
        else:
            self.rst_template = None

        if colab_template is not None:
            self.colab_template = Path(colab_template).absolute()
        else:
            self.colab_template = None

        self.colab_nb_path = self.output_path.joinpath(f'colab_{self.nb}')

        # If overwrite is True, write the executed notebook to the same name as the notebook
        if self.overwrite:
            self.executed_nb_path = self.output_path.joinpath(self.nb)
            self.temp_nb_path = self.output_path.joinpath(f'executed_{self.nb}')
        else:
            self.executed_nb_path = self.output_path.joinpath(f'executed_{self.nb}')

        if kernel_name is not None:
            self.execute_kwargs = dict(timeout=900, kernel_name=kernel_name, allow_errors=False)
        else:
            self.execute_kwargs = dict(timeout=900, kernel_name='python3', allow_errors=False)

    @staticmethod
    def py_to_ipynb(py_path):
        """
        Convert python script to ipython notebook
        Returns
        -------
        """
        nb_path = sph_nb.replace_py_ipynb(py_path)
        if not Path(nb_path).exists():
            file_conf, blocks = sph_nb.split_code_and_text_blocks(py_path)
            gallery_config = gg.DEFAULT_GALLERY_CONF
            gallery_config['first_notebook_cell'] = None
            example_nb = sph_nb.jupyter_notebook(blocks, gallery_config, nb_path)

            code = example_nb['cells'][1]['source'][0]
            # If using mayavi add in the notebook initialisation so that figures render properly
            if re.search("from mayavi import mlab", code):
                if not re.search("mlab.init_notebook()", code):
                    new_code = re.sub("from mayavi import mlab",
                                      "from mayavi import mlab\nmlab.init_notebook()", code)
                    example_nb['cells'][1]['source'][0] = new_code
            sph_nb.save_notebook(example_nb, nb_path)
        return nb_path

    def link(self):
        """
        Create nb_sphinx link file for notebooks external to the docs directory
        """
        link_path = os.path.relpath(self.nb_path, self.nb_link_path)
        link_dict = {"path": link_path}
        link_save_path = self.nb_link_path.joinpath(str(self.nb_name) + '.nblink')

        with open(link_save_path, 'w') as f:
            json.dump(link_dict, f)

    def execute(self, force=False):
        """
        Executes the specified notebook file, and optionally write out the executed notebook to a
        new file.
        Parameters
        ----------
        write : bool, optional
            Write the executed notebook to a new file, or not.
        Returns
        -------
        executed_nb_path : str, ``None``
            The path to the executed notebook path, or ``None`` if ``write=False``.
        """

        with open(self.nb_path) as f:
            nb = nbformat.read(f, as_version=IPYTHON_VERSION)

        is_executed = nb['metadata'].get('docs_executed')

        if is_executed == 'executed' and not force:
            _logger.info(f"Notebook {self.nb} in {self.nb_dir} already executed, skipping")
        else:

            # Execute the notebook
            _logger.info(f"Executing notebook {self.nb} in {self.nb_dir}")
            t0 = time.time()

            clear_executor = ClearOutputPreprocessor()
            executor = ExecutePreprocessor(**self.execute_kwargs)

            # First clean up the notebook and remove any cells that have been run
            clear_executor.preprocess(nb, {})

            try:
                executor.preprocess(nb, {'metadata': {'path': self.nb_dir}})
                execute_dict = {'docs_executed': 'executed'}
                nb['metadata'].update(execute_dict)
            except CellExecutionError as err:
                execute_dict = {'docs_executed': 'errored'}
                nb['metadata'].update(execute_dict)
                _logger.error(f"Error executing notebook {self.nb}")
                _logger.error(err)

            _logger.info(f"Finished running notebook ({time.time() - t0})")

            _logger.info(f"Writing executed notebook to {self.executed_nb_path}")
                # Makes sure original notebook isn't left blank in case of error during writing
            if self.overwrite:
                with open(self.temp_nb_path, 'w', encoding='utf-8') as f:
                #with open(self.temp_nb_path, 'w') as f:
                    nbformat.write(nb, f)
                shutil.copyfile(self.temp_nb_path, self.executed_nb_path)
                os.remove(self.temp_nb_path)
            else:
                with open(self.executed_nb_path, 'w', encoding='utf-8') as f:
                #with open(self.temp_nb_path, 'w') as f:
                    nbformat.write(nb, f)

        return self.executed_nb_path

    def convert(self):
        """
        Converts the executed notebook to a restructured text (RST) file.
        Returns
        -------
        output_file_path : str``
            The path to the converted notebook
        """

        # Only convert if executed notebook exists
        if not os.path.exists(self.executed_nb_path):
            raise IOError("Executed notebook file doesn't exist! Expected: {0}"
                          .format(self.executed_nb_path))

        # Initialize the resources dict
        resources = dict()
        resources['unique_key'] = self.nb_name

        # path to store extra files, like plots generated
        resources['output_files_dir'] = 'nboutput/'

        # Exports the notebook to RST
        _logger.info("Exporting executed notebook to RST format")
        exporter = RSTExporter()

        # If a RST template file has been specified use this template
        if self.rst_template:
            exporter.template_file = self.rst_template

        output, resources = exporter.from_filename(self.executed_nb_path, resources=resources)

        # Write the output RST file
        writer = FilesWriter()
        output_file_path = writer.write(output, resources, notebook_name=self.nb_name)

        return output_file_path

    def append(self):
        """
        Append cells required to run in google colab to top of ipynb file. If you want to apply
        this on the unexecuted notebook, must run append method before execute!!
        Returns
        -------
        colab_file_path : str
            The path to the colab notebook
        """

        if self.colab_template is None:
            _logger.warning("No colab template specified, skipping this step")
            return

        else:
            # Read in the colab template
            with open(self.colab_template, 'r') as f:
                colab_template = f.read()
                colab_dict = json.loads(colab_template)
                colab_cells = colab_dict['cells']

            # Read in the notebook
            with open(self.nb_path, 'r') as file:
                nb = file.read()
                nb_dict = json.loads(nb)
                nb_cells = nb_dict['cells']

            colab_nb = nb_dict.copy()
            # Assumes the first cell of nb is the title
            colab_nb['cells'] = list(np.concatenate([[nb_cells[0]], colab_cells, nb_cells[1:]]))

            # Make sure colab notebooks are never executed with nbsphinx
            nb_sphinx_dict = {"nbsphinx": {"execute": "never"}}
            colab_nb['metadata'].update(nb_sphinx_dict)

            with open(self.colab_nb_path, 'w') as json_file:
                json.dump(colab_nb, json_file, indent=1)

            return self.colab_nb_path

    def unexecute(self):
        """
        Unexecutes the notebook i.e. removes all output cells
        """
        _logger.info(f"Cleaning up notebook {self.nb} in {self.nb_dir}")
        if not self.executed_nb_path.exists():
            _logger.warning(f"{self.executed_nb_path} not found, nothing to clean")
            return

        with open(self.executed_nb_path) as f:
            nb = nbformat.read(f, as_version=IPYTHON_VERSION)

        if nb['metadata'].get('docs_executed', None):
            nb['metadata'].pop('docs_executed')
        clear_executor = ClearOutputPreprocessor()
        clear_executor.preprocess(nb, {})

        with open(self.executed_nb_path, 'w') as f:
            nbformat.write(nb, f)


def process_notebooks(nbfile_or_path, execute=True, force=False, link=False, cleanup=False,
                      filename_pattern='', rst=False, colab=False, **kwargs):
    """
    Execute and optionally convert the specified notebook file or directory of
    notebook files.
    Wrapper for `NotebookConverter` class that does all the file handling.
    Parameters
    ----------
    nbfile_or_path : str
        Either a single notebook filename or a path containing notebook files.
    execute : bool
        Whether or not to execute the notebooks
    link : bool, default = False
        Whether to create nbsphink link file
    cleanup : bool, default = False
        Whether to unexecute notebook and clean up files. To clean up must set this to True and
        execute argument to False
    filename_pattern: str, default = ''
        Filename pattern to look for in .py or .ipynb files to include in docs
    rst : bool, default=False
        Whether to convert executed notebook to rst format
    colab : bool, default=False
        Whether to make colab compatible notebook
    **kwargs
        Other keyword arguments that are passed to the 'NotebookExecuter'
    """

    if os.path.isdir(nbfile_or_path):
        # It's a path, so we need to walk through recursively and find any
        # notebook files
        for root, dirs, files in os.walk(nbfile_or_path):
            for name in files:

                _, ext = os.path.splitext(name)
                full_path = os.path.join(root, name)

                # skip checkpoints
                if 'ipynb_checkpoints' in full_path:
                    if cleanup:
                        os.remove(full_path)
                        continue
                    else:
                        continue

                # if name starts with 'exec' and cleanup=True delete the notebook
                if name.startswith('exec'):
                    if cleanup:
                        os.remove(full_path)
                        continue
                    else:
                        continue

                # if name starts with 'colab' and cleanup=True delete colab notebook
                if name.startswith('colab'):
                    if cleanup:
                        os.remove(full_path)
                        continue
                    else:
                        continue

                # if name rst file and cleanup=True delete file
                if ext == '.rst':
                    if cleanup:
                        os.remove(full_path)
                        continue
                    else:
                        continue

                # if file has 'ipynb' extension create the NotebookConverter object
                if ext == '.ipynb':
                    if re.search(filename_pattern, name):
                        nbc = NotebookConverter(full_path, **kwargs)
                        # Want to create the link file
                        if link:
                            nbc.link()
                        # Execute the notebook
                        if execute:
                            nbc.execute(force=force)
                        # If cleanup is true and execute is false unexecute the notebook
                        if cleanup:
                            nbc.unexecute()

                # if file has 'py' extension convert to '.ipynb' and then execute
                if ext == '.py':
                    if re.search(filename_pattern, name):
                        # See if the ipynb version already exists
                        ipy_path = sph_nb.replace_py_ipynb(full_path)
                        if Path(ipy_path).exists():
                            # If it does and we want to execute, skip as it would have been
                            # executed above already
                            if execute:
                                continue
                            # If cleanup then we want to delete this file
                            if cleanup:
                                os.remove(ipy_path)
                        else:
                            # If it doesn't exist, we need to make it
                            full_path = NotebookConverter.py_to_ipynb(full_path)
                            nbc = NotebookConverter(full_path, **kwargs)
                            if link:
                                nbc.link()
                            # Execute the notebook
                            if execute:
                                nbc.execute(force=force)


    else:
        # If a single file is passed in
        nbc = NotebookConverter(nbfile_or_path, **kwargs)
        if execute:
            nbc.execute(force=force)
        # If cleanup is true and execute is false unexecute the notebook
        elif not execute and cleanup:
            nbc.unexecute()

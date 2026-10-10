Docker
======

The community maintains a docker image, which can be found
`on DockerHub <https://hub.docker.com/r/manimcommunity/manim>`__.
For our image ``manimcommunity/manim``, there are the following tags:

- ``latest``: the most recent version corresponding
  to `the main branch <https://github.com/ManimCommunity/manim>`__,
- ``stable``: the latest released version (according to
  `the releases page <https://github.com/ManimCommunity/manim/releases>`__),
- ``vX.Y.Z``: any particular released version (according to
  `the releases page <https://github.com/ManimCommunity/manim/releases>`__).

.. note::

   When using Manim's CLI within a Docker container, options that launch host
   applications, such as ``-p`` and ``--show_in_file_browser``, are not
   supported. Live preview also requires explicit display forwarding.

.. note::

   The Docker image ships with a minimal TeX Live installation. In particular,
   ``ctex`` is not installed by default. If your scenes rely on
   ``TexTemplateLibrary.ctex``, add it in a derived image (see below), or run
   ``docker exec --user root CONTAINER tlmgr install ctex`` in a persistent
   container. The system TeX installation is root-owned; the default
   ``manimuser`` cannot modify it. Package installation uses the image's pinned
   TeX repository rather than the current rolling CTAN repository.


Basic usage of the Docker container
-----------------------------------

Assuming that you can access the docker installation on your system
from a terminal (bash / PowerShell) via ``docker``, you can
render a scene ``CircleToSquare`` in a file `test_scenes.py`
with the following command.

.. code-block:: bash

   docker run --rm -it -v "/full/path/to/your/directory:/manim" manimcommunity/manim manim -qm test_scenes.py CircleToSquare

.. tip::

   For Linux users there might be permission problems when letting the
   user in the container write to the mounted volume.
   Add ``--user="$(id -u):$(id -g)"`` to the ``docker`` CLI arguments
   to prevent the creation of output files not belonging to your user.


Instead of using the "throwaway container" approach outlined
above, you can also create a named container that you can
modify to your liking. First, run

.. code-block:: sh

   docker run -it --name my-manim-container -v "/full/path/to/your/directory:/manim" manimcommunity/manim bash


to obtain an interactive shell inside your container. Rendering uses the
non-root ``manimuser``. To install system dependencies or TeX packages, use a
root shell in another terminal, for example
``docker exec --user root -it my-manim-container bash``.

Exit the container as soon as you are satisfied. Then, before using it,
start the container by running

.. code-block:: sh

   docker start my-manim-container

which starts the container in the background. Then, to render
a scene ``CircleToSquare`` in a file ``test_scenes.py``, run

.. code-block:: sh

   docker exec -it my-manim-container manim -qm test_scenes.py CircleToSquare


Customizing the image
---------------------

For changes that should survive recreating a container, build a derived image.
For example, a Dockerfile adding Chinese TeX support can contain:

.. code-block:: dockerfile

   FROM manimcommunity/manim:stable
   USER root
   RUN tlmgr install ctex
   USER manimuser

Build it with ``docker build -t my-manim .`` and use ``my-manim`` in place of
``manimcommunity/manim``. For reproducible projects, replace ``stable`` with a
specific version or image digest. Changes made inside a throwaway container
started with ``--rm`` are discarded when it exits.

The default image continues to include TeX and Jupyter. Main and release images
are tested on both AMD64 and ARM64. Releases promote the exact tested
image digest rather than rebuilding it. For build, test, and dependency-update
instructions, see the repository's
`Docker maintenance guide <https://github.com/ManimCommunity/manim/blob/main/docker/readme.md>`__.


Running JupyterLab via Docker
-----------------------------

Another alternative to using the Docker image is to spin up a
local JupyterLab instance. To do that, simply run

.. code-block:: sh

   docker run -it -p 8888:8888 manimcommunity/manim jupyter lab --ip=0.0.0.0

and then follow the instructions in the terminal.

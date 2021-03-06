[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.1051094.svg)](https://doi.org/10.5281/zenodo.1051094)

ECE2CMOR3 Python code to CMORize and post-process EC-Earth output data.

## Required python packages:

* cmor-3.5.0 (see cmor [dependencies](https://anaconda.org/conda-forge/cmor/files))
* eccodes/gribapi (for filtering IFS output GRIB files)
* dreq (the CMIP6 data request tool drq)
* netCDF4
* cdo (version 1.9.6; only for atmosphere post-processing)
* nose, testfixtures (only for testing)
* pip (for installing python packages)
* f90nml (only for fortran namelist I/O)
* xlrd (for reading *.xlsx excel sheets)
* XlsxWriter (for writing *.xlsx excel sheets)

## Installation:

More extensive installation description can be found [here](https://dev.ec-earth.org/projects/cmip6/wiki/Installation_of_ece2cmor3) at the EC-Earth portal, including the link to an [example of running ece2cmor](https://dev.ec-earth.org/projects/cmip6/wiki/Step-by-step_guide_for_making_CMIP6_experiments#Cmorisation-with-ece2cmor-v120). The basic ece2cmor3 installation description follows below.

#### Installation & running with miniconda (strongly recommended):
The Miniconda python distribution should be installed. With miniconda all the packages can be installed within one go by the package manager `conda`. This applies also to systems where one is not allowed to install complementary python packages to the default python distribution.

##### If Miniconda is not yet installed:

Download [miniconda](https://repo.continuum.io/miniconda/) (e.g. take the latest miniconda version for python 2.7) by using `wget` and install with `bash`:
 ```shell
 wget https://repo.continuum.io/miniconda/Miniconda2-latest-Linux-x86_64.sh
 bash Miniconda2-latest-Linux-x86_64.sh -b -u -p /$HOME/miniconda2
 ```
One could consider to add the following aliases in the `.bashrc` file:
 ```shell
 mincondapath=${HOME}/miniconda2/
 alias activateminiconda='source ${mincondapath}/etc/profile.d/conda.sh; export PATH="${mincondapath}/bin:$PATH"'
 alias activateece2cmor3='activateminiconda; conda activate ece2cmor3;'
 ```


##### Download ece3cmor3 by a git checkout

For example we create the directoy ${HOME}/cmorize/ for the ece2cmor tool:

```shell
git clone https://github.com/EC-Earth/ece2cmor3.git
cd ece2cmor3
git submodule update --init --recursive
```

##### Creating a virtual conda environment and installing ece3cmor3 therein:
In the ece2cmor3 git checkout directory, type
```shell
activateminiconda                         # The alias as defined above
conda update -n base -c defaults conda    # for updating conda itself
conda env create -f environment.yml       # for linux & mac os
conda activate ece2cmor3
python setup.py install
```

##### Running ece2cmor3 inside the conda environment:

```shell
 conda activate ece2cmor3
 ece2cmor -h
 checkvars -h
 etc.
 conda deactivate
```

#### Note that the nested CMOR tables require an update once in a while: 

The CMOR tables are maintained via a nested git repository inside the ece2cmor3 git repository. 
Once in a while one of the ece2cmor3 developers will update the nested repository of the CMOR tables. 
This will be visible from the ece2cmor3 repository by a git status call, it will tell that there are "new updates" in these tables. 
In that case one has to repeat the following inside the git checkout directory:
```shell
git submodule update --init --recursive
```

#### Note for developers: 

To avoid many installation calls during development, you can symlink the installed modules to the source directory by executing
```shell
python setup.py develop;
```

#### Updating the nested CMOR table repository by maintainers:
Navigate to your git checkout directory and execute
```shell
cd ${HOME}/cmorize/ece2cmor3/ece2cmor3/resources/tables/
git pull origin master
cd ../; git add cmip6-cmor-tables
git commit cmip6-cmor-tables -m 'Update the nested CMOR tables for their updates'
git push
```

## Design:

The package consists for 2 main modules, ifs2cmor and nemo2cmor. The main api module ece2cmorlib calls initialization and processing functions in these ocean and atmosphere specific codes. The full workload is divided into tasks, which consist of a source (an IFS grib code or NEMO parameter id) and a target (a cmor3 CMIP6 table entry). The tasks are constructed by the Fortran namelist legacy loader (namloader.py) or by the new json-loader (default). The working is similar to the previous ece2cmor tool: the loader reads parameter tables and creates tasks as it receives a dictionary of desired targets from the caller script.

At execution, the nemo2cmor module searches for the sources in the NEMO output files and streams the data to cmor to rewrite it according to CMIP6 conventions. For the IFS component, the module first performs the necessary post-processing steps, creating a list of intermediate netcdf files that contain time-averaged selections of the data. Special treatment such as unit conversions and post-processing formulas are attached to the tasks as attributes, as well as the file path in which the source data resides.

# ── Xenia Dockerfile ─────────────────────────────────────────────────────────
# Uses mambaforge (conda-forge) base so that GDAL, PROJ, HDF5, and pyresample
# install as pre-compiled binaries — no compilation from source, no missing
# system libs, no PROJ_DATA path issues.
# ─────────────────────────────────────────────────────────────────────────────

FROM condaforge/mambaforge:24.3.0-0

LABEL maintainer="Michail Stamatis"
LABEL description="Xenia — MTG/FCI satellite and climate NetCDF viewer"

# ── system packages (minimal) ─────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        unzip \
        git \
    && rm -rf /var/lib/apt/lists/*

# ── conda environment ─────────────────────────────────────────────────────────
# All geospatial C extensions come from conda-forge as compiled binaries.
# pip-only packages (satpy, uxarray, pycoast, python-dotenv) added after.
RUN mamba install -y -c conda-forge \
        python=3.11 \
        numpy \
        scipy \
        xarray \
        netcdf4 \
        h5py \
        h5netcdf \
        pyresample \
        pyproj \
        proj \
        gdal \
        rasterio \
        matplotlib \
        pillow \
        fastapi \
        uvicorn \
        pydantic \
        python-multipart \
        dask \
        distributed \
    && mamba clean -afy

# ── pip-only packages ─────────────────────────────────────────────────────────
RUN pip install --no-cache-dir \
        "satpy[all]" \
        uxarray \
        pycoast \
        python-dotenv \
        trollimage \
        pyorbital \
        pykdtree

# ── application ───────────────────────────────────────────────────────────────
WORKDIR /app

# Copy backend source
COPY backend/ /app/

# Frontend (static files served by FastAPI)
COPY frontend/ /app/static/

# Data directory — mount your data here at runtime
# e.g.  docker run -v /your/data:/data ...
ENV MTG_DATA_DIR=/data
RUN mkdir -p /data

# PROJ data path — conda-forge sets this correctly, but make it explicit
ENV PROJ_DATA=/opt/conda/share/proj
ENV PROJ_LIB=/opt/conda/share/proj

# ── expose & run ──────────────────────────────────────────────────────────────
EXPOSE 8994

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8994", "--workers", "1"]

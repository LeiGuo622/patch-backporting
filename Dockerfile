# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies
# git: for GitPython
# curl: for downloading files
# universal-ctags: for code indexing
# build-essential, cmake, autoconf, automake, libtool, pkg-config: for compiling target projects (like libtiff)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    universal-ctags \
    build-essential \
    cmake \
    autoconf \
    automake \
    libtool \
    pkg-config \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI manually
RUN curl -fsSL https://download.docker.com/linux/static/stable/$(uname -m)/docker-24.0.5.tgz -o docker.tgz \
    && tar xzvf docker.tgz \
    && mv docker/docker /usr/local/bin/ \
    && rm -rf docker docker.tgz

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Change working directory to src as per usage instructions
WORKDIR /app/src

# Default command to run the application (prints help)
CMD ["python", "backporting.py", "--help"]
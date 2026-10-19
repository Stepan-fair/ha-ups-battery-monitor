FROM ghcr.io/home-assistant/generic-x86-64-homeassistant:2026.10.2
COPY requirements-ha.txt /tmp/requirements-ha.txt
RUN pip install --no-cache-dir -r /tmp/requirements-ha.txt
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /work

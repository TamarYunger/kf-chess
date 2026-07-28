FROM python:3.13-slim
WORKDIR /app

# certs/ is normally empty (just a .gitkeep) - only non-empty on a machine
# behind a TLS-intercepting proxy/filter that needs its own CA trusted
# inside the build too. update-ca-certificates is a no-op if there's
# nothing new to add, so this is harmless on any other machine.
COPY certs/ /usr/local/share/ca-certificates/
RUN update-ca-certificates

COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt
COPY . .
EXPOSE 8765
CMD ["python", "-m", "server.ws_server"]
